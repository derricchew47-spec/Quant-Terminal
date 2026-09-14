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

VERSION = "ULTRA_8.1_PATCHED"

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
def fetch_history(symbol: str, period: str = "3y"):
    symbol = symbol.upper().strip()
    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(period=period, interval="1d", auto_adjust=True, actions=False)
    except Exception as err:
        raise RuntimeError(f"网络/API 获取失败 ({str(err)})") from err

    if frame is None or frame.empty:
        raise ValueError("拉取到的行情数据为空，可能已退市或代码不正确")

    frame = frame.rename(columns={c: str(c).title() for c in frame.columns})
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in frame.columns for c in required):
        raise ValueError(f"缺少关键 OHLCV 列，现有列: {list(frame.columns)}")

    frame = frame[required].copy()

    # [任务H]: 基本合理性数据校验
    valid_mask = (
        (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1))
        & (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1))
        & (frame["Close"] > 0)
        & (frame["Open"] > 0)
        & (frame["High"] > 0)
        & (frame["Low"] > 0)
        & (frame["Volume"] >= 0)
    )
    frame = frame.loc[valid_mask].copy()

    idx = pd.DatetimeIndex(frame.index)
    try:
        idx = idx.tz_localize(None)
    except Exception:
        pass
    frame.index = idx.normalize()
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()

    if len(frame) < 35:
        raise ValueError(f"历史 K 线数据量不足 ({len(frame)}/35 根)，无法计算完整指标")

    return frame


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


def indicators(frame, benchmark=None):
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


