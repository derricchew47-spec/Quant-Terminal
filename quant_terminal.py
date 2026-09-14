# QuantumSignal ULTRA - single-file Streamlit deployment
# Upload only app.py and requirements.txt to the same GitHub directory.
# Original UI layout/styles preserved. No broker or order-submission integration.
# Default: audited original signal; unvalidated research strategies remain disabled.

from pathlib import Path
import tempfile

"""Backend-only settings. The original UI structure is unchanged."""
# Keep the audited original signal as default: candidate superiority was NOT proven.
# Research alternatives: 'pullback', 'breakout', 'resume'. These use next-day market
# entry regardless of the original limit/market switch, and remain experimental.
SIGNAL_MODEL = 'baseline'

# Optional round-2 entry/exit strategy (None keeps the audited baseline).
# Choices: structure_15, confirm_15, confirm_10, resume_15, atr20_15,
# confirm_full15. The selected confirm_10 FAILED new-stock validation.
# If exploring it, set ROUND2_STRATEGY='confirm_10' and use the EXISTING
# advanced controls: RR=1.0, partial=0.5, breakeven=1.0, conservative risk.
# Round-2 entry triggers supersede the old market/limit choice while enabled.
ROUND2_STRATEGY = None

# The final joint win-rate + net-profit selection chose atr20_15, but it also
# failed validation/cost stress. To inspect it only: ROUND2_STRATEGY='atr20_15',
# original advanced controls RR=1.5, partial=0.5, breakeven=1.5, conservative risk.

# ============================================================================
# QuantumSignal Terminal ULTRA | Enhanced Backtest Engine & Advanced Scoring
# Version: ULTRA_8.1_PATCHED
# CHANGELOG (v8.0):
# - Fix A: Replaced sidebar sliders with 3 risk presets (保守/稳健/进取), defaulted to Conservative, with an expandable advanced settings override.
# - Fix B: Corrected backtest timing logic to eliminate look-ahead bias:
#          1) Same-day exit priority: Stop-loss checks take precedence over target take-profit.
#          2) Trailing/breakeven stops calculated today apply exclusively from NEXT day onward.
#          3) Entry logic maintains strict day-t signal evaluation and day-t+1 execution.
# - Fix C: Position sizing denominator updated to include slippage & execution fees in per-share real risk.
# - Fix D: Integrated partial_tp_ratio into presets & fixed ghost trade bug when position becomes 0.
# - Fix E: Implemented full multi-ticker shared-cash portfolio backtest with daily step-by-step capital allocation.
# - Fix F: Added visible Red/Green traffic light status banner, score breakdown table, and mandatory disclaimer to diagnostic page.
# - Fix G: Handled benchmark data insufficiency (<200 points) explicitly via rolling count check without silent healthy assumption.
# - Fix H: Added raw data sanity validation filtering out impossible/corrupted OHLCV bars before indicators computation.
# - Fix I: Elevated Expectancy (R-multiple) & win rate key metrics to the absolute front of backtest result cards.
# - Fix J: Added dynamic stock pools for S&P 500 & full US market directory cached in SQLite with a strict 24-hour cache freshness rule.
# - Fix K: Added st.progress feedback for stock scanning and backtesting to prevent silent UI freezes.
# CHANGELOG (v8.1 PATCHED — surgical fixes only, no architecture changes):
# - Patch 1: Fixed `market_ok is False` identity-comparison bug (np.where returns float 0.0/1.0/nan,
#            never Python bool, so the market-breakdown filter never actually fired). Now uses `market_ok == 0`.
# - Patch 2: Preset switching (保守/稳健/进取) no longer gets permanently locked out after the user tweaks
#            any advanced slider. Switching profile now always re-applies the preset and clears the
#            "user_customized" flag; added a "🔄 重置为当前预设" button as an explicit manual reset.
# - Patch 3: R-multiple stats (平均盈利R / 平均亏损R / 期望值 Expectancy) now computed from the ACTUAL risk
#            amount committed at the time each trade was opened (per_share_risk * shares, tracked per
#            position and pro-rated across partial take-profits), instead of a fixed
#            initial_capital*risk_pct denominator that drifts out of sync as equity compounds.
#            Applied identically in simulate() and simulate_portfolio().
# - Patch 4: Corrected simulate_portfolio() docstring to match actual same-day cash reuse behavior.
# ============================================================================

import html
import math
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

VERSION = "ULTRA_8.2_SINGLE_FILE"
_cache_dir = Path(tempfile.gettempdir()) / "quantumsignal_ultra_cache"
_cache_dir.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(_cache_dir / "yfinance"))

