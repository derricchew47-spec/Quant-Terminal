# ============================================================================
# QuantumSignal Terminal ULTRA | Bull/Bear Adaptive Quantitative System
# ============================================================================
# 架构融合亮点：
# 1) 主框架 (UI): 采用 Quantum 1 视效、卡片 Dashboard、自选库管理与多 Tab 布局。
# 2) 布局修复: 隐藏 Streamlit 原生 Header，调整 padding-top，修复标题遮挡问题。
# 3) 防护修补: 修复 p['buy_mode'] 的 KeyError 异常。
# 4) 牛熊自适应逻辑: 
#    - 大牛市: 自动切换 Super-Bull 突破/追涨买点 (EMA10 / 5日突破)，避免踏空。
#    - 大熊市: 引入 SPY 200日趋势拦截 + MA50/200 熊市死叉拦截，防止连续频发买入/止损。
# ============================================================================

import html
import math
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

VERSION = "ULTRA_4.1_STABLE"

# -----------------------------------------------------------------------------
# 1. 页面配置与 Cyberpunk 视觉样式 (修复标题遮挡问题)
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
    /* 隐藏顶部原生 Header 遮罩，防止挡住顶部文字 */
    header[data-testid="stHeader"] { 
        visibility: hidden; 
        height: 0px; 
    }
    
    .stApp {
        background-color: #0b0e14;
        color: #c9d1d9;
        font-family: 'Fira Code', monospace, -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* 调整顶部 Padding 为 3.5rem，保证 Scroll 到最上方时标题完好显示 */
    .block-container { 
        max-width: 1450px; 
        padding-top: 3.5rem !important; 
    }
    
    .tech-header {
        font-weight: 800;
        color: #00f0ff;
        text-shadow: 0 0 12px rgba(0,240,255,.35);
        letter-spacing: .5px;
        margin-top: 0px;
        margin-bottom: 4px;
    }
    .tech-subtitle {
        color: #8b949e;
        font-size: 11px;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 16px;
    }
    .tech-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 13px;
        box-shadow: 0 4px 15px rgba(0,0,0,.35);
        margin-bottom: 10px;
        position: relative;
        overflow: hidden;
    }
    .tech-card::before {
        content: '';
        position: absolute;
        top:0; left:0; right:0; height:2px;
        background: linear-gradient(90deg,#00f0ff,#7000ff);
    }
    .metric-title {
        font-size: 10px;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .metric-value {
        font-size: 18px;
        font-weight: 800;
        color: #fff;
        margin-top: 5px;
    }
    .metric-buy { color:#ccff00; text-shadow:0 0 8px rgba(204,255,0,.25); }
    .metric-stop { color:#ff3366; text-shadow:0 0 8px rgba(255,51,102,.25); }
    .metric-take { color:#00f0ff; text-shadow:0 0 8px rgba(0,240,255,.25); }
    .metric-good { color:#00ff66; text-shadow:0 0 8px rgba(0,255,102,.25); }
    .metric-warn { color:#ffaa00; }
    .signal-strip {
        background: linear-gradient(90deg,rgba(0,240,255,.08),rgba(112,0,255,.08));
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 10px 13px;
        margin: 8px 0 14px 0;
    }
    .score-panel {
        background: #10151d;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 12px;
    }
    .score-row {
        display:flex; align-items:center; gap:9px; margin:7px 0;
        font-size:11px;
    }
    .score-label { width:125px; color:#8b949e; }
    .score-bar { flex:1; background:#21262d; height:7px; border-radius:99px; overflow:hidden; }
    .score-fill { height:100%; background:linear-gradient(90deg,#00f0ff,#7000ff); border-radius:99px; }
    .score-number { width:50px; text-align:right; color:#fff; font-weight:700; }
    .decision-box {
        border:1px solid #30363d;
        border-radius:10px;
        background:#121821;
        padding:12px;
        margin:8px 0;
    }
    div[data-testid="stSidebar"] .stRadio > div > label {
        background:#161b22;
        border:1px solid #30363d;
        border-radius:8px;
        padding:10px 12px;
        width:100%;
        margin-bottom: 5px;
    }
    div[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background:linear-gradient(135deg,rgba(0,240,255,.14),rgba(112,0,255,.14));
        border:1.5px solid #00f0ff !important;
    }
    div[data-testid="stSidebar"] .stRadio > div > label > div:first-child { display:none; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# 2. Session State / 全局导航
# -----------------------------------------------------------------------------
NAV_OPTIONS = [
    "🚀 自动扫描 & 智能推荐",
    "🔍 单标的全量诊断",
    "🧪 策略历史回测引擎",
    "📊 自选清单监控",
]

for key, val in [
    ("current_page", NAV_OPTIONS[0]),
    ("selected_ticker", "NVDA"),
    ("scan_results", []),
    ("rr_ratio", 2.0),
    ("risk_pct", 0.5),
    ("min_score", 65),
    ("capital", 10000.0),
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
        min_price=5.0,
        max_atr_pct=8.0,
        min_score=65,
        fee_bps=5.0,
        slip_bps=5.0,
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


def cfg_from_session():
    return Config(
        rr=st.session_state.rr_ratio,
        risk_pct=st.session_state.risk_pct,
        min_score=st.session_state.min_score,
    )


# -----------------------------------------------------------------------------
# 4. 股票池预设
# -----------------------------------------------------------------------------
INDEX_PRESET_POOLS = {
    "🔥 精选核心科技 (15只)": ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN", "SMCI"],
    "💻 半导体与芯片产业链": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "MU", "TXN", "AMAT", "LRCX", "ADI", "KLAC", "ARM", "MRVL"],
    "🌐 核心ETF与资产类别": ["SPY", "QQQ", "IWM", "SOXX", "XLV", "XLF", "XLE", "ARKK", "TLT", "GLD"],
    "📊 标普 500 动态池": "SP500_AUTO",
}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_sp500_tickers():
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        return tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    except Exception:
        return ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "TSLA", "LLY"]


def parse_symbols(text):
    items = re.split(r"[,，;；\s]+", str(text).strip().upper())
    out = []
    for symbol in items:
        symbol = symbol.replace(".", "-").strip()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


# -----------------------------------------------------------------------------
# 5. SQLite 自选清单
# -----------------------------------------------------------------------------
DB_FILE = "quant_terminal_ultra.db"


def init_quant_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT, category TEXT, added_at TEXT)"
    )
    conn.commit()
    conn.close()


def add_to_watchlist(symbol, name="", category="推荐自选"):
    syms = parse_symbols(symbol)
    if syms:
        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)",
            (syms[0], name or syms[0], category, datetime.now().strftime("%Y-%m-%d")),
        )
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


init_quant_db()


# -----------------------------------------------------------------------------
# 6. 行情获取
# -----------------------------------------------------------------------------
@st.cache_data(ttl=21600, show_spinner=False)
def fetch_history(symbol: str, period: str = "3y"):
    try:
        symbol = symbol.upper().strip()
        frame = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True, actions=False)
        if frame is None or frame.empty:
            return None
        frame = frame.rename(columns={c: str(c).title() for c in frame.columns})
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in frame.columns for c in required):
            return None
        frame = frame[required].copy()
        idx = pd.DatetimeIndex(frame.index)
        try:
            idx = idx.tz_localize(None)
        except Exception:
            pass
        frame.index = idx.normalize()
        frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
        frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        return frame if len(frame) >= 35 else None
    except Exception:
        return None


# -----------------------------------------------------------------------------
# 7. 量化核心指标 (Wilder 平滑 + Supertrend + 六维评分)
# -----------------------------------------------------------------------------
def wilder(series, n=14):
    values = series.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    for i in range(n - 1, len(values)):
        if i == 0 or np.isnan(output[i - 1]):
            window = values[i - n + 1 : i + 1]
            if np.isfinite(window).all():
                output[i] = window.mean()
        elif np.isfinite(values[i]):
            output[i] = (output[i - 1] * (n - 1) + values[i]) / n
    return pd.Series(output, index=series.index)


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

    # Wilder RSI
    delta = c.diff()
    gain = wilder(delta.clip(lower=0), 14)
    loss = wilder(-delta.clip(upper=0), 14)
    rs = gain / loss.replace(0, np.nan)
    d["RSI"] = 100 - 100 / (1 + rs)

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACDSignal"] = d.MACD.ewm(span=9, adjust=False).mean()
    d["Hist"] = d.MACD - d.MACDSignal

    d["DollarVolume"] = (c * v).rolling(20).mean()
    d["ATRpct"] = d.ATR / c * 100
    d["Support"] = l.rolling(20).min()
    d["Resistance"] = h.shift().rolling(20).max()
    d["Return63"] = c.pct_change(63, fill_method=None)

    # SPY 大盘基准
    if benchmark is not None and not benchmark.empty:
        b = benchmark.Close.reindex(d.index)
        d["Relative63"] = d.Return63 - b.pct_change(63, fill_method=None)
        d["MarketMA200"] = b.rolling(200).mean()
        # 大熊市防护条件：SPY 必须高于 MA200
        d["MarketOK"] = b > d.MarketMA200
        d["MarketKnown"] = b.rolling(200).count().eq(200)
    else:
        d["Relative63"] = np.nan
        d["MarketOK"] = False
        d["MarketKnown"] = False

    # Supertrend
    at10 = wilder(tr, 10).to_numpy()
    ub = ((h + l) / 2).to_numpy() + 3 * at10
    lb = ((h + l) / 2).to_numpy() - 3 * at10
    fu, fl = ub.copy(), lb.copy()
    direction = np.zeros(len(d), dtype=int)
    prices = c.to_numpy()

    for i in range(len(d)):
        if not np.isfinite(at10[i]):
            continue
        if i == 0 or not np.isfinite(at10[i - 1]):
            direction[i] = 1 if prices[i] >= (h.iloc[i] + l.iloc[i]) / 2 else -1
        else:
            fu[i] = ub[i] if ub[i] < fu[i - 1] or prices[i - 1] > fu[i - 1] else fu[i - 1]
            fl[i] = lb[i] if lb[i] > fl[i - 1] or prices[i - 1] < fl[i - 1] else fl[i - 1]
            direction[i] = direction[i - 1]
            if direction[i - 1] == -1 and prices[i] > fu[i]:
                direction[i] = 1
            elif direction[i - 1] == 1 and prices[i] < fl[i]:
                direction[i] = -1

    d["STDirection"] = direction

    # 六维得分 (0–100)
    d["TrendScore"] = (
        (c > d.MA50).astype(int) * 10
        + (d.MA50 > d.MA200).astype(int) * 10
        + (d.MA50 > d.MA50.shift(10)).astype(int) * 10
    )
    d["StrengthScore"] = np.select(
        [d.Relative63 > 0.10, d.Relative63 > 0.03, d.Relative63 > 0],
        [20, 15, 10],
        default=0,
    )
    d["MomentumScore"] = (
        d.RSI.between(45, 65).astype(int) * 10
        + (d.Hist > 0).astype(int) * 5
        + (d.STDirection == 1).astype(int) * 5
    )
    d["LiquidityScore"] = np.select([d.DollarVolume >= 50e6, d.DollarVolume >= 10e6], [10, 5], default=0)
    d["VolatilityScore"] = np.select([d.ATRpct.between(1, 4), d.ATRpct.between(0.3, 6)], [10, 5], default=0)
    d["MarketScore"] = d.MarketOK.astype(int) * 10

    score_cols = ["TrendScore", "StrengthScore", "MomentumScore", "LiquidityScore", "VolatilityScore", "MarketScore"]
    d["Score"] = d[score_cols].sum(axis=1).astype(int)

    return d


# -----------------------------------------------------------------------------
# 8. 重构逻辑：牛熊自适应交易计划 (彻底杜绝 KeyError: buy_mode)
# -----------------------------------------------------------------------------
def plan(row, cfg=None):
    cfg = cfg or Config()
    required = ["Close", "ATR", "MA50", "MA200", "Support", "EMA10", "EMA20", "RSI", "Score"]
    if any(k not in row or not np.isfinite(row[k]) for k in required) or row.ATR <= 0:
        return None

    reasons = []

    # 1. 熊市防连续止损拦截 (Bear Market Safeguard)
    is_bear_market = not row.MarketOK or (row.Close < row.MA200 and row.MA50 < row.MA200)
    if is_bear_market:
        reasons.append("🚫 熊市拦截：大盘或标的处于空头死叉，暂停买入防连续止损")

    # 2. 牛市/强势股买点抬升自适应 (Bull Market Anti-Skate)
    is_super_bull = (
        row.Score >= 75
        and row.Close > row.MA50
        and (np.isnan(row.Relative63) or row.Relative63 > 0.05)
    )

    if is_super_bull and not is_bear_market:
        # 大牛市：不傻等 EMA20，买点抬升至 EMA10 / 5日微幅回调，防止踏空
        entry = max(float(row.EMA10), float(row.Close * 0.985))
        buy_mode = "🚀 大牛市突破/主升跟进"
    else:
        # 震荡市：采用传统的逢低回踩 EMA20
        entry = min(float(row.Close), float(row.EMA20))
        buy_mode = "⚡ 稳健逢低回踩"

    # 3. 结构止损与目标价
    stop = min(entry - 1.5 * row.ATR, row.Support - 0.25 * row.ATR)
    risk = entry - stop
    target = entry + cfg.rr * risk

    # 4. 其他硬过滤校验
    if row.Close < cfg.min_price:
        reasons.append("价格低于门槛")
    if row.DollarVolume < cfg.min_dollar_volume:
        reasons.append("20日成交额不足")
    if row.ATRpct > cfg.max_atr_pct:
        reasons.append("波动率过高")
    if row.Score < cfg.min_score:
        reasons.append("综合评分不足")
    if row.RSI > 75:
        reasons.append("RSI过热")

    entry_low = max(stop + 0.1 * risk, entry - 0.25 * row.ATR)
    
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "entry_low": entry_low,
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "score": int(row.Score),
        "buy_mode": buy_mode,  # 确保必选字段完整返回
        "is_bear": is_bear_market,
    }


def quantity(cash, entry, stop, cfg):
    fee = cfg.fee_bps / 1e4
    slip = cfg.slip_bps / 1e4
    per_share = entry - stop * (1 - slip) + fee * (entry + stop * (1 - slip))
    if cash <= 0 or stop <= 0 or per_share <= 0:
        return 0
    risk_qty = cash * cfg.risk_pct / 100 / per_share
    pos_qty = cash * cfg.max_position_pct / 100 / (entry * (1 + fee))
    return max(0, math.floor(min(risk_qty, pos_qty)))


def build_summary(symbol, d, cfg):
    if len(d) < 210:
        raise ValueError("历史交易日不足 210 天")
    row = d.iloc[-1]
    p = plan(row, cfg)
    if p is None:
        raise ValueError("指标计算失败")
    return {
        "代码": symbol,
        "评分": p["score"],
        "状态": "候选 · 入场挂单" if p["eligible"] else ("🚫 熊市拦截" if p["is_bear"] else "观察 · 条件未满足"),
        "收盘价": float(row.Close),
        "买入参考": p["entry"],
        "止损": p["stop"],
        "目标": p["target"],
        "RSI": float(row.RSI),
        "ATR%": float(row.ATRpct),
        "买入模式": p.get("buy_mode", "⚡ 动态量化"),
        "行情日期": d.index[-1].strftime("%Y-%m-%d"),
        "原因": "；".join(p["reasons"]) or "满足全部适应性筛选条件",
        "TrendScore": int(row.TrendScore),
        "StrengthScore": int(row.StrengthScore),
        "MomentumScore": int(row.MomentumScore),
        "LiquidityScore": int(row.LiquidityScore),
        "VolatilityScore": int(row.VolatilityScore),
        "MarketScore": int(row.MarketScore),
    }


def make_signal(symbol, frame, cfg, benchmark):
    d = indicators(frame, benchmark)
    summary = build_summary(symbol, d, cfg)
    p = plan(d.iloc[-1], cfg)
    return {
        "symbol": symbol,
        "df": d,
        "summary": summary,
        "plan": p,
        "current_price": float(d.Close.iloc[-1]),
        "quant_score": int(summary["评分"]),
        "eligible": bool(p["eligible"]),
        "rsi": float(d.RSI.iloc[-1]),
        "atr_pct": float(d.ATRpct.iloc[-1]),
        "relative63": float(d.Relative63.iloc[-1] * 100) if np.isfinite(d.Relative63.iloc[-1]) else np.nan,
    }


# -----------------------------------------------------------------------------
# 9. 策略历史回测引擎 (严谨时间顺序撮合 + 牛熊规则)
# -----------------------------------------------------------------------------
def simulate(d, cfg=None, initial=10000.0, start=None):
    cfg = cfg or Config()
    start_i = 210 if start is None else max(210, int(d.index.searchsorted(pd.Timestamp(start))))
    if start_i >= len(d):
        raise ValueError("有效回测区间不足")

    fee = cfg.fee_bps / 1e4
    slip = cfg.slip_bps / 1e4
    cash = float(initial)
    pos, entry, stop, target, basis = 0, 0.0, 0.0, 0.0, 0.0
    trades = []
    curve = [{"Date": d.index[start_i - 1], "Equity": cash, "Benchmark": initial}]
    benchmark_entry = float(d.Open.iloc[start_i])

    for i in range(start_i, len(d)):
        row, prev, date = d.iloc[i], d.iloc[i - 1], d.index[i]
        exited = False

        # 离场卖出逻辑
        if pos > 0:
            if row.Open <= stop:
                proceeds = pos * (row.Open * (1 - slip)) * (1 - fee)
                cash += proceeds
                trades.append({"日期": date, "操作": "卖出", "原因": "跳空止损", "价格": row.Open, "净盈亏": proceeds - basis})
                pos = 0
                exited = True
            elif row.Open >= target:
                proceeds = pos * target * (1 - fee)
                cash += proceeds
                trades.append({"日期": date, "操作": "卖出", "原因": "止盈离场", "价格": target, "净盈亏": proceeds - basis})
                pos = 0
                exited = True

        # 入场买入逻辑 (前一日信号 -> 次日限价)
        if pos == 0 and not exited:
            p = plan(prev, cfg)
            if p and p["eligible"] and row.Low <= p["entry"]:
                fill = min(float(row.Open), p["entry"]) if row.Open <= p["entry"] else p["entry"]
                q = quantity(cash, fill, p["stop"], cfg)
                if q > 0:
                    pos = q
                    entry, stop = fill, p["stop"]
                    target = entry + cfg.rr * (entry - stop)
                    basis = pos * entry * (1 + fee)
                    cash -= basis
                    trades.append({"日期": date, "操作": "买入", "原因": p.get("buy_mode", "入场挂单"), "价格": entry, "净盈亏": None})

        # 移动止损 (次日生效)
        if pos > 0:
            if row.Low <= stop:
                proceeds = pos * stop * (1 - slip) * (1 - fee)
                cash += proceeds
                trades.append({"日期": date, "操作": "卖出", "原因": "盘中止损", "价格": stop, "净盈亏": proceeds - basis})
                pos = 0
            else:
                stop = max(stop, float(row.High - 2 * row.ATR))

        curve.append({"Date": date, "Equity": cash + pos * row.Close, "Benchmark": initial * row.Close / benchmark_entry})

    eq = pd.DataFrame(curve).set_index("Date")
    ledger = pd.DataFrame(trades)
    sells = [t["净盈亏"] for t in trades if t["操作"] == "卖出" and t["净盈亏"] is not None]
    gains = sum(max(0, p) for p in sells)
    losses = -sum(min(0, p) for p in sells)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    final = float(eq.Equity.iloc[-1])

    metrics = {
        "最终资产": final,
        "收益率%": (final / initial - 1) * 100,
        "买入持有%": (eq.Benchmark.iloc[-1] / initial - 1) * 100,
        "最大回撤%": float((eq.Equity / eq.Equity.cummax() - 1).min() * 100),
        "年化收益%": ((final / initial) ** (1 / years) - 1) * 100,
        "已平仓笔数": len(sells),
        "胜率%": (sum(p > 0 for p in sells) / len(sells) * 100) if sells else None,
        "盈亏金额比": (gains / losses) if losses else None,
    }
    return metrics, eq, ledger


# -----------------------------------------------------------------------------
# 10. UI 渲染辅助函数 (Quantum 1 卡片与 Dashboard 布局)
# -----------------------------------------------------------------------------
def metric_card(title, value, css_class=""):
    return f"<div class='tech-card'><div class='metric-title'>{html.escape(title)}</div><div class='metric-value {css_class}'>{html.escape(str(value))}</div></div>"


def render_chart(sig_data, days=90):
    d = sig_data["df"].tail(days)
    p = sig_data["plan"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name="日K"), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.EMA10, name="EMA10", line=dict(color="#00f0ff", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MA50, name="MA50", line=dict(color="#ffaa00", width=1)), row=1, col=1)
    
    if p:
        fig.add_hline(y=p["entry"], line_dash="dash", line_color="#ccff00", annotation_text="买入参考", row=1, col=1)
        fig.add_hline(y=p["stop"], line_dash="dash", line_color="#ff3366", annotation_text="止损", row=1, col=1)
        fig.add_hline(y=p["target"], line_dash="dash", line_color="#00f0ff", annotation_text="目标", row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(color="#b87cff", width=1.2)), row=2, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#161b22", height=500, margin=dict(l=10, r=10, t=20, b=10))
    return fig


# -----------------------------------------------------------------------------
# 11. STREAMLIT 渲染主入口 (Quantum 1 UI 框架)
# -----------------------------------------------------------------------------
st.markdown('<h3 class="tech-header">⚡ QUANTUM TERMINAL ULTRA</h3>', unsafe_allow_html=True)
st.markdown('<div class="tech-subtitle">Bull/Bear Adaptive Trading Engine & Multi-Dimensional Research</div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🎛️ 终端控制台")
    app_mode = st.radio("导航菜单", NAV_OPTIONS, index=NAV_OPTIONS.index(st.session_state.current_page))
    st.session_state.current_page = app_mode
    st.markdown("---")
    with st.form("sidebar_cfg"):
        st.markdown("#### ⚙️ 策略风控配置")
        st.session_state.rr_ratio = st.slider("目标盈亏比 (R/R)", 1.0, 5.0, float(st.session_state.rr_ratio), 0.5)
        st.session_state.risk_pct = st.slider("单笔风控 %", 0.1, 5.0, float(st.session_state.risk_pct), 0.1)
        st.session_state.min_score = st.slider("最低触发评分", 0, 100, int(st.session_state.min_score), 5)
        st.session_state.capital = st.number_input("账户总资金 ($)", value=float(st.session_state.capital), step=1000.0)
        st.form_submit_button("保存并更新")

cfg = cfg_from_session()

# =============================================================================
# TAB 1: 自动扫描 & 智能推荐 (添加安全获取防护)
# =============================================================================
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 市场全池自动扫描与牛熊识别")
    c1, c2, c3 = st.columns([2.5, 3.5, 1.5])
    with c1: selected_preset = st.selectbox("预设池", list(INDEX_PRESET_POOLS.keys()))
    default_pool = fetch_sp500_tickers() if INDEX_PRESET_POOLS[selected_preset] == "SP500_AUTO" else INDEX_PRESET_POOLS[selected_preset]
    with c2: custom_pool_str = st.text_input("待扫描代码", value=", ".join(default_pool))
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动量化扫描", use_container_width=True)

    if run_scan:
        symbols = parse_symbols(custom_pool_str)
        benchmark = fetch_history("SPY", "3y")
        results = []
        progress = st.progress(0, text="并行量化分析中...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {executor.submit(fetch_history, s, "3y"): s for s in symbols}
            done = 0
            for future in as_completed(future_map):
                s = future_map[future]
                done += 1
                frame = future.result()
                if frame is not None and benchmark is not None:
                    try:
                        sig = make_signal(s, frame, cfg, benchmark)
                        results.append(sig)
                    except Exception:
                        pass
                progress.progress(done / len(symbols))
        progress.empty()
        results.sort(key=lambda x: (x["eligible"], x["quant_score"]), reverse=True)
        st.session_state.scan_results = results

    res = st.session_state.get("scan_results", [])
    if res:
        eligible_res = [r for r in res if r["eligible"]]
        st.markdown(f"<div class='signal-strip'><b>扫描完成</b> · 共 {len(res)} 只 · 达标候选 {len(eligible_res)} 只</div>", unsafe_allow_html=True)
        
        # 顶部 3 大卡片 (添加安全获取防护)
        top3 = eligible_res[:3] if eligible_res else res[:3]
        cols = st.columns(len(top3))
        for i, r in enumerate(top3):
            p = r.get("plan", {})
            buy_mode_str = p.get("buy_mode", "⚡ 动态量化") if p else "未触发"
            entry_val = p.get("entry", 0.0) if p else 0.0
            stop_val = p.get("stop", 0.0) if p else 0.0
            
            with cols[i]:
                st.markdown(
                    f"""<div class='tech-card'>
                    <div style='color:#00f0ff;font-weight:800;font-size:11px'>TOP {i+1} · {r['symbol']}</div>
                    <div style='font-size:22px;font-weight:800;color:#fff'>${r['current_price']:.2f}</div>
                    <div style='font-size:12px;color:#ccff00'>模式: {html.escape(buy_mode_str)}</div>
                    <hr style='border-color:#30363d;margin:6px 0'>
                    <div style='font-size:11px;color:#8b949e'>买入参考: <b style='color:#ccff00'>${entry_val:.2f}</b></div>
                    <div style='font-size:11px;color:#8b949e'>止损位置: <b style='color:#ff3366'>${stop_val:.2f}</b></div>
                    </div>""",
                    unsafe_allow_html=True,
                )

        # 全量结果表格
        df_display = pd.DataFrame([{
            "代码": r["symbol"], 
            "评分": r["quant_score"], 
            "状态": r["summary"]["状态"], 
            "买入模式": r.get("plan", {}).get("buy_mode", "⚡ 动态量化"), 
            "现价": r["current_price"], 
            "买入参考": r.get("plan", {}).get("entry", 0.0), 
            "止损": r.get("plan", {}).get("stop", 0.0), 
            "目标": r.get("plan", {}).get("target", 0.0), 
            "原因": r["summary"]["原因"]
        } for r in res])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 2: 单标的全量诊断 (Quantum 1 UI 卡片 Dashboard)
# =============================================================================
elif app_mode == "🔍 单标的全量诊断":
    st.markdown("### 🔍 标的全量深度量化诊断")
    c1, c2 = st.columns([3, 1])
    with c1:
        ticker_input = st.text_input("股票代码", value=st.session_state.selected_ticker).upper().strip()
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        diag_btn = st.button("⚡ 诊断标的", use_container_width=True)

    if diag_btn:
        st.session_state.selected_ticker = parse_symbols(ticker_input)[0]

    sym = st.session_state.selected_ticker
    frame = fetch_history(sym, "3y")
    benchmark = fetch_history("SPY", "3y")

    if frame is not None and benchmark is not None:
        sig = make_signal(sym, frame, cfg, benchmark)
        p = sig["plan"]
        s = sig["summary"]

        html_cards = (
            metric_card("现价", f"${sig['current_price']:.2f}")
            + metric_card("自适应买入参考", f"${p['entry']:.2f}", "metric-buy")
            + metric_card("结构止损位", f"${p['stop']:.2f}", "metric-stop")
            + metric_card(f"目标价 ({cfg.rr:.1f}R)", f"${p['target']:.2f}", "metric-take")
        )
        st.markdown(f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{html_cards}</div>", unsafe_allow_html=True)

        st.markdown(
            f"""<div class='decision-box'>
            <b>💡 运行策略: {p.get('buy_mode', '⚡ 动态量化')}</b><br>
            <span style='font-size:11px;color:#8b949e;'>
            综合评分: <b style='color:#fff'>{sig['quant_score']} / 100</b> · 
            RSI: <b style='color:#fff'>{sig['rsi']:.1f}</b> · 
            状态: <b style='color:#00f0ff'>{s['状态']}</b>
            </span>
            </div>""",
            unsafe_allow_html=True,
        )

        st.plotly_chart(render_chart(sig), use_container_width=True)

        if st.button("➕ 加入自选监控", use_container_width=True):
            add_to_watchlist(sym)
            st.success(f"{sym} 已成功加入自选清单！")

# =============================================================================
# TAB 3: 策略历史回测引擎 (严谨时间撮合 + 牛熊验证)
# =============================================================================
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 牛熊自适应策略回测引擎")
    with st.form("bt_form"):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: bt_sym = st.text_input("回测代码", value=st.session_state.selected_ticker).upper()
        with c2: start_d = st.date_input("开始日期", value=pd.Timestamp.now() - pd.DateOffset(years=2))
        with c3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            run_bt = st.form_submit_button("🚀 运行回测")

    if run_bt:
        frame = fetch_history(bt_sym, "5y")
        benchmark = fetch_history("SPY", "5y")
        if frame is not None and benchmark is not None:
            d = indicators(frame, benchmark)
            metrics, eq, ledger = simulate(d, cfg, initial=st.session_state.capital, start=str(start_d))

            html_bt_cards = (
                metric_card("策略终值收益", f"{metrics['收益率%']:+.2f}%", "metric-good" if metrics['收益率%']>=0 else "metric-stop")
                + metric_card("基准买入持有", f"{metrics['买入持有%']:+.2f}%")
                + metric_card("最大回撤 (Max DD)", f"{metrics['最大回撤%']:.2f}%", "metric-stop")
                + metric_card("胜率 / 已平仓", f"{metrics['胜率%']:.1f}% ({metrics['已平仓笔数']}笔)" if metrics['胜率%'] else "N/A", "metric-buy")
            )
            st.markdown(f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{html_bt_cards}</div>", unsafe_allow_html=True)

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Equity, name="Quantum 策略", line=dict(color="#00f0ff", width=2)))
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Benchmark, name="标的买入持有", line=dict(color="#6e7681", width=1.5, dash="dot")))
            fig_eq.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#161b22", height=380)
            st.plotly_chart(fig_eq, use_container_width=True)

            st.markdown("#### 🧾 详细交易明细")
            st.dataframe(ledger, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 4: 自选清单监控 (SQLite 持久化 + 批量诊断)
# =============================================================================
else:
    st.markdown("### 📊 自选清单实时监控")
    watch_df = get_watchlist()
    if watch_df.empty:
        st.info("自选清单为空，请在“单标的全量诊断”中添加标的。")
    else:
        benchmark = fetch_history("SPY", "3y")
        watch_results = []
        for sym in watch_df["symbol"]:
            frame = fetch_history(sym, "3y")
            if frame is not None and benchmark is not None:
                try:
                    sig = make_signal(sym, frame, cfg, benchmark)
                    watch_results.append(sig)
                except Exception:
                    pass
        
        if watch_results:
            df_w = pd.DataFrame([{
                "代码": r["symbol"], 
                "评分": r["quant_score"], 
                "状态": r["summary"]["状态"],
                "买入模式": r.get("plan", {}).get("buy_mode", "⚡ 动态量化"), 
                "现价": r["current_price"], 
                "买入参考": r.get("plan", {}).get("entry", 0.0),
                "止损": r.get("plan", {}).get("stop", 0.0), 
                "目标": r.get("plan", {}).get("target", 0.0)
            } for r in watch_results])
            st.dataframe(df_w, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        c1, c2 = st.columns([3, 1])
        with c1: rem_sym = st.selectbox("选择移除标的", watch_df["symbol"].tolist())
        with c2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("🗑️ 移除自选", use_container_width=True):
                remove_from_watchlist(rem_sym)
                st.rerun()