def plan(row, cfg=None):
    cfg = cfg or Config()
    required = ["Close", "ATR", "MA50", "MA200", "Support", "EMA10", "EMA20", "RSI", "Score", "DonchianHigh20", "DollarVolume", "ATRpct", "BiasMA20"]
    if any(k not in row or not np.isfinite(row[k]) for k in required) or row.ATR <= 0:
        return None

    reasons = []

    # [任务G]: 显式处理大盘数据不足
    # [v8.1 Patch 1]: np.where() 返回的是 numpy 浮点数（1.0/0.0/nan），不是 Python 原生 bool，
    # 用 `is False` 做身份比较永远不成立（0.0 is False 恒为 False），导致这条拦截从未真正生效。
    # 改用数值比较 `market_ok == 0`，确保大盘破位时真的会被拦截。
    market_ok = row.get("MarketOK", True)
    if pd.isna(market_ok):
        reasons.append("⚠️ 大盘历史数据不足200天，无法确认大盘趋势")
    elif market_ok == 0 or row.Close < row.MA200:
        reasons.append("🚫 熊市拦截：大盘或标的破位200日线")

    if row.DollarVolume < cfg.min_dollar_volume:
        reasons.append(f"💧 成交额不足 (${row.DollarVolume/1e6:.1f}M < ${cfg.min_dollar_volume/1e6:.1f}M)")
    if row.ATRpct > cfg.max_atr_pct:
        reasons.append(f"🌊 波动率过高 (ATR% {row.ATRpct:.1f}% > {cfg.max_atr_pct:.1f}%)")

    if cfg.execution_mode.startswith("追势"):
        entry = float(row.Close)
        buy_mode_desc = "🚀 突破追势 (市价跟进)"
    else:
        entry = min(float(row.Close), float(row.EMA10))
        buy_mode_desc = "🎯 稳健挂单 (限价跟进)"

    stop = entry - 2.8 * row.ATR
    risk = entry - stop
    target = entry + cfg.rr * risk

    if row.Close < cfg.min_price:
        reasons.append("价格低于门槛")
    if row.Score < cfg.min_score:
        reasons.append("综合评分不足")

    bias_warning = row.BiasMA20 > cfg.max_bias_pct

    # 计算分拆细节
    score_breakdown = {
        "趋势分": int(row.get("ScoreTrend", 0)),
        "MACD分": int(row.get("ScoreMACD", 0)),
        "RSI分": int(row.get("ScoreRSI", 0)),
        "量能分": int(row.get("ScoreVol", 0)),
        "总分": int(row.Score),
    }

    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "score": int(row.Score),
        "score_breakdown": score_breakdown,
        "buy_mode": buy_mode_desc,
        "atr_pct": float(row.ATRpct),
        "relative63": float(row.get("Relative63", 0.0)),
        "bias_warning": bias_warning,
        "bias_val": float(row.BiasMA20),
    }


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
def simulate(d, cfg=None, initial=10000.0, start=None):
    cfg = cfg or Config()
    start_i = 210 if start is None else max(210, int(d.index.searchsorted(pd.Timestamp(start))))
    if start_i >= len(d):
        raise ValueError(f"有效回测起始日期 {start} 超出历史范围或数据不足")

    fee_pct = cfg.fee_bps / 1e4
    slip_pct = cfg.slip_bps / 1e4

    cash = float(initial)
    pos = 0
    entry_price = 0.0
    planned_entry = 0.0
    initial_risk = 0.0
    stop = 0.0
    next_day_stop = 0.0
    target = 0.0
    basis = 0.0
    highest_after_entry = 0.0
    current_risk_amt = 0.0  # [v8.1 Patch 3]: 当前持仓剩余的真实风险金额，随分批止盈按比例递减

    tp_taken = False
    breakeven_triggered = False

    trades = []
    curve = [{"Date": d.index[start_i - 1], "Equity": cash, "Benchmark": initial}]
    benchmark_entry = float(d.Open.iloc[start_i])

    for i in range(start_i, len(d)):
        row, prev, date = d.iloc[i], d.iloc[i - 1], d.index[i]
        current_equity = cash + (pos * row.Close if pos > 0 else 0)

        # ---------------------------------------------------------------------
        # [任务B.2]: 当天开盘生效的止损价是昨收盘后确定的止损价
        # ---------------------------------------------------------------------
        active_stop = next_day_stop if pos > 0 else stop

        exited_today = False

        # 1. 持仓出场检查 (如果今天有持仓)
        if pos > 0:
            highest_after_entry = max(highest_after_entry, float(row.High))

            # [任务B.1]: 同日双触发时，止损优先结算
            if row.Low <= active_stop:
                exited_today = True
                raw_exit_price = min(row.Open, active_stop) if row.Open < active_stop else active_stop
                real_exit_price = raw_exit_price * (1.0 - slip_pct)
                proceeds = pos * real_exit_price * (1.0 - fee_pct)
                net_pnl = proceeds - basis

                # [v8.1 Patch 3]: 用剩余的真实风险金额算这笔的R倍数
                r_multiple = (net_pnl / current_risk_amt) if current_risk_amt > 0 else 0.0
                current_risk_amt = 0.0

                if breakeven_triggered and abs(real_exit_price - planned_entry) / planned_entry < 0.02:
                    exit_reason = "🛡️ 保本止损出场"
                else:
                    exit_reason = "🚨 吊灯/唐奇安止损出场"

                trades.append({
                    "日期": date,
                    "操作": "卖出",
                    "原因": exit_reason,
                    "成交价": real_exit_price,
                    "净盈亏": net_pnl,
                    "仓位占比%": round((pos * real_exit_price / current_equity) * 100, 2),
                    "实际风险占比%": 0.0,
                    "R倍数": r_multiple,
                })
                cash += proceeds
                pos = 0
                next_day_stop = 0.0

            # [任务B.3 & D]: 只有当今天未发生止损平仓且仍有持仓时，才检查分批止盈
            if (not exited_today) and (pos > 0) and (not tp_taken) and (cfg.partial_tp_ratio > 0) and (row.High >= target):
                tp_shares = math.floor(pos * cfg.partial_tp_ratio)
                if tp_shares > 0:
                    raw_tp_price = min(row.High, target)
                    real_tp_price = raw_tp_price * (1.0 - slip_pct)
                    tp_proceeds = tp_shares * real_tp_price * (1.0 - fee_pct)
                    tp_cost_portion = basis * (tp_shares / pos)
                    tp_net_pnl = tp_proceeds - tp_cost_portion

                    # [v8.1 Patch 3]: 按卖出份额比例分摊真实风险金额，算这笔止盈的R倍数
                    sell_ratio = tp_shares / pos
                    sell_risk_amt = current_risk_amt * sell_ratio
                    r_multiple = (tp_net_pnl / sell_risk_amt) if sell_risk_amt > 0 else 0.0
                    current_risk_amt -= sell_risk_amt

                    trades.append({
                        "日期": date,
                        "操作": "卖出",
                        "原因": "🎯 触及目标价分批止盈",
                        "成交价": real_tp_price,
                        "净盈亏": tp_net_pnl,
                        "仓位占比%": round((tp_shares * real_tp_price / current_equity) * 100, 2),
                        "实际风险占比%": 0.0,
                        "R倍数": r_multiple,
                    })

                    cash += tp_proceeds
                    pos -= tp_shares
                    basis -= tp_cost_portion
                    tp_taken = True

                    # 分批止盈后若 pos 归零 (例如 partial_tp_ratio=1.0)，防止后续产生幽灵交易
                    if pos == 0:
                        exited_today = True
                        next_day_stop = 0.0
                        current_risk_amt = 0.0

            # [任务B.2]: 尾盘根据当天走势计算新止损，延后至明日生效 (next_day_stop)
            if pos > 0 and (not exited_today):
                cand_stop = active_stop

                be_target_price = planned_entry + (cfg.breakeven_trigger_r * initial_risk)
                if (not breakeven_triggered) and (row.High >= be_target_price):
                    breakeven_stop = planned_entry * 1.001
                    cand_stop = max(cand_stop, breakeven_stop)
                    breakeven_triggered = True

                if tp_taken:
                    cand_stop = max(cand_stop, planned_entry * 1.001)

                chandelier_stop = highest_after_entry - 3.2 * row.ATR
                donchian_stop = float(row.DonchianLow10)
                next_day_stop = max(cand_stop, chandelier_stop, donchian_stop)

        # 2. [任务B.4]: 开仓买入逻辑 (昨日信号 -> 今日开盘/盘中成交)
        if pos == 0 and (not exited_today):
            p = plan(prev, cfg)
            if p and p["eligible"] and prev.VolRatio > 0.9:
                planned_target_price = p["entry"]
                should_buy = False
                raw_fill_price = 0.0

                if cfg.execution_mode.startswith("追势"):
                    should_buy = True
                    raw_fill_price = float(row.Open)
                else:
                    if row.Low <= planned_target_price:
                        should_buy = True
                        raw_fill_price = min(row.Open, planned_target_price)

                if should_buy:
                    real_fill_price = raw_fill_price * (1.0 + slip_pct)
                    planned_entry = planned_target_price
                    stop_price = p["stop"]

                    # [任务C]: 把滑点和手续费算进"每股真实风险"
                    # 每股真实风险 = (入场价 - 止损价 * (1 - 滑点)) + 手续费 * (入场价 + 止损价 * (1 - 滑点))
                    stop_after_slip = stop_price * (1.0 - slip_pct)
                    per_share_risk = (real_fill_price - stop_after_slip) + fee_pct * (real_fill_price + stop_after_slip)

                    if per_share_risk > 0:
                        risk_amount = current_equity * (cfg.risk_pct / 100.0)
                        raw_shares = risk_amount / per_share_risk
                        max_shares_cap = (current_equity * (cfg.max_position_pct / 100.0)) / real_fill_price
                        max_shares_cash = (cash * 0.98) / (real_fill_price * (1.0 + fee_pct))

                        final_shares = math.floor(min(raw_shares, max_shares_cap, max_shares_cash))

                        if final_shares > 0:
                            pos = final_shares
                            entry_price = real_fill_price
                            basis = pos * entry_price * (1.0 + fee_pct)
                            cash -= basis

                            stop = stop_price
                            next_day_stop = stop_price
                            target = p["target"]
                            initial_risk = planned_entry - stop
                            highest_after_entry = entry_price

                            tp_taken = False
                            breakeven_triggered = False

                            pos_pct = round((basis / current_equity) * 100, 2)
                            actual_risk_pct = round((per_share_risk * pos / current_equity) * 100, 2)

                            # [v8.1 Patch 3]: 记录这笔交易开仓时实际承担的总风险金额，供后续R倍数计算使用
                            current_risk_amt = per_share_risk * pos

                            trades.append({
                                "日期": date,
                                "操作": "买入",
                                "原因": p.get("buy_mode", "买入信号"),
                                "成交价": real_fill_price,
                                "净盈亏": None,
                                "仓位占比%": pos_pct,
                                "实际风险占比%": actual_risk_pct,
                                "风险金额": current_risk_amt,
                            })

        current_equity = cash + (pos * row.Close if pos > 0 else 0)
        curve.append({"Date": date, "Equity": current_equity, "Benchmark": initial * (row.Close / benchmark_entry)})

    eq = pd.DataFrame(curve).set_index("Date")
    ledger = pd.DataFrame(trades)
    sells = [t["净盈亏"] for t in trades if t["操作"] == "卖出" and t["净盈亏"] is not None]
    final = float(eq.Equity.iloc[-1])

    # [任务I & v8.1 Patch 3]: 期望值 Expectancy 与胜率，基于每笔交易实际风险算出的R倍数序列
    r_multiples = [t["R倍数"] for t in trades if t["操作"] == "卖出" and "R倍数" in t]
    r_wins = [r for r in r_multiples if r > 0]
    r_losses = [abs(r) for r in r_multiples if r < 0]
    win_rate = (len(r_wins) / len(r_multiples)) if r_multiples else 0.0

    avg_win_r = (sum(r_wins) / len(r_wins)) if r_wins else 0.0
    avg_loss_r = (sum(r_losses) / len(r_losses)) if r_losses else 0.0
    expectancy_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

    metrics = {
        "期望值 (R)": expectancy_r,
        "胜率%": win_rate * 100.0,
        "平均盈利 (R)": avg_win_r,
        "平均亏损 (R)": avg_loss_r,
        "最终资产": final,
        "收益率%": (final / initial - 1) * 100,
        "买入持有%": (eq.Benchmark.iloc[-1] / initial - 1) * 100,
        "最大回撤%": float((eq.Equity / eq.Equity.cummax() - 1).min() * 100),
        "已平仓笔数": len(sells),
    }
    return metrics, eq, ledger