# -----------------------------------------------------------------------------
# 1. 页面配置与 Cyberpunk 视觉样式
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="QuantumSignal Terminal ULTRA",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    header[data-testid="stHeader"] { visibility: hidden; height: 0px; }
    .stApp { background-color: #0b0e14; color: #c9d1d9; font-family: 'Fira Code', monospace, sans-serif; }
    .block-container { max-width: 1450px; padding-top: 3.5rem !important; }
    .tech-header { font-weight: 800; color: #00f0ff; text-shadow: 0 0 12px rgba(0,240,255,.35); letter-spacing: .5px; margin-bottom: 4px; }
    .tech-subtitle { color: #8b949e; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 16px; }
    .tech-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 13px; box-shadow: 0 4px 15px rgba(0,0,0,.35); margin-bottom: 10px; position: relative; overflow: hidden; }
    .tech-card::before { content: ''; position: absolute; top:0; left:0; right:0; height:2px; background: linear-gradient(90deg,#00f0ff,#7000ff); }
    .metric-title { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { font-size: 18px; font-weight: 800; color: #fff; margin-top: 5px; }
    .metric-buy { color:#ccff00; text-shadow:0 0 8px rgba(204,255,0,.25); }
    .metric-stop { color:#ff3366; text-shadow:0 0 8px rgba(255,51,102,.25); }
    .metric-good { color:#00ff66; text-shadow:0 0 8px rgba(0,255,102,.25); }
    .signal-strip { background: linear-gradient(90deg,rgba(0,240,255,.08),rgba(112,0,255,.08)); border: 1px solid #30363d; border-radius: 10px; padding: 10px 13px; margin: 8px 0 14px 0; }
    .diag-box { background: #121821; border: 1px solid #2d333b; border-radius: 8px; padding: 12px; margin-bottom: 10px; }
    .diag-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; margin-right: 6px; }
    .tag-bull { background: rgba(0,255,102,0.15); color: #00ff66; border: 1px solid #00ff66; }
    .tag-bear { background: rgba(255,51,102,0.15); color: #ff3366; border: 1px solid #ff3366; }
    .tag-neutral { background: rgba(0,240,255,0.15); color: #00f0ff; border: 1px solid #00f0ff; }
    .tag-warn { background: rgba(255,170,0,0.15); color: #ffaa00; border: 1px solid #ffaa00; }

    .status-banner-pass { background: rgba(0, 255, 102, 0.1); border: 1px solid #00ff66; border-radius: 8px; padding: 12px 16px; color: #00ff66; font-weight: bold; margin-bottom: 12px; }
    .status-banner-fail { background: rgba(255, 51, 102, 0.1); border: 1px solid #ff3366; border-radius: 8px; padding: 12px 16px; color: #ff3366; font-weight: bold; margin-bottom: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# 2. Session State / 全局路由与状态管理
# -----------------------------------------------------------------------------
NAV_OPTIONS = [
    "🚀 自动扫描 & 智能推荐",
    "🔍 单标的全量诊断",
    "🧪 策略历史回测引擎",
    "📊 自选清单监控",
]

PRESET_CONFIGS = {
    "保守": {
        "risk_pct": 0.3,
        "min_score": 75,
        "max_atr_pct": 10.0,
        "partial_tp_ratio": 0.5,
        "rr_ratio": 2.5,
        "max_pos_pct": 15.0,
        "breakeven_trigger_r": 1.0,
        "execution_mode": "稳健模式 (Limit)",
    },
    "稳健": {
        "risk_pct": 0.5,
        "min_score": 70,
        "max_atr_pct": 15.0,
        "partial_tp_ratio": 0.5,
        "rr_ratio": 2.0,
        "max_pos_pct": 20.0,
        "breakeven_trigger_r": 1.0,
        "execution_mode": "稳健模式 (Limit)",
    },
    "进取": {
        "risk_pct": 1.0,
        "min_score": 60,
        "max_atr_pct": 20.0,
        "partial_tp_ratio": 0.3,
        "rr_ratio": 1.5,
        "max_pos_pct": 30.0,
        "breakeven_trigger_r": 1.5,
        "execution_mode": "追势模式 (Market)",
    },
}

if "target_page" in st.session_state and st.session_state.target_page:
    st.session_state.current_page = st.session_state.target_page
    st.session_state.target_page = None

for key, val in [
    ("current_page", NAV_OPTIONS[0]),
    ("selected_ticker", "AAPL"),
    ("scan_results", []),
    ("scan_errors", []),
    ("risk_profile", "保守"),
    ("rr_ratio", PRESET_CONFIGS["保守"]["rr_ratio"]),
    ("risk_pct", PRESET_CONFIGS["保守"]["risk_pct"]),
    ("max_pos_pct", PRESET_CONFIGS["保守"]["max_pos_pct"]),
    ("min_score", PRESET_CONFIGS["保守"]["min_score"]),
    ("capital", 10000.0),
    ("partial_tp_ratio", PRESET_CONFIGS["保守"]["partial_tp_ratio"]),
    ("breakeven_trigger_r", PRESET_CONFIGS["保守"]["breakeven_trigger_r"]),
    ("execution_mode", PRESET_CONFIGS["保守"]["execution_mode"]),
    ("max_atr_pct", PRESET_CONFIGS["保守"]["max_atr_pct"]),
    ("min_dollar_vol", 10.0),  # 百万美元为单位
    ("max_bias_pct", 15.0),
    ("portfolio_max_slots", 5),
    ("portfolio_mode", "组合模式 (共享资金)"),
    ("user_customized", False),
]:
    if key not in st.session_state:
        st.session_state[key] = val


# -----------------------------------------------------------------------------
# 3. 风控与配置模型
# -----------------------------------------------------------------------------
class Config:
    def __init__(
        self,
        rr=2.0,
        risk_pct=0.5,
        max_position_pct=20.0,
        min_dollar_volume=10_000_000,
        min_price=2.0,
        max_atr_pct=15.0,
        min_score=70,
        fee_bps=5.0,
        slip_bps=5.0,
        partial_tp_ratio=0.5,
        breakeven_trigger_r=1.0,
        execution_mode="稳健模式 (Limit)",
        max_bias_pct=15.0,
        portfolio_max_slots=5,
    ):
        self.rr = float(rr)
        self.risk_pct = float(risk_pct)
        self.max_position_pct = float(max_position_pct)
        self.min_dollar_volume = float(min_dollar_volume)
        self.min_price = float(min_price)
        self.max_atr_pct = float(max_atr_pct)
        self.min_score = int(min_score)
        self.fee_bps = float(fee_bps)
        self.slip_bps = float(slip_bps)
        self.partial_tp_ratio = float(partial_tp_ratio)
        self.breakeven_trigger_r = float(breakeven_trigger_r)
        self.execution_mode = str(execution_mode)
        self.max_bias_pct = float(max_bias_pct)
        self.portfolio_max_slots = int(portfolio_max_slots)


def cfg_from_session():
    return Config(
        rr=st.session_state.rr_ratio,
        risk_pct=st.session_state.risk_pct,
        max_position_pct=st.session_state.max_pos_pct,
        min_score=st.session_state.min_score,
        partial_tp_ratio=st.session_state.partial_tp_ratio,
        breakeven_trigger_r=st.session_state.breakeven_trigger_r,
        execution_mode=st.session_state.execution_mode,
        max_atr_pct=st.session_state.max_atr_pct,
        min_dollar_volume=st.session_state.min_dollar_vol * 1_000_000,
        max_bias_pct=st.session_state.max_bias_pct,
        portfolio_max_slots=st.session_state.portfolio_max_slots,
    )


# -----------------------------------------------------------------------------
# 4. 预设池与 SQLite 数据库 (任务J: 动态股票池 & 24小时SQLite缓存)
# -----------------------------------------------------------------------------
INDEX_PRESET_POOLS = {
    "🔥 核心巨头与科技 (15只)": ["MU", "NVDA", "AAPL", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN"],
    "🧬 生物医药与前沿医疗": ["LLY", "NVO", "MRNA", "BNTX", "REGN", "VRTX", "CRSP", "EDIT", "BEAM", "ILMN", "AMGN", "GILD", "BIIB", "TMO", "PFE"],
    "💻 半导体与芯片产业链": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "MU", "TXN", "AMAT", "LRCX", "ADI", "KLAC", "ARM", "MRVL"],
    "🌐 S&P 500 成分股 (动态抓取)": "DYNAMIC_SP500",
    "🏛️ 美股全市场目录 (动态抓取)": "DYNAMIC_ALL_US",
}


def parse_symbols(text):
    if isinstance(text, list):
        items = text
    else:
        items = re.split(r"[,，;；\s]+", str(text).strip().upper())
    out = []
    for symbol in items:
        symbol = str(symbol).replace(".", "-").strip()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


DB_FILE = "quant_terminal_ultra.db"


def init_quant_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT, category TEXT, added_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS pool_cache (pool_name TEXT PRIMARY KEY, symbols TEXT, updated_at TEXT)")
    conn.commit()
    conn.close()


def add_to_watchlist(symbol):
    syms = parse_symbols(symbol)
    if syms:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)", (syms[0], syms[0], "自选标的", datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()


def remove_from_watchlist(symbol):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
    conn.commit()
    conn.close()


def get_watchlist():
    conn = sqlite3.connect(DB_FILE)
    frame = pd.read_sql_query("SELECT * FROM watchlist ORDER BY symbol", conn)
    conn.close()
    return frame


def get_cached_pool(pool_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT symbols, updated_at FROM pool_cache WHERE pool_name=?", (pool_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        symbols_str, updated_at_str = row
        updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() - updated_at < timedelta(hours=24):
            return parse_symbols(symbols_str), updated_at_str, True
        return parse_symbols(symbols_str), updated_at_str, False
    return None, None, False


def save_cached_pool(pool_name, symbols):
    conn = sqlite3.connect(DB_FILE)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    symbols_str = ",".join(symbols)
    conn.execute("INSERT OR REPLACE INTO pool_cache VALUES (?, ?, ?)", (pool_name, symbols_str, now_str))
    conn.commit()
    conn.close()


def fetch_dynamic_pool(pool_type):
    cached_syms, last_updated, is_fresh = get_cached_pool(pool_type)
    if is_fresh and cached_syms:
        return cached_syms, f"数据来源：24小时内本地缓存 (更新于 {last_updated})"

    new_syms = []
    try:
        if pool_type == "DYNAMIC_SP500":
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            df_sp = tables[0]
            col = "Symbol" if "Symbol" in df_sp.columns else df_sp.columns[0]
            new_syms = [str(s).replace(".", "-").strip() for s in df_sp[col].dropna()]
        elif pool_type == "DYNAMIC_ALL_US":
            url = "http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                lines = res.text.strip().split("\n")
                for line in lines[1:]:
                    parts = line.split("|")
                    if len(parts) >= 2 and parts[1] != "File Creation Time":
                        sym = parts[0].strip()
                        is_etf = parts[3].strip() if len(parts) > 3 else "N"
                        if is_etf != "Y" and sym and not sym.endswith("$"):
                            new_syms.append(sym.replace(".", "-"))
    except Exception as err:
        if cached_syms:
            return cached_syms, f"⚠️ 动态网络抓取失败 ({err})，已使用历史缓存 (更新于 {last_updated})"
        fallback = INDEX_PRESET_POOLS["🔥 核心巨头与科技 (15只)"]
        return fallback, f"⚠️ 动态抓取失败且无缓存 ({err})，已降级使用预设小池"

    if new_syms:
        save_cached_pool(pool_type, new_syms)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return new_syms, f"🟢 成功实时更新 (时间：{now_str})"
    elif cached_syms:
        return cached_syms, f"⚠️ 抓取到的列表为空，已使用历史缓存 (更新于 {last_updated})"
    else:
        return INDEX_PRESET_POOLS["🔥 核心巨头与科技 (15只)"], "⚠️ 抓取结果为空，降级使用预设小池"


init_quant_db()


# -----------------------------------------------------------------------------
# 5. 行情与多维精细评分矩阵 (任务H: 数据清洗校验 & 任务G: 200日线数据充足性校验)
# -----------------------------------------------------------------------------


def wilder(series: pd.Series, n: int = 14) -> pd.Series:
    if len(series) < n:
        return pd.Series(np.nan, index=series.index)

    values = series.to_numpy(dtype=float)
    sma_init = values[:n].mean()

    initial_series = pd.Series(np.nan, index=series.index)
    initial_series.iloc[n - 1] = sma_init
    initial_series.iloc[n:] = series.iloc[n:]

    res = initial_series.ewm(alpha=1.0 / n, adjust=False).mean()
    return res


def _base_indicators(frame, benchmark=None):
    d = frame.copy()
    c, h, l, v = d.Close, d.High, d.Low, d.Volume

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["TR"] = tr
    d["ATR"] = wilder(tr, 14)

    for n in (10, 20, 50, 200):
        d[f"MA{n}"] = c.rolling(n).mean()
    d["EMA10"] = c.ewm(span=10, adjust=False).mean()
    d["EMA20"] = c.ewm(span=20, adjust=False).mean()

    # 布林带宽度与唐奇安通道
    std20 = c.rolling(20).std()
    d["BBUpper"] = d.MA20 + (std20 * 2)
    d["BBLower"] = d.MA20 - (std20 * 2)
    d["BBWidth"] = (d.BBUpper - d.BBLower) / d.MA20
    d["DonchianHigh20"] = h.rolling(20).max()
    d["DonchianLow10"] = l.rolling(10).min()

    # RSI
    delta = c.diff()
    gain = wilder(delta.clip(lower=0), 14)
    loss = wilder(-delta.clip(upper=0), 14)

    rsi = pd.Series(np.nan, index=c.index)
    both_zero = (gain == 0) & (loss == 0)
    loss_zero_gain_pos = (loss == 0) & (gain > 0)
    normal_mask = (loss > 0) & gain.notna() & loss.notna()

    rsi[both_zero] = 50.0
    rsi[loss_zero_gain_pos] = 100.0

    rs = gain[normal_mask] / loss[normal_mask]
    rsi[normal_mask] = 100.0 - (100.0 / (1.0 + rs))
    d["RSI"] = rsi

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACDSignal"] = d.MACD.ewm(span=9, adjust=False).mean()
    d["Hist"] = d.MACD - d.MACDSignal

    d["VolMA20"] = v.rolling(20).mean()
    d["VolRatio"] = v / d.VolMA20.replace(0, np.nan)
    d["DollarVolume"] = c * d.VolMA20
    d["BiasMA20"] = (c - d.MA20) / d.MA20 * 100.0

    d["ATRpct"] = d.ATR / c * 100
    d["Support"] = l.rolling(20).min()
    d["Return63"] = c.pct_change(63, fill_method=None)

    # [任务G]: 大盘数据充足性校验
    if benchmark is not None and not benchmark.empty:
        b = benchmark.Close.reindex(d.index)
        d["Relative63"] = (d.Return63 - b.pct_change(63, fill_method=None)) * 100
        b_count = b.rolling(200).count()
        b_ma200 = b.rolling(200).mean()
        d["MarketCount"] = b_count
        d["MarketMA200"] = b_ma200
        d["MarketOK"] = np.where(b_count >= 200, b > b_ma200, np.nan)
    else:
        d["Relative63"] = 0.0
        d["MarketCount"] = 0
        d["MarketOK"] = True

    # 评分拆解计算
    d["ScoreTrend"] = (
        (c > d.EMA10).astype(int) * 10
        + (d.EMA10 > d.EMA20).astype(int) * 10
        + (d.EMA20 > d.MA50).astype(int) * 5
        + (d.MA50 > d.MA200).astype(int) * 5
    )
    d["ScoreMACD"] = (
        (d.MACD > 0).astype(int) * 8
        + (d.Hist > 0).astype(int) * 8
        + (d.Hist > d.Hist.shift(1)).astype(int) * 4
    )
    rsi_sc = pd.Series(0, index=d.index)
    rsi_sc += np.where(d.RSI.between(50, 65), 20, 0)
    rsi_sc += np.where(d.RSI.between(40, 50) | d.RSI.between(65, 72), 10, 0)
    d["ScoreRSI"] = rsi_sc

    d["ScoreVol"] = (d.VolRatio > 1.2).astype(int) * 15 + (d.BBWidth < d.BBWidth.rolling(60).quantile(0.3)).astype(int) * 15

    d["Score"] = d["ScoreTrend"] + d["ScoreMACD"] + d["ScoreRSI"] + d["ScoreVol"]
    return d


def analyze_technical_aspects(row, cfg=None):
    cfg = cfg or Config()
    features = {}
    if row["EMA10"] > row["EMA20"] and row["EMA20"] > row["MA50"]:
        features["ma_status"] = "🟢 多头排列 (EMA10 > EMA20 > MA50)"
        features["ma_tag"] = "tag-bull"
    else:
        features["ma_status"] = "🟡 盘整或空头整理"
        features["ma_tag"] = "tag-neutral"

    if row["MACD"] > 0 and row["Hist"] > 0:
        features["macd_status"] = "🟢 水上金叉主升 (MACD & Hist 双正)"
        features["macd_tag"] = "tag-bull"
    else:
        features["macd_status"] = "🔴 动能弱势/水下调整"
        features["macd_tag"] = "tag-bear"

    rsi_val = row["RSI"]
    if 50 <= rsi_val <= 65:
        features["rsi_status"] = f"🟢 黄金动能区 (RSI: {rsi_val:.1f})"
        features["rsi_tag"] = "tag-bull"
    else:
        features["rsi_status"] = f"🟡 偏离强势区 (RSI: {rsi_val:.1f})"
        features["rsi_tag"] = "tag-neutral"

    bias_val = row.get("BiasMA20", 0.0)
    if bias_val > cfg.max_bias_pct:
        features["bias_status"] = f"⚠️ 乖离偏高 ({bias_val:+.1f}% > {cfg.max_bias_pct:.0f}%)"
        features["bias_tag"] = "tag-warn"
    else:
        features["bias_status"] = f"🟢 乖离合理 ({bias_val:+.1f}%)"
        features["bias_tag"] = "tag-bull"

    rel = row.get("Relative63", 0.0)
    features["alpha_status"] = f"📈 Alpha相对强度: {rel:+.1f}%"
    return features




def make_signal(symbol, frame, cfg, benchmark):
    d = indicators(frame, benchmark)
    last_row = d.iloc[-1]
    p = plan(last_row, cfg)
    tech_diag = analyze_technical_aspects(last_row, cfg)

    summary_reasons = []
    if p:
        if p["bias_warning"]:
            summary_reasons.append(f"⚠️ 乖离偏高({p['bias_val']:+.1f}%)")
        if p["reasons"]:
            summary_reasons.extend(p["reasons"])
        elif not summary_reasons:
            summary_reasons.append("满足自适应筛选条件")

    return {
        "symbol": symbol,
        "df": d,
        "plan": p,
        "tech_diag": tech_diag,
        "current_price": float(d.Close.iloc[-1]),
        "quant_score": int(p["score"]) if p else 0,
        "eligible": bool(p["eligible"]) if p else False,
        "summary": {
            "状态": "候选突破" if p and p["eligible"] else "观察中",
            "原因": "；".join(summary_reasons),
        },
    }


# -----------------------------------------------------------------------------
# 6. 修正后的回测模拟引擎 (任务B: 时序偏差修正, 任务C: 真实风险公式, 任务D: 修复0股交易, 任务E: 组合模式)
# [v8.1 Patch 3]: R倍数统计现在基于每笔交易开仓时实际承担的风险金额 (current_risk_amt)，
# 而不是固定用 initial * risk_pct 作分母 —— 后者会随着权益复利增长而逐渐失真。
# -----------------------------------------------------------------------------


# [任务E]: 多标的真实共享资金池组合回测引擎


# Backend adapters retain all original UI function names and result keys.


# === Self-contained mathematical engine (no local module imports) ===
"""Auditable daily-bar long-only research engine. No brokerage integration."""
from pathlib import Path
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent




@dataclass(frozen=True)
class Settings:
    risk_pct: float=0.3
    max_position_pct: float=15.
    slots: int=5
    fee_bps: float=5.
    slip_bps: float=5.
    rr: float=2.5
    partial: float=0.5
    be_r: float=1.
    min_score: int=75
    max_atr_pct: float=10.
    min_dollar_volume: float=10_000_000.
    min_price: float=2.
    execution: str='limit'

@dataclass(frozen=True)
class ExitRules:
    # Zero activation preserves the previously audited trailing behavior exactly.
    trail_activate_r: float=0.
    chandelier_atr: float=3.2
    max_holding_bars: int=0


def wilder_exact(s,n=14):
    a=s.to_numpy(dtype=float); out=np.full(len(a),np.nan)
    for i in range(n-1,len(a)):
        if np.isfinite(a[i-n+1:i+1]).all():
            out[i]=np.mean(a[i-n+1:i+1]); break
    else: return pd.Series(out,index=s.index)
    for j in range(i+1,len(a)):
        if np.isfinite(a[j]): out[j]=(out[j-1]*(n-1)+a[j])/n
    return pd.Series(out,index=s.index)

def features(frame,benchmark):
    d=_base_indicators(frame,benchmark)
    delta=d.Close.diff(); gain=wilder_exact(delta.clip(lower=0)); loss=wilder_exact(-delta.clip(upper=0))
    d['ATR']=wilder_exact(d.TR)
    d['ATRpct']=100*d.ATR/d.Close
    d['RSI']=100-100/(1+gain/loss.replace(0,np.nan))
    d.loc[(loss==0)&(gain>0),'RSI']=100.
    d.loc[(loss==0)&(gain==0),'RSI']=50.
    # Disjoint intervals: RSI=50 and RSI=65 must never score twice.
    d['ScoreRSI']=np.select([d.RSI.between(50,65),(d.RSI.ge(40)&d.RSI.lt(50))|(d.RSI.gt(65)&d.RSI.le(72))],[20,10],default=0)
    d['Score']=d.ScoreTrend+d.ScoreMACD+d.ScoreRSI+d.ScoreVol
    if benchmark is None or benchmark.empty:
        d['MarketOK']=np.nan; d['Relative63']=np.nan
    d['PriorHigh20']=d.High.shift(1).rolling(20).max()
    d['PrevHigh']=d.High.shift(1)
    d['PrevClose']=d.Close.shift(1)
    d['PrevEMA10']=d.EMA10.shift(1)
    d['Slope50']=d.MA50-d.MA50.shift(20)
    d['PullbackTouch']=((d.Low-d.EMA20)/d.ATR).rolling(5).min()
    d['ExtensionATR']=(d.Close-d.EMA20)/d.ATR
    return d

def signals(d,model='baseline',cfg=Settings()):
    valid=np.isfinite(d[['ATR','MA200','RSI','Relative63','MarketOK']]).all(axis=1)
    common=valid & d.MarketOK.eq(1) & d.Close.ge(d.MA200) & d.Close.ge(cfg.min_price) & d.DollarVolume.ge(cfg.min_dollar_volume) & d.ATRpct.le(cfg.max_atr_pct)
    if model=='baseline':
        eligible=common & d.Score.ge(cfg.min_score) & d.VolRatio.gt(.9)
        mode=cfg.execution
    else:
        trend=common & d.MA50.gt(d.MA200) & d.Slope50.gt(0) & d.EMA10.gt(d.EMA20) & d.Relative63.gt(0) & d.RSI.between(45,70) & d.ExtensionATR.between(0,2)
        if model=='pullback': eligible=trend & d.PullbackTouch.le(.5) & d.Close.gt(d.PrevHigh) & d.Close.gt(d.EMA10)
        elif model=='breakout': eligible=trend & d.Close.gt(d.PriorHigh20) & d.VolRatio.gt(1.2)
        elif model=='resume': eligible=trend & d.PrevClose.le(d.PrevEMA10) & d.Close.gt(d.EMA10) & d.Close.gt(d.PrevHigh)
        else: raise ValueError(f'Unknown model {model}')
        mode='market'
    entry=d.Close if mode=='market' else pd.concat([d.Close,d.EMA10],axis=1).min(axis=1)
    stop=entry-2.8*d.ATR
    eligible=eligible & stop.gt(0)
    return pd.DataFrame({'eligible':eligible,'entry':entry,'stop':stop,'score':d.Score,'mode':mode},index=d.index)

def wilson(wins,n):
    if not n: return [None,None]
    z=1.95996398454; p=wins/n; den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [100*(mid-half),100*(mid+half)]

def summarize(eq,trades,initial):
    r=np.array([t['R'] for t in trades]); pnl=np.array([t['pnl'] for t in trades])
    n=len(r); wins=int((pnl>0).sum()); losses=float(-pnl[pnl<0].sum())
    final=float(eq.Equity.iloc[-1]); yrs=max((eq.index[-1]-eq.index[0]).days/365.25,1/365.25)
    returns=eq.Equity.pct_change().dropna()
    return {'trades':n,'win_pct':100*wins/n if n else None,'win_ci95':wilson(wins,n),'expectancy_R':float(r.mean()) if n else None,
        'avg_win_R':float(r[r>0].mean()) if (r>0).any() else None,'avg_loss_R':float(-r[r<0].mean()) if (r<0).any() else None,
        'profit_factor':float(pnl[pnl>0].sum()/losses) if losses else None,'return_pct':100*(final/initial-1),
        'cagr_pct':100*((final/initial)**(1/yrs)-1),'max_dd_pct':100*float((eq.Equity/eq.Equity.cummax()-1).min()),
        'sharpe_zero_cash':float(returns.mean()/returns.std()*np.sqrt(252)) if returns.std()>0 else None,
        'exposure_pct':100*float(eq.Exposure.mean()),'forced_exits':sum(t['reason']=='period_end' for t in trades),
        'natural_trades':sum(t['reason']!='period_end' for t in trades),'final_equity':final}

def backtest(data,start,end,model='baseline',cfg=Settings(),initial=100000.,signal_override=None,exit_rules=ExitRules()):
    """Signals at prior close; reserve orders before intraday outcomes; all trades flattened at fixed endpoint.

    Daily bars cannot identify intraday path. Stop takes precedence if both stop and
    target are touched intraday. Intraday limit entries get no same-day target credit.
    Missing bars preserve last mark and disable new orders on a stale signal.
    """
    if not (0<cfg.risk_pct<=100 and 0<cfg.max_position_pct<=100 and cfg.slots>=1 and 0<=cfg.partial<=1 and cfg.rr>0): raise ValueError('invalid settings')
    fee=cfg.fee_bps/1e4; slip=cfg.slip_bps/1e4
    arrays={}; sigs={}; calendars={}; prev_dates={}
    for s,d in sorted(data.items()):
        if not d.index.is_unique or not d.index.is_monotonic_increasing: raise ValueError('dates must be sorted and unique')
        arrays[s]={dt:row for dt,row in zip(d.index,d.to_dict('records'))}
        sig=signals(d,model,cfg) if signal_override is None else signal_override[s]
        sigs[s]={d.index[i]:r for i,r in enumerate(sig.to_dict('records'))}
        prev_dates[s]={d.index[i]:d.index[i-1] for i in range(1,len(d))}
    all_dates=sorted(set().union(*(set(d.index) for d in data.values())))
    dates=[dt for dt in all_dates if pd.Timestamp(start)<=dt<=pd.Timestamp(end)]
    if not dates: raise ValueError('no bars in requested dates')
    prev_calendar={all_dates[i]:all_dates[i-1] for i in range(1,len(all_dates))}
    cash=float(initial); positions={}; marks={}; completed=[]; events=[]; curve=[]; trade_id=0
    before=[d for d in all_dates if d<dates[0]]
    curve.append({'Date':before[-1] if before else dates[0]-pd.Timedelta(days=1),'Equity':initial,'Exposure':0.,'Cash':initial})

    def sell(s,qty,raw_price,date,reason,market=True):
        nonlocal cash
        p=positions[s]; fill=raw_price*(1-slip) if market else raw_price
        proceeds=qty*fill*(1-fee); cash+=proceeds
        p['pnl']+=proceeds-qty*p['unit_cost']; p['qty']-=qty
        events.append({'id':p['id'],'date':str(date.date()),'symbol':s,'side':'sell','qty':qty,'fill':fill,'reason':reason})
        if p['qty']==0:
            completed.append({'id':p['id'],'symbol':s,'entry_date':p['entry_date'],'exit_date':str(date.date()),'entry_fill':p['fill'],'initial_qty':p['initial_qty'],'initial_risk':p['risk_total'],'pnl':p['pnl'],'R':p['pnl']/p['risk_total'],'reason':reason})
            del positions[s]

    for date in dates:
        prev_eq=cash+sum(p['qty']*marks[s] for s,p in positions.items())
        budget=cash; available=max(0,cfg.slots-len(positions)); orders=[]
        candidates=[]
        for s in arrays:
            if s in positions or date not in arrays[s]: continue
            previous=prev_dates[s].get(date)
            if previous!=prev_calendar.get(date) or previous is None: continue
            sig=sigs[s][previous]
            if sig['eligible']: candidates.append((s,sig))
        candidates.sort(key=lambda x:(-float(x[1]['score']),x[0]))
        # All orders reserve cash and slots before knowing which limits fill.
        for s,sig in candidates:
            if available<=0: break
            row=arrays[s][date]; op=float(row['Open']); limit=float(sig['entry']); stop=float(sig['stop'])
            if op<=stop or stop<=0: continue
            if model!='baseline' and op>limit+float(sig.get('max_gap_atr',1.))*float(arrays[s][prev_dates[s][date]]['ATR']): continue
            is_limit=sig['mode']=='limit'; is_stop=sig['mode']=='stop'
            reserve_fill=limit if is_limit else max(op,limit)*(1+slip) if is_stop else op*(1+slip)
            unit_risk=reserve_fill*(1+fee)-stop*(1-slip)*(1-fee)
            if unit_risk<=0: continue
            qty=math.floor(min(prev_eq*cfg.risk_pct/100/unit_risk,prev_eq*cfg.max_position_pct/100/(reserve_fill*(1+fee)),budget/(reserve_fill*(1+fee))))
            if qty<=0: continue
            budget-=qty*reserve_fill*(1+fee); available-=1
            orders.append((s,sig,qty))

        existing=set(positions)
        for s in sorted(existing):
            if date not in arrays[s]: continue
            row=arrays[s][date]; p=positions[s]; op=row['Open']; stop=p['stop']
            if op<=stop:
                sell(s,p['qty'],op,date,'gap_stop'); continue
            if exit_rules.max_holding_bars and p['age']>=exit_rules.max_holding_bars:
                sell(s,p['qty'],op,date,'time_exit_next_open'); continue
            # A known opening gap above target occurs before the later daily low.
            if not p['tp'] and cfg.partial>0 and op>=p['target']:
                qty=math.floor(p['qty']*cfg.partial)
                if qty: sell(s,qty,op,date,'partial_target_open',market=False); p['tp']=True
            if s not in positions: continue
            if row['Low']<=stop:
                sell(s,p['qty'],stop,date,'stop'); continue
            if not p['tp'] and cfg.partial>0 and row['High']>=p['target']:
                qty=math.floor(p['qty']*cfg.partial)
                if qty: sell(s,qty,p['target'],date,'partial_target',market=False); p['tp']=True

        entry_intraday=set()
        for s,sig,qty in orders:
            row=arrays[s][date]; op=row['Open']; is_limit=sig['mode']=='limit'; is_stop=sig['mode']=='stop'; limit=sig['entry']
            if is_limit and row['Low']>limit: continue
            if is_stop and row['High']<limit: continue
            intraday=(is_limit and op>limit) or (is_stop and op<limit)
            fill=min(min(op,limit)*(1+slip),limit) if is_limit else max(op,limit)*(1+slip) if is_stop else op*(1+slip)
            stop=float(sig['stop']); risk=fill*(1+fee)-stop*(1-slip)*(1-fee)
            if risk<=0: continue
            cost=qty*fill*(1+fee)
            if cost>cash+1e-7: raise AssertionError('cash conservation failed')
            cash-=cost; trade_id+=1
            p={'id':trade_id,'qty':qty,'initial_qty':qty,'fill':fill,'unit_cost':fill*(1+fee),'risk_total':qty*risk,'risk_unit':risk,'stop':stop,
               'target':(fill*(1+fee)+cfg.rr*risk)/(1-fee),'tp':False,'highest':fill,'pnl':0.,'age':0,'entry_date':str(date.date())}
            positions[s]=p
            events.append({'id':trade_id,'date':str(date.date()),'symbol':s,'side':'buy','qty':qty,'fill':fill,'reason':model})
            if intraday: entry_intraday.add(s)
            # Price must cross the lower protective stop after a long limit fill.
            if row['Low']<=stop:
                sell(s,qty,stop,date,'entry_day_stop'); continue
            if not intraday and cfg.partial>0 and row['High']>=p['target']:
                take=math.floor(qty*cfg.partial)
                if take: sell(s,take,p['target'],date,'entry_day_partial',market=False); p['tp']=True

        for s,p in list(positions.items()):
            if date not in arrays[s]: continue
            row=arrays[s][date]
            # The high of an intraday entry bar may precede its entry.
            observed_high=max(p['fill'],row['Close']) if s in entry_intraday else row['High']
            p['highest']=max(p['highest'],observed_high)
            breakeven=p['unit_cost']/((1-slip)*(1-fee))
            be=breakeven if (observed_high>=p['fill']+cfg.be_r*p['risk_unit'] or p['tp']) else p['stop']
            p['age']+=1
            if p['highest']>=p['fill']+exit_rules.trail_activate_r*p['risk_unit']:
                p['stop']=max(p['stop'],be,p['highest']-exit_rules.chandelier_atr*row['ATR'],row['DonchianLow10'])
            else:
                p['stop']=max(p['stop'],be)
        for s in arrays:
            if date in arrays[s]: marks[s]=float(arrays[s][date]['Close'])
        eq=cash+sum(p['qty']*marks[s] for s,p in positions.items())
        curve.append({'Date':date,'Equity':eq,'Exposure':(eq-cash)/eq,'Cash':cash})
        if cash < -1e-7: raise AssertionError('negative cash')

    # Predeclared period-end liquidation; include costs and count separately.
    for s,p in list(positions.items()): sell(s,p['qty'],marks[s],dates[-1],'period_end')
    curve[-1]['Equity']=cash; curve[-1]['Cash']=cash; curve[-1]['Exposure']=0.
    eq=pd.DataFrame(curve).set_index('Date')
    if not math.isclose(initial+sum(t['pnl'] for t in completed),cash,abs_tol=1e-6): raise AssertionError('PnL does not reconcile')
    return summarize(eq,completed,initial),eq,pd.DataFrame(completed),pd.DataFrame(events)


"""Strategy changes, not accounting changes. Fixed hypotheses frozen before results."""
from dataclasses import replace
import numpy as np
import pandas as pd

SPECS={
 'control_market':dict(entry='baseline',mode='market',stop='atr28',rr=2.5,partial=.5,be=1.,activate=0.,holding=0),
 'control_pullback':dict(entry='pullback',mode='market',stop='atr28',rr=2.5,partial=.5,be=1.,activate=0.,holding=0),
 'structure_15':dict(entry='pullback',mode='market',stop='structure',rr=1.5,partial=.5,be=1.5,activate=1.5,holding=20),
 'confirm_15':dict(entry='pullback',mode='stop',stop='structure',rr=1.5,partial=.5,be=1.5,activate=1.5,holding=20),
 'confirm_10':dict(entry='pullback',mode='stop',stop='structure',rr=1.,partial=.5,be=1.,activate=1.,holding=20),
 'resume_15':dict(entry='resume',mode='stop',stop='structure',rr=1.5,partial=.5,be=1.5,activate=1.5,holding=20),
 'atr20_15':dict(entry='pullback',mode='market',stop='atr20',rr=1.5,partial=.5,be=1.5,activate=1.5,holding=20),
 'confirm_full15':dict(entry='pullback',mode='stop',stop='structure',rr=1.5,partial=1.,be=1.5,activate=1.5,holding=20)
}

def prepare(data,name,base=Settings(),ui_overrides=False):
    spec=SPECS[name]
    cfg=replace(base,execution='market')
    if not ui_overrides: cfg=replace(cfg,rr=spec['rr'],partial=spec['partial'],be_r=spec['be'])
    exits=ExitRules(trail_activate_r=spec['activate'],max_holding_bars=spec['holding'])
    prepared={}
    for s,d in data.items():
        sig=signals(d,spec['entry'],cfg)
        sig['entry']=d.High+.1*d.ATR if spec['mode']=='stop' else d.Close
        if spec['stop']=='structure':
            # A structural low invalidates the pullback thesis; ATR avoids stops
            # tighter than normal noise. Skip excessively distant support.
            structural=d.Low.rolling(5).min()-.25*d.ATR
            sig['stop']=np.minimum(structural,sig.entry-1.2*d.ATR)
            sig['eligible']=sig.eligible & ((sig.entry-sig.stop)/d.ATR).le(3.)
        else:
            sig['stop']=sig.entry-(2.0 if spec['stop']=='atr20' else 2.8)*d.ATR
        sig['eligible']=sig.eligible & sig.stop.gt(0)
        sig['mode']=spec['mode']
        sig['max_gap_atr']=.5 if spec['mode']=='stop' else 1.
        prepared[s]=sig
    return cfg,exits,prepared

"""Adapters for the user's original UI: preserve function names and return schemas."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math
import numpy as np
import pandas as pd
import yfinance as yf

def settings(cfg):
    return Settings(risk_pct=cfg.risk_pct,max_position_pct=cfg.max_position_pct,
        slots=cfg.portfolio_max_slots,fee_bps=cfg.fee_bps,slip_bps=cfg.slip_bps,
        rr=cfg.rr,partial=cfg.partial_tp_ratio,be_r=cfg.breakeven_trigger_r,
        min_score=cfg.min_score,max_atr_pct=cfg.max_atr_pct,
        min_dollar_volume=cfg.min_dollar_volume,min_price=cfg.min_price,
        execution='market' if cfg.execution_mode.startswith('追势') else 'limit')

def fetch_history(symbol,period='3y'):
    # Always exclude New York's current date, so a partially formed bar cannot
    # accidentally masquerade as yesterday's fully available signal.
    end=datetime.now(ZoneInfo('America/New_York')).date()
    years=int(period[:-1]) if period.endswith('y') and period[:-1].isdigit() else 5
    start=end-timedelta(days=365*years+400)
    d=yf.Ticker(symbol.strip().upper()).history(start=start.isoformat(),end=end.isoformat(),auto_adjust=True,actions=False)
    if d is None or d.empty: raise ValueError('行情为空')
    d=d[['Open','High','Low','Close','Volume']].copy()
    d.index=pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    if not d.index.is_unique: raise ValueError('行情日期重复')
    d=d.sort_index()
    if not np.isfinite(d.to_numpy()).all(): raise ValueError('行情含缺失或非有限数值')
    if not ((d.High>=d[['Open','Close','Low']].max(axis=1)) & (d.Low<=d[['Open','Close','High']].min(axis=1)) & (d.Low>0) & (d.Volume>=0)).all(): raise ValueError('行情OHLCV关系异常')
    if len(d)<220: raise ValueError('少于220根日线，无法完整预热')
    return d

def indicators(frame,benchmark=None):
    d=features(frame,benchmark)
    d['Support5']=d.Low.rolling(5).min()
    return d

def make_plan(row,cfg):
    needed=['Close','ATR','MA200','EMA10','EMA20','RSI','Score','DollarVolume','ATRpct','BiasMA20','Relative63','MarketOK']
    if any(k not in row for k in needed): return None
    if not np.isfinite(row[['Close','ATR','MA200','EMA10','EMA20','RSI','Score']].to_numpy(dtype=float)).all() or row.ATR<=0: return None
    reasons=[]; c=settings(cfg)
    if not np.isfinite(row.MarketOK): reasons.append('大盘数据不足，无法确认200日趋势')
    elif row.MarketOK!=1: reasons.append('大盘未站上200日线')
    if row.Close<row.MA200: reasons.append('个股低于200日线')
    if row.Close<c.min_price: reasons.append('价格低于门槛')
    if row.DollarVolume<c.min_dollar_volume: reasons.append('成交额不足')
    if row.ATRpct>c.max_atr_pct: reasons.append('ATR波动率过高')
    if not np.isfinite(row.Relative63): reasons.append('相对收益历史不足')
    entry_model=SPECS[ROUND2_STRATEGY]['entry'] if ROUND2_STRATEGY else SIGNAL_MODEL
    if entry_model=='baseline':
        if row.Score<c.min_score: reasons.append('综合评分不足')
        if row.VolRatio<=.9: reasons.append('量比不足0.9')
    else:
        checks=[(row.MA50>row.MA200,'50日线未高于200日线'),(row.Slope50>0,'50日线斜率不为正'),(row.EMA10>row.EMA20,'短期均线未多头排列'),(row.Relative63>0,'63日相对SPY收益不为正'),(45<=row.RSI<=70,'RSI不在45–70'),(0<=row.ExtensionATR<=2,'距EMA20不在0–2ATR')]
        if entry_model=='pullback': checks.extend([(row.PullbackTouch<=.5,'近5日缺少回调触及'),(row.Close>row.PrevHigh,'未突破前日最高'),(row.Close>row.EMA10,'未站上EMA10')])
        if entry_model=='breakout': checks.extend([(row.Close>row.PriorHigh20,'未突破前20日最高'),(row.VolRatio>1.2,'量比不足1.2')])
        if entry_model=='resume': checks.extend([(row.PrevClose<=row.PrevEMA10,'前收盘未低于短均线'),(row.Close>row.EMA10,'未站回短均线'),(row.Close>row.PrevHigh,'未突破前日最高')])
        reasons.extend(reason for ok,reason in checks if not ok)
    one=row.to_frame().T
    sig=signals(one,entry_model,c).iloc[0]
    entry=float(sig.entry); stop=float(sig.stop)
    if ROUND2_STRATEGY:
        spec=SPECS[ROUND2_STRATEGY]
        entry=float(row.High+.1*row.ATR) if spec['mode']=='stop' else float(row.Close)
        if spec['stop']=='structure':
            stop=min(float(row.Support5-.25*row.ATR),entry-1.2*row.ATR)
            if not np.isfinite(stop) or (entry-stop)/row.ATR>3:
                sig.eligible=False; reasons.append('结构支撑过远或缺失：风险距离须不超过3ATR')
        else: stop=entry-(2.0 if spec['stop']=='atr20' else 2.8)*row.ATR
        sig['mode']=spec['mode']
    if stop<=0: reasons.append('初始止损价格非正')
    fee=c.fee_bps/1e4; slip=c.slip_bps/1e4
    risk=entry-stop
    net_risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
    target=(entry*(1+fee)+c.rr*net_risk)/(1-fee)
    if not bool(sig.eligible) and not reasons: reasons.append('未满足完整指标有效性或入场条件')
    return {'entry':entry,'stop':stop,'target':target,'risk':risk,'eligible':bool(sig.eligible),
        'reasons':reasons,'score':int(row.Score),'score_breakdown':{'趋势分':int(row.ScoreTrend),'MACD分':int(row.ScoreMACD),'RSI分':int(row.ScoreRSI),'量能分':int(row.ScoreVol),'总分':int(row.Score)},
        'buy_mode':'次日突破触发价（未突破不入场）' if sig['mode']=='stop' else '次日开盘参考（成交前需重算风险）' if sig['mode']=='market' else '次日限价参考',
        'atr_pct':float(row.ATRpct),'relative63':float(row.Relative63),'bias_warning':bool(row.BiasMA20>cfg.max_bias_pct),'bias_val':float(row.BiasMA20)}

def translate(m):
    return {'期望值 (R)':m['expectancy_R'] or 0.,'胜率%':m['win_pct'] or 0.,
        '平均盈利 (R)':m['avg_win_R'] or 0.,'平均亏损 (R)':m['avg_loss_R'] or 0.,
        '最终资产':m['final_equity'],'收益率%':m['return_pct'],'最大回撤%':m['max_dd_pct'],
        '已平仓笔数':m['trades'],'期末结算笔数':m['forced_exits'],'利润因子':m['profit_factor'],
        '胜率95%区间':m['win_ci95'],'平均资金投入%':m['exposure_pct']}

def ledger_for_ui(trades):
    return trades.rename(columns={'id':'交易ID','symbol':'代码','entry_date':'开仓日期','exit_date':'平仓日期','entry_fill':'买入成交价','initial_qty':'开仓股数','initial_risk':'初始风险金额','pnl':'完整交易净盈亏','R':'完整交易R','reason':'最终退出原因'})

def install(namespace):
    Config=namespace['Config']
    original_cfg_from_session=namespace['cfg_from_session']
    def cfg_from_session():
        cfg=original_cfg_from_session()
        if ROUND2_STRATEGY: cfg.execution_mode='确认突破条件入场（研究）' if SPECS[ROUND2_STRATEGY]['mode']=='stop' else '追势模式 (Market)'
        return cfg
    def run_engine(data,start,end,cfg,initial):
        if ROUND2_STRATEGY:
            c,exits,sig=prepare(data,ROUND2_STRATEGY,settings(cfg),ui_overrides=True)
            return backtest(data,start,end,ROUND2_STRATEGY,c,initial,signal_override=sig,exit_rules=exits)
        return backtest(data,start,end,SIGNAL_MODEL,settings(cfg),initial)
    def plan(row,cfg=None): return make_plan(row,cfg or Config())
    def simulate(d,cfg=None,initial=10000.,start=None):
        cfg=cfg or Config()
        if len(d)<221: raise ValueError('预热数据不足')
        actual_start=start or str(d.index[220].date())
        if (d.index<pd.Timestamp(actual_start)).sum()<220: raise ValueError('回测起始日前预热不足220根，请使用更长行情')
        m,e,t,ev=run_engine({'标的':d},actual_start,str(d.index[-1].date()),cfg,initial)
        ix=e.index[1:]; fee=cfg.fee_bps/1e4; slip=cfg.slip_bps/1e4
        buy=float(d.loc[ix[0],'Open'])*(1+slip)*(1+fee)
        e['Benchmark']=initial
        e.loc[ix,'Benchmark']=initial*d.loc[ix,'Close']/buy
        e.loc[ix[-1],'Benchmark']*=(1-slip)*(1-fee)
        metrics=translate(m); metrics['买入持有%']=100*(e.Benchmark.iloc[-1]/initial-1)
        return metrics,e,ledger_for_ui(t)
    def simulate_portfolio(data_dict,cfg=None,initial=100000.,start=None):
        cfg=cfg or Config()
        if not data_dict: raise ValueError('股票池没有可用数据')
        actual_start=start or str(max(d.index[220] for d in data_dict.values()).date())
        for sym,d in data_dict.items():
            if (d.index<pd.Timestamp(actual_start)).sum()<220: raise ValueError(f'{sym} 回测起始日前预热不足220根')
        end=min(d.index[-1] for d in data_dict.values())
        m,e,t,ev=run_engine(data_dict,actual_start,str(end.date()),cfg,initial)
        return translate(m),e,ledger_for_ui(t)
    namespace.update({'fetch_history':fetch_history,'indicators':indicators,'plan':plan,'simulate':simulate,'simulate_portfolio':simulate_portfolio,'cfg_from_session':cfg_from_session})

install(globals())


# -----------------------------------------------------------------------------
# 7. UI 渲染与图形展示
# -----------------------------------------------------------------------------
def render_segmented_chart(sig_data, days=120):
    d = sig_data["df"].tail(days)
    p = sig_data["plan"]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.55, 0.22, 0.23])

    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name="日K",
                                 increasing_line_color='#00ff66', decreasing_line_color='#ff3366'), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.EMA10, name="EMA10", line=dict(color="#00f0ff", width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.EMA20, name="EMA20", line=dict(color="#ffaa00", width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MA50, name="MA50", line=dict(color="#b87cff", width=1.5)), row=1, col=1)

    if p:
        fig.add_hline(y=p["entry"], line_dash="dash", line_color="#ccff00", annotation_text=f"建议买入 ({p['buy_mode']})", row=1, col=1)
        fig.add_hline(y=p["stop"], line_dash="dash", line_color="#ff3366", annotation_text="止损位", row=1, col=1)
        fig.add_hline(y=p["target"], line_dash="dash", line_color="#00ff66", annotation_text=f"分批止盈 (TP: {p['target']:.2f})", row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(color="#00f0ff", width=1.5)), row=2, col=1)
    fig.add_hline(y=65, line_dash="dot", line_color="#ff3366", row=2, col=1)
    fig.add_hline(y=40, line_dash="dot", line_color="#00ff66", row=2, col=1)

    colors = np.where(d.Hist >= 0, '#00ff66', '#ff3366')
    fig.add_trace(go.Bar(x=d.index, y=d.Hist, name="MACD Hist", marker_color=colors), row=3, col=1)

    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#121821", height=600, margin=dict(l=15, r=15, t=10, b=15), showlegend=False)
    return fig


def metric_card(title, value, css_class=""):
    return f"<div class='tech-card'><div class='metric-title'>{html.escape(title)}</div><div class='metric-value {css_class}'>{html.escape(str(value))}</div></div>"


# -----------------------------------------------------------------------------
# 8. STREAMLIT 主交互界面 (侧边栏任务A收纳 & 高级设置折叠)
# -----------------------------------------------------------------------------
st.markdown('<h3 class="tech-header">⚡ QUANTUM TERMINAL ULTRA 8.1</h3>', unsafe_allow_html=True)
st.markdown('<div class="tech-subtitle">Conservative-FOMO Preset System & Portfolio Backtest Engine</div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🎛️ 终端控制台")
    selected_nav = st.radio("导航菜单", NAV_OPTIONS, index=NAV_OPTIONS.index(st.session_state.current_page))
    if selected_nav != st.session_state.current_page:
        st.session_state.current_page = selected_nav
        st.rerun()

    st.markdown("---")
    st.markdown("#### 🛡️ 风险偏好预设 (小白推荐)")
    # [任务A]: 三档风控预设单选框
    chosen_profile = st.radio("风险偏好", ["保守", "稳健", "进取"], index=["保守", "稳健", "进取"].index(st.session_state.risk_profile))

    # [v8.1 Patch 2]: 移除 "not user_customized" 限制 —— 之前只要手动调过一次高级参数，
    # user_customized 就被锁定为 True 且从未被重置，导致之后再切换档位单选框完全不生效。
    # 现在只要用户主动切换了不同档位，就视为明确的"重新开始"意图，强制重新应用新预设。
    if chosen_profile != st.session_state.risk_profile:
        st.session_state.risk_profile = chosen_profile
        st.session_state.user_customized = False
        p_cfg = PRESET_CONFIGS[chosen_profile]
        st.session_state.risk_pct = p_cfg["risk_pct"]
        st.session_state.min_score = p_cfg["min_score"]
        st.session_state.max_atr_pct = p_cfg["max_atr_pct"]
        st.session_state.partial_tp_ratio = p_cfg["partial_tp_ratio"]
        st.session_state.rr_ratio = p_cfg["rr_ratio"]
        st.session_state.max_pos_pct = p_cfg["max_pos_pct"]
        st.session_state.breakeven_trigger_r = p_cfg["breakeven_trigger_r"]
        st.session_state.execution_mode = p_cfg["execution_mode"]
        st.rerun()

    if st.session_state.user_customized:
        st.info("💡 已从预设值手动调整参数")
        # [v8.1 Patch 2]: 新增显式重置按钮，方便用户一键清除手动调整、回到当前档位的标准预设值
        if st.button("🔄 重置为当前预设", use_container_width=True):
            st.session_state.user_customized = False
            p_cfg = PRESET_CONFIGS[st.session_state.risk_profile]
            st.session_state.risk_pct = p_cfg["risk_pct"]
            st.session_state.min_score = p_cfg["min_score"]
            st.session_state.max_atr_pct = p_cfg["max_atr_pct"]
            st.session_state.partial_tp_ratio = p_cfg["partial_tp_ratio"]
            st.session_state.rr_ratio = p_cfg["rr_ratio"]
            st.session_state.max_pos_pct = p_cfg["max_pos_pct"]
            st.session_state.breakeven_trigger_r = p_cfg["breakeven_trigger_r"]
            st.session_state.execution_mode = p_cfg["execution_mode"]
            st.rerun()

    # [任务A]: 隐藏进高级设置，默认折叠
    with st.expander("⚙️ 高级设置（了解风险后再调）", expanded=False):
        st.markdown("##### 🎛️ 详细参数微调")
        new_exec = st.radio("入场模式", ["稳健模式 (Limit)", "追势模式 (Market)"], index=0 if st.session_state.execution_mode.startswith("稳健") else 1)
        new_rr = st.slider("目标盈亏比 (R/R)", 1.0, 5.0, float(st.session_state.rr_ratio), 0.5)
        new_risk = st.slider("单笔风控 %", 0.1, 5.0, float(st.session_state.risk_pct), 0.1)
        new_max_pos = st.slider("最大持仓上限 %", 5.0, 100.0, float(st.session_state.max_pos_pct), 5.0)
        new_tp = st.slider("分批止盈比例", 0.0, 1.0, float(st.session_state.partial_tp_ratio), 0.1)
        new_be = st.slider("保本触发 (R距离)", 0.5, 3.0, float(st.session_state.breakeven_trigger_r), 0.5)
        new_min_sc = st.slider("最低筛选评分门槛", 40, 95, int(st.session_state.min_score), 5)
        new_max_atr = st.slider("最高 ATR 波动率 %", 5.0, 30.0, float(st.session_state.max_atr_pct), 1.0)
        new_min_vol = st.slider("最低日均成交额 (M$)", 1.0, 50.0, float(st.session_state.min_dollar_vol), 1.0)
        new_max_bias = st.slider("MA20 追高预警阈值 %", 5.0, 30.0, float(st.session_state.max_bias_pct), 1.0)
        new_slots = st.slider("组合模式最大同时持仓数", 1, 10, int(st.session_state.portfolio_max_slots), 1)

        # 检查是否发生手动改变
        if (new_exec != st.session_state.execution_mode or new_rr != st.session_state.rr_ratio or
            new_risk != st.session_state.risk_pct or new_max_pos != st.session_state.max_pos_pct or
            new_tp != st.session_state.partial_tp_ratio or new_be != st.session_state.breakeven_trigger_r or
            new_min_sc != st.session_state.min_score or new_max_atr != st.session_state.max_atr_pct or
            new_min_vol != st.session_state.min_dollar_vol or new_max_bias != st.session_state.max_bias_pct or
            new_slots != st.session_state.portfolio_max_slots):
            st.session_state.execution_mode = new_exec
            st.session_state.rr_ratio = new_rr
            st.session_state.risk_pct = new_risk
            st.session_state.max_pos_pct = new_max_pos
            st.session_state.partial_tp_ratio = new_tp
            st.session_state.breakeven_trigger_r = new_be
            st.session_state.min_score = new_min_sc
            st.session_state.max_atr_pct = new_max_atr
            st.session_state.min_dollar_vol = new_min_vol
            st.session_state.max_bias_pct = new_max_bias
            st.session_state.portfolio_max_slots = new_slots
            st.session_state.user_customized = True

cfg = cfg_from_session()
app_mode = st.session_state.current_page

# =============================================================================
# TAB 1: 自动扫描 & 智能推荐
# =============================================================================
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 市场全池自动扫描")
    st.info(f"当前档位：**{st.session_state.risk_profile}** | 执行模式：**{cfg.execution_mode}** | 分批止盈: **{cfg.partial_tp_ratio*100:.0f}%** | 风险上限: **{cfg.risk_pct}%**")

    c1, c2, c3 = st.columns([2.5, 3.5, 1.5])
    with c1:
        selected_preset = st.selectbox("预设/动态股票池", list(INDEX_PRESET_POOLS.keys()))
    with c2:
        pool_target = INDEX_PRESET_POOLS[selected_preset]
        if isinstance(pool_target, str) and pool_target.startswith("DYNAMIC_"):
            symbols_list, pool_msg = fetch_dynamic_pool(pool_target)
            st.caption(pool_msg)
            custom_pool_str = st.text_input("扫描代码 (动态已载入前500)", value=", ".join(symbols_list[:500]))
        else:
            custom_pool_str = st.text_input("扫描代码", value=", ".join(pool_target))
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动模型扫描", use_container_width=True)

    if run_scan:
        symbols = parse_symbols(custom_pool_str)[:500]
        st.caption("ℹ️ 按名单顺序抽取前500支进行扫描，不代表排名最优。")

        try:
            benchmark = fetch_history("SPY", "3y")
        except Exception as e:
            st.error(f"基准 SPY 拉取失败: {e}")
            benchmark = None

        results = []
        errors = []

        # [任务K]: 清晰进度条反馈
        progress_bar = st.progress(0)
        status_text = st.empty()

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {executor.submit(fetch_history, s, "3y"): s for s in symbols}
            done = 0
            total = len(symbols)
            for future in as_completed(future_map):
                s = future_map[future]
                done += 1
                try:
                    frame = future.result()
                    if benchmark is not None:
                        results.append(make_signal(s, frame, cfg, benchmark))
                except Exception as err:
                    errors.append((s, str(err)))

                progress_bar.progress(done / total)
                status_text.text(f"已处理 {done}/{total} 支标的...")

        progress_bar.empty()
        status_text.empty()

        results.sort(key=lambda x: (x["eligible"], x["quant_score"]), reverse=True)
        st.session_state.scan_results = results
        st.session_state.scan_errors = errors

    if st.session_state.scan_errors:
        err_msg = ", ".join([f"**{s}** ({err})" for s, err in st.session_state.scan_errors[:10]])
        st.warning(f"⚠️ 共 {len(st.session_state.scan_errors)} 个标的处理失败 (展示前10个): {err_msg}")

    res = st.session_state.get("scan_results", [])
    if res:
        df_display = pd.DataFrame([{
            "代码": r["symbol"],
            "优化评分": r["quant_score"],
            "状态": r["summary"]["状态"],
            "现价": f"${r['current_price']:.2f}",
            "建议买入价": f"${r['plan']['entry']:.2f}" if r["plan"] else "N/A",
            "优化止损位": f"${r['plan']['stop']:.2f}" if r["plan"] else "N/A",
            "分批止盈价": f"${r['plan']['target']:.2f}" if r["plan"] else "N/A",
            "MA20乖离率": f"{r['plan']['bias_val']:+.1f}%" if r["plan"] else "N/A",
            "相对Alpha": f"{r['plan']['relative63']:+.2f}%" if r["plan"] else "N/A",
            "诊断与拦截说明": r["summary"]["原因"],
        } for r in res])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 2: 单标的全量诊断 (任务F: 醒目红绿灯 + 评分拆解 + 免责声明)
# =============================================================================
elif app_mode == "🔍 单标的全量诊断":
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        ticker_input = st.text_input("输入股票代码", value=st.session_state.selected_ticker).upper().strip()
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("⚡ 诊断", use_container_width=True):
            st.session_state.selected_ticker = parse_symbols(ticker_input)[0]
            st.rerun()
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("⭐ 加入自选", use_container_width=True):
            add_to_watchlist(st.session_state.selected_ticker)
            st.toast(f"已将 {st.session_state.selected_ticker} 添加到自选清单！")

    sym = st.session_state.selected_ticker
    try:
        frame = fetch_history(sym, "3y")
        benchmark = fetch_history("SPY", "3y")
        sig = make_signal(sym, frame, cfg, benchmark)
        p = sig["plan"]

        # [任务F.1]: 醒目结论红绿灯横幅
        if p and p["eligible"]:
            st.markdown('<div class="status-banner-pass">🟢 当前满足系统买入条件 (系统评估通过)</div>', unsafe_allow_html=True)
        else:
            reasons_text = "；".join(p["reasons"]) if p and p["reasons"] else "数据异常或不符合基础入场条件"
            st.markdown(f'<div class="status-banner-fail">🔴 当前不满足买入条件<br/><span style="font-size:12px;font-weight:normal;">原因：{html.escape(reasons_text)}</span></div>', unsafe_allow_html=True)

        # [任务F.2]: 可折叠的评分分拆区块
        if p and "score_breakdown" in p:
            with st.expander("📊 这个评分是怎么算出来的？(点击展开分拆)", expanded=False):
                sb = p["score_breakdown"]
                df_sb = pd.DataFrame([
                    {"评分维度": "趋势维度 (EMA/MA多头排列)", "得分": f"{sb['趋势分']} / 30"},
                    {"评分维度": "动能维度 (MACD水上/柱状图加数)", "得分": f"{sb['MACD分']} / 20"},
                    {"评分维度": "相对强弱 (RSI 黄金动能区间)", "得分": f"{sb['RSI分']} / 20"},
                    {"评分维度": "量能爆发 (突破放量/布林收敛)", "得分": f"{sb['量能分']} / 30"},
                    {"评分维度": "⚡ 综合总评分", "得分": f"{sb['总分']} / 100"},
                ])
                st.dataframe(df_sb, use_container_width=True, hide_index=True)

        # [任务F.3]: 醒目免责声明
        st.caption("⚠️ **免责声明**：评分是固定规则分数，不是获利概率。新入场候选尚未证明稳定优于基线；回测按完整交易统计并包含期末结算。")

        diag = sig["tech_diag"]
        st.markdown(
            f"""
            <div class='diag-box'>
                <span class='diag-tag {diag["ma_tag"]}'>{diag["ma_status"]}</span>
                <span class='diag-tag {diag["macd_tag"]}'>{diag["macd_status"]}</span>
                <span class='diag-tag {diag["rsi_tag"]}'>{diag["rsi_status"]}</span>
                <span class='diag-tag {diag["bias_tag"]}'>{diag["bias_status"]}</span>
                <span class='diag-tag tag-neutral'>{diag["alpha_status"]}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.plotly_chart(render_segmented_chart(sig), use_container_width=True)
    except Exception as err:
        st.error(f"⚠️ 无法为 {sym} 生成诊断视图: {err}")

# =============================================================================
# TAB 3: 策略历史回测引擎 (任务I: 胜率与Expectancy最先展示 & 任务E: 组合模式)
# =============================================================================
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 优化策略历史回测 (Dynamic Partial TP & Portfolio Backtest)")
    st.info(f"⚙️ 当前偏好：**{st.session_state.risk_profile}** | 执行参数：**{cfg.execution_mode}** | 分批止盈率: **{cfg.partial_tp_ratio*100:.0f}%** | 风险/笔: **{cfg.risk_pct}%**")

    # [任务E]: 新增开关
    st.session_state.portfolio_mode = st.radio("全池回测模式", ["组合模式 (共享资金)", "独立模式 (各自独立初始资金)"], horizontal=True)

    st.markdown("#### 📅 选择回测起始日期")
    quick_range = st.radio("快捷时间范围", ["最近1年", "最近3年", "最近5年", "自定义"], index=1, horizontal=True)

    today = datetime.now().date()
    if quick_range == "最近1年":
        default_start = today - timedelta(days=365)
    elif quick_range == "最近3年":
        default_start = today - timedelta(days=365 * 3)
    elif quick_range == "最近5年":
        default_start = today - timedelta(days=365 * 5)
    else:
        default_start = datetime(2023, 1, 1).date()

    selected_start_date = st.date_input("回测起始日期", value=default_start)

    bt_type = st.radio("测试类型", ["🎯 单标的深度回测", "🌐 股票池全池回测"], horizontal=True)

    if bt_type == "🎯 单标的深度回测":
        bt_sym = st.text_input("回测代码", value="AAPL").upper()
        if st.button("🚀 运行单标的回测"):
            try:
                frame = fetch_history(bt_sym, "5y")
                benchmark = fetch_history("SPY", "5y")
                d = indicators(frame, benchmark)
                metrics, eq, ledger = simulate(d, cfg, initial=st.session_state.capital, start=str(selected_start_date))

                # [任务I]: 期望值 Expectancy 与胜率放在最显眼的最前列
                html_bt_cards = (
                    metric_card("期望值 (Expectancy)", f"{metrics['期望值 (R)']:+.2f} R", "metric-buy" if metrics['期望值 (R)'] > 0 else "metric-stop")
                    + metric_card("胜率%", f"{metrics['胜率%']:.1f}% ({metrics['已平仓笔数']}笔)", "metric-good" if metrics['胜率%'] >= 50 else "metric-stop")
                    + metric_card("盈亏比 (均赢/均亏)", f"{metrics['平均盈利 (R)']:.1f}R / {metrics['平均亏损 (R)']:.1f}R")
                    + metric_card("策略最终收益率", f"{metrics['收益率%']:+.2f}%", "metric-good" if metrics['收益率%'] >= 0 else "metric-stop")
                    + metric_card("最大回撤%", f"{metrics['最大回撤%']:.2f}%", "metric-stop")
                )
                st.markdown(f"<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:10px'>{html_bt_cards}</div>", unsafe_allow_html=True)
                st.caption("💡 *按完整交易统计，分批卖出不重复计笔；包含期末结算与交易成本。历史结果不代表未来。*")

                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Equity, name=f"Quantum 策略 ({cfg.execution_mode})", line=dict(color="#00f0ff", width=2)))
                fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Benchmark, name="买入持有", line=dict(color="#6e7681", width=1.5, dash="dot")))
                fig_eq.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#161b22", height=380)
                st.plotly_chart(fig_eq, use_container_width=True)

                st.markdown("#### 🧾 详细交易明细")
                st.dataframe(ledger, use_container_width=True, hide_index=True)
            except Exception as err:
                st.error(f"❌ 回测运行失败: {err}")

    else:
        bt_preset = st.selectbox("选择回测股票池", list(INDEX_PRESET_POOLS.keys()))
        if st.button("⚡ 运行全池回测"):
            pool_target = INDEX_PRESET_POOLS[bt_preset]
            if isinstance(pool_target, str) and pool_target.startswith("DYNAMIC_"):
                symbols, _ = fetch_dynamic_pool(pool_target)
            else:
                symbols = parse_symbols(", ".join(pool_target))

            symbols = symbols[:500]
            st.caption("ℹ️ 回测抽取前500支标的。")

            try:
                benchmark = fetch_history("SPY", "5y")
            except Exception as err:
                st.error(f"基准数据获取失败: {err}")
                benchmark = None

            progress_bar = st.progress(0)
            status_text = st.empty()

            data_map = {}
            pool_errors = []

            with ThreadPoolExecutor(max_workers=8) as executor:
                future_map = {executor.submit(fetch_history, s, "5y"): s for s in symbols}
                done = 0
                total = len(symbols)
                for future in as_completed(future_map):
                    s = future_map[future]
                    done += 1
                    try:
                        frame = future.result()
                        if benchmark is not None:
                            d = indicators(frame, benchmark)
                            data_map[s] = d
                    except Exception as err:
                        pool_errors.append((s, str(err)))

                    progress_bar.progress(done / total)
                    status_text.text(f"已获取数据 {done}/{total}...")

            progress_bar.empty()
            status_text.empty()

            if pool_errors:
                err_msg = ", ".join([f"**{s}** ({err})" for s, err in pool_errors[:10]])
                st.warning(f"⚠️ 共 {len(pool_errors)} 个标的数据拉取失败 (展示前10个): {err_msg}")

            if st.session_state.portfolio_mode.startswith("组合模式"):
                # [任务E]: 共享资金池组合真实回测
                try:
                    p_metrics, p_eq, p_ledger = simulate_portfolio(data_map, cfg, initial=100000.0, start=str(selected_start_date))

                    html_p_cards = (
                        metric_card("组合期望值 (R)", f"{p_metrics['期望值 (R)']:+.2f} R", "metric-buy" if p_metrics['期望值 (R)'] > 0 else "metric-stop")
                        + metric_card("组合胜率%", f"{p_metrics['胜率%']:.1f}% ({p_metrics['已平仓笔数']}笔)", "metric-good" if p_metrics['胜率%'] >= 50 else "metric-stop")
                        + metric_card("组合总收益率%", f"{p_metrics['收益率%']:+.2f}%", "metric-good" if p_metrics['收益率%'] >= 0 else "metric-stop")
                        + metric_card("组合最大回撤%", f"{p_metrics['最大回撤%']:.2f}%", "metric-stop")
                    )
                    st.markdown(f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{html_p_cards}</div>", unsafe_allow_html=True)
                    st.caption("💡 *组合回测：10万共享资金；按完整交易统计，含期末结算与费用。按前收盘权益预留资金和槽位。*")

                    fig_peq = go.Figure()
                    fig_peq.add_trace(go.Scatter(x=p_eq.index, y=p_eq.Equity, name="全池组合净值", line=dict(color="#00f0ff", width=2)))
                    fig_peq.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#161b22", height=380)
                    st.plotly_chart(fig_peq, use_container_width=True)

                    st.markdown("#### 🧾 组合交易明细")
                    st.dataframe(p_ledger, use_container_width=True, hide_index=True)
                except Exception as err:
                    st.error(f"❌ 组合回测计算失败: {err}")
            else:
                # 独立模式
                pool_results = []
                for s, d in data_map.items():
                    try:
                        metrics, _, _ = simulate(d, cfg, initial=10000.0, start=str(selected_start_date))
                        metrics["代码"] = s
                        pool_results.append(metrics)
                    except Exception:
                        pass

                if pool_results:
                    df_pool = pd.DataFrame(pool_results)
                    st.dataframe(df_pool[["代码", "期望值 (R)", "胜率%", "平均盈利 (R)", "平均亏损 (R)", "收益率%", "最大回撤%", "已平仓笔数"]].sort_values(by="期望值 (R)", ascending=False), use_container_width=True, hide_index=True)

# =============================================================================
# TAB 4: 自选清单监控
# =============================================================================
else:
    st.markdown("### 📊 自选清单实时监控")

    c1, c2 = st.columns([4, 1])
    with c1:
        new_symbol = st.text_input("添加标的至自选", placeholder="输入代码如 TSLA, NVDA").upper().strip()
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("➕ 添加代码", use_container_width=True):
            if new_symbol:
                add_to_watchlist(new_symbol)
                st.success(f"已成功添加 {new_symbol}")
                st.rerun()

    watch_df = get_watchlist()
    if watch_df.empty:
        st.info("💡 你的自选清单为空。可在上方输入代码添加，或在扫描/诊断页面点击【⭐ 加入自选】。")
    else:
        try:
            benchmark = fetch_history("SPY", "3y")
        except Exception:
            benchmark = None

        watch_results = []
        watch_errors = []

        progress_bar = st.progress(0)
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_map = {executor.submit(fetch_history, sym, "3y"): sym for sym in watch_df["symbol"]}
            done = 0
            total = len(watch_df)
            for future in as_completed(future_map):
                sym = future_map[future]
                done += 1
                try:
                    frame = future.result()
                    if benchmark is not None:
                        watch_results.append(make_signal(sym, frame, cfg, benchmark))
                except Exception as err:
                    watch_errors.append((sym, str(err)))
                progress_bar.progress(done / total)

        progress_bar.empty()

        if watch_errors:
            err_msg = ", ".join([f"**{s}** ({err})" for s, err in watch_errors])
            st.warning(f"⚠️ 自选池中以下 {len(watch_errors)} 个标的更新失败: {err_msg}")

        if watch_results:
            for r in watch_results:
                cols = st.columns([1, 2, 2, 2, 2, 1.5])
                with cols[0]:
                    st.markdown(f"### **{r['symbol']}**")
                with cols[1]:
                    st.markdown(f"现价: **${r['current_price']:.2f}**")
                with cols[2]:
                    st.markdown(f"评分: **{r['quant_score']}分**")
                with cols[3]:
                    st.markdown(f"建议买入: **${r['plan']['entry']:.2f}**" if r["plan"] else "N/A")
                with cols[4]:
                    st.markdown(f"状态: **{r['summary']['状态']}**")
                with cols[5]:
                    if st.button("🗑️ 移除", key=f"del_{r['symbol']}"):
                        remove_from_watchlist(r['symbol'])
                        st.toast(f"已从自选移除 {r['symbol']}")
                        st.rerun()
                st.markdown("---")