# [任务E]: 多标的真实共享资金池组合回测引擎
def simulate_portfolio(data_dict, cfg=None, initial=100000.0, start=None):
    """
    简化前提：1) 当天卖出后释放的资金，同一天内即可用于当天的新开仓（T+0 资金循环使用）；
             2) 同一标的不在同一天内卖出又重新买入。
    资金调度：每天对全池检查信号，按评分降序排列，优先配给高分标的，直到现金或持仓槽位上限用完。
    """
    # [v8.1 Patch 4]: 原注释写的是"次日可用于开仓"，与实际代码行为（当天出场后立刻更新cash、
    # 同一天内的开仓逻辑直接使用更新后的cash）不一致，这里改成准确描述实际行为的措辞。
    cfg = cfg or Config()
    fee_pct = cfg.fee_bps / 1e4
    slip_pct = cfg.slip_bps / 1e4

    valid_series = {}
    for s, df in data_dict.items():
        if df is None or len(df) < 210:
            continue
        start_i = 210 if start is None else max(210, int(df.index.searchsorted(pd.Timestamp(start))))
        if start_i < len(df):
            valid_series[s] = df.iloc[start_i - 1 :]

    if not valid_series:
        raise ValueError("全池没有标的包含足够的回测历史数据")

    all_dates = sorted(list(set().union(*[df.index for df in valid_series.values()])))
    all_dates = [d for d in all_dates if d >= pd.Timestamp(start)] if start else all_dates[210:]

    cash = float(initial)
    positions = {}  # symbol -> dict of pos info
    trades = []
    portfolio_curve = []

    for date in all_dates:
        # 1. 出场处理
        symbols_holding = list(positions.keys())
        for sym in symbols_holding:
            df = valid_series[sym]
            if date not in df.index:
                continue
            idx = df.index.get_loc(date)
            row = df.iloc[idx]
            pos_info = positions[sym]

            pos_info["highest"] = max(pos_info["highest"], float(row.High))
            active_stop = pos_info["next_day_stop"]
            exited_today = False

            # [任务B.1]: 止损优先
            if row.Low <= active_stop:
                exited_today = True
                raw_exit_price = min(row.Open, active_stop) if row.Open < active_stop else active_stop
                real_exit_price = raw_exit_price * (1.0 - slip_pct)
                proceeds = pos_info["pos"] * real_exit_price * (1.0 - fee_pct)
                net_pnl = proceeds - pos_info["basis"]

                # [v8.1 Patch 3]: 用剩余风险金额算这笔止损的R倍数
                risk_left = pos_info.get("risk_amt", 0.0)
                r_multiple = (net_pnl / risk_left) if risk_left > 0 else 0.0

                trades.append({
                    "日期": date,
                    "代码": sym,
                    "操作": "卖出",
                    "原因": "🚨 止损出场",
                    "成交价": real_exit_price,
                    "净盈亏": net_pnl,
                    "R倍数": r_multiple,
                })
                cash += proceeds
                del positions[sym]

            # 分批止盈
            if (not exited_today) and (sym in positions) and (not pos_info["tp_taken"]) and (cfg.partial_tp_ratio > 0) and (row.High >= pos_info["target"]):
                tp_shares = math.floor(pos_info["pos"] * cfg.partial_tp_ratio)
                if tp_shares > 0:
                    raw_tp_price = min(row.High, pos_info["target"])
                    real_tp_price = raw_tp_price * (1.0 - slip_pct)
                    tp_proceeds = tp_shares * real_tp_price * (1.0 - fee_pct)
                    tp_cost_portion = pos_info["basis"] * (tp_shares / pos_info["pos"])
                    tp_net_pnl = tp_proceeds - tp_cost_portion

                    # [v8.1 Patch 3]: 按卖出份额比例分摊风险金额，算这笔止盈的R倍数
                    sell_ratio = tp_shares / pos_info["pos"]
                    sell_risk_amt = pos_info.get("risk_amt", 0.0) * sell_ratio
                    r_multiple = (tp_net_pnl / sell_risk_amt) if sell_risk_amt > 0 else 0.0
                    pos_info["risk_amt"] = pos_info.get("risk_amt", 0.0) - sell_risk_amt

                    trades.append({
                        "日期": date,
                        "代码": sym,
                        "操作": "卖出",
                        "原因": "🎯 分批止盈",
                        "成交价": real_tp_price,
                        "净盈亏": tp_net_pnl,
                        "R倍数": r_multiple,
                    })
                    cash += tp_proceeds
                    pos_info["pos"] -= tp_shares
                    pos_info["basis"] -= tp_cost_portion
                    pos_info["tp_taken"] = True

                    if pos_info["pos"] == 0:
                        del positions[sym]
                        exited_today = True

            # 更新明日止损
            if (sym in positions) and (not exited_today):
                p_info = positions[sym]
                cand_stop = active_stop
                be_target = p_info["planned_entry"] + cfg.breakeven_trigger_r * (p_info["planned_entry"] - p_info["stop"])
                if (not p_info["breakeven_triggered"]) and (row.High >= be_target):
                    cand_stop = max(cand_stop, p_info["planned_entry"] * 1.001)
                    p_info["breakeven_triggered"] = True
                if p_info["tp_taken"]:
                    cand_stop = max(cand_stop, p_info["planned_entry"] * 1.001)

                ch_stop = p_info["highest"] - 3.2 * row.ATR
                don_stop = float(row.DonchianLow10)
                p_info["next_day_stop"] = max(cand_stop, ch_stop, don_stop)

        # 当前组合总资产评估
        current_eq = cash
        for sym, p_info in positions.items():
            df = valid_series[sym]
            if date in df.index:
                current_eq += p_info["pos"] * df.loc[date, "Close"]

        # 2. 开仓检查
        candidate_buys = []
        if len(positions) < cfg.portfolio_max_slots:
            for sym, df in valid_series.items():
                if sym in positions or date not in df.index:
                    continue
                idx = df.index.get_loc(date)
                if idx == 0:
                    continue
                prev_row = df.iloc[idx - 1]
                curr_row = df.iloc[idx]

                p = plan(prev_row, cfg)
                if p and p["eligible"] and prev_row.VolRatio > 0.9:
                    candidate_buys.append({
                        "symbol": sym,
                        "plan": p,
                        "score": p["score"],
                        "curr_row": curr_row,
                    })

            # 按评分高到低排序，优先买入
            candidate_buys.sort(key=lambda x: x["score"], reverse=True)

            for cand in candidate_buys:
                if len(positions) >= cfg.portfolio_max_slots:
                    break
                sym = cand["symbol"]
                p = cand["plan"]
                row = cand["curr_row"]

                planned_target_price = p["entry"]
                should_buy = False
                raw_fill_price = 0.0

                if cfg.execution_mode.startswith("追势"):
                    should_buy = True
                    raw_fill_price = float(row.Open)
                else:
                    if row.Low <= planned_target_price:
                        should_buy = True
                        raw_fill_price = min(row.Open, planned_target_price)

                if should_buy:
                    real_fill_price = raw_fill_price * (1.0 + slip_pct)
                    stop_price = p["stop"]
                    stop_after_slip = stop_price * (1.0 - slip_pct)
                    per_share_risk = (real_fill_price - stop_after_slip) + fee_pct * (real_fill_price + stop_after_slip)

                    if per_share_risk > 0:
                        risk_amount = current_eq * (cfg.risk_pct / 100.0)
                        raw_shares = risk_amount / per_share_risk
                        max_shares_cap = (current_eq * (cfg.max_position_pct / 100.0)) / real_fill_price
                        max_shares_cash = (cash * 0.98) / (real_fill_price * (1.0 + fee_pct))

                        final_shares = math.floor(min(raw_shares, max_shares_cap, max_shares_cash))

                        if final_shares > 0:
                            basis = final_shares * real_fill_price * (1.0 + fee_pct)
                            cash -= basis
                            # [v8.1 Patch 3]: 记录开仓时的真实风险金额，供后续R倍数计算使用
                            open_risk_amt = per_share_risk * final_shares
                            positions[sym] = {
                                "pos": final_shares,
                                "entry_price": real_fill_price,
                                "planned_entry": planned_target_price,
                                "stop": stop_price,
                                "next_day_stop": stop_price,
                                "target": p["target"],
                                "basis": basis,
                                "highest": real_fill_price,
                                "tp_taken": False,
                                "breakeven_triggered": False,
                                "risk_amt": open_risk_amt,
                            }
                            trades.append({
                                "日期": date,
                                "代码": sym,
                                "操作": "买入",
                                "原因": p["buy_mode"],
                                "成交价": real_fill_price,
                                "净盈亏": None,
                                "风险金额": open_risk_amt,
                            })

        # 每日汇总记录
        current_eq = cash
        for sym, p_info in positions.items():
            df = valid_series[sym]
            if date in df.index:
                current_eq += p_info["pos"] * df.loc[date, "Close"]
        portfolio_curve.append({"Date": date, "Equity": current_eq})

    eq = pd.DataFrame(portfolio_curve).set_index("Date")
    ledger = pd.DataFrame(trades)
    sells = [t["净盈亏"] for t in trades if t["操作"] == "卖出" and t["净盈亏"] is not None]
    final = float(eq.Equity.iloc[-1]) if not eq.empty else initial

    # [任务I & v8.1 Patch 3]: 组合层面同样改用基于实际风险金额的R倍数序列
    r_multiples = [t["R倍数"] for t in trades if t["操作"] == "卖出" and "R倍数" in t]
    r_wins = [r for r in r_multiples if r > 0]
    r_losses = [abs(r) for r in r_multiples if r < 0]
    win_rate = (len(r_wins) / len(r_multiples)) if r_multiples else 0.0
    avg_win_r = (sum(r_wins) / len(r_wins)) if r_wins else 0.0
    avg_loss_r = (sum(r_losses) / len(r_losses)) if r_losses else 0.0
    expectancy_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

    metrics = {
        "期望值 (R)": expectancy_r,
        "胜率%": win_rate * 100.0,
        "平均盈利 (R)": avg_win_r,
        "平均亏损 (R)": avg_loss_r,
        "最终资产": final,
        "收益率%": (final / initial - 1) * 100,
        "最大回撤%": float((eq.Equity / eq.Equity.cummax() - 1).min() * 100) if not eq.empty else 0.0,
        "已平仓笔数": len(sells),
    }
    return metrics, eq, ledger


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
        run_scan = st.button("⚡ 启动高胜率模型扫描", use_container_width=True)

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
        st.caption("⚠️ **免责声明**：评分是基于固定技术指标矩阵规则打分，不是历史胜率，也不代表未来一定盈利。股市有风险，入市需谨慎。")

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
                st.caption("💡 *以上基于历史数据回测，不代表未来一定重现。*")

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
                    st.caption("💡 *组合回测：10万初始资金共享池，按评分优先分配最多持仓槽位。*")

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
