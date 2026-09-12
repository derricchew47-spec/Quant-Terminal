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


VERSION = "Q1_UI_Q2_LOGIC_3.0"

# -----------------------------------------------------------------------------
# 1. Quantum 1 页面配置 + Cyberpunk 视觉
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="QuantumSignal Terminal PRO",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    .stApp {
        background-color: #0b0e14;
        color: #c9d1d9;
        font-family: 'Fira Code', monospace, -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .block-container { max-width: 1450px; padding-top: 1.2rem; }
    .tech-header {
        font-weight: 800;
        color: #00f0ff;
        text-shadow: 0 0 12px rgba(0,240,255,.35);
        letter-spacing: .5px;
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
        font-size: 20px;
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
    div[data-testid="stSidebar"] .stRadio > div { gap:8px; }
    div[data-testid="stSidebar"] .stRadio > div > label {
        background:#161b22;
        border:1px solid #30363d;
        border-radius:8px;
        padding:10px 12px;
        width:100%;
        transition:all .18s ease;
    }
    div[data-testid="stSidebar"] .stRadio > div > label:hover {
        border-color:#00f0ff;
        background:#1c2129;
    }
    div[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background:linear-gradient(135deg,rgba(0,240,255,.14),rgba(112,0,255,.14));
        border:1.5px solid #00f0ff !important;
    }
    div[data-testid="stSidebar"] .stRadio > div > label > div:first-child { display:none; }
    .stTextInput input, .stNumberInput input, .stSelectbox div {
        background:#0b0e14 !important;
        color:#00f0ff !important;
        border:1px solid #30363d !important;
        border-radius:6px !important;
        font-family:'Fira Code',monospace !important;
    }
    div.stButton > button, div.stFormSubmitButton > button {
        background:linear-gradient(135deg,#00f0ff 0%,#7000ff 100%) !important;
        color:#ffffff !important;
        border:none !important;
        font-weight:800 !important;
        border-radius:7px !important;
        box-shadow:0 0 10px rgba(0,240,255,.2) !important;
    }
    .small-muted { color:#6e7681; font-size:10px; }
    @media (max-width: 700px) {
        .block-container { padding-left:.7rem; padding-right:.7rem; }
        .metric-value { font-size:17px; }
        .score-label { width:105px; }
    }
</style>
""",
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# 2. Navigation / Session State（保留 Quantum 1 四页结构）
# -----------------------------------------------------------------------------
NAV_OPTIONS = [
    "🚀 自动扫描 & 智能推荐",
    "🔍 单标的全量诊断",
    "🧪 策略历史回测引擎",
    "📊 自选清单监控",
]

if "current_page" not in st.session_state:
    st.session_state.current_page = NAV_OPTIONS[0]
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = "NVDA"
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "rr_ratio" not in st.session_state:
    st.session_state.rr_ratio = 2.0
if "risk_pct" not in st.session_state:
    st.session_state.risk_pct = 0.5
if "min_score" not in st.session_state:
    st.session_state.min_score = 65
if "capital" not in st.session_state:
    st.session_state.capital = 10000.0


# -----------------------------------------------------------------------------
# 3. Config：Quantum 2 风控 / 筛选模型
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
        if not (1 <= self.rr <= 5):
            raise ValueError("目标盈亏比必须在 1–5 之间")
        if not (0 < self.risk_pct <= 5):
            raise ValueError("单笔风险必须大于 0 且不超过 5%")
        if not (0 < self.max_position_pct <= 100):
            raise ValueError("单只持仓上限必须在 0–100%")
        if min(self.fee_bps, self.slip_bps, self.min_dollar_volume, self.min_price) < 0:
            raise ValueError("风控参数不能为负")


def cfg_from_session():
    return Config(
        rr=st.session_state.rr_ratio,
        risk_pct=st.session_state.risk_pct,
        max_position_pct=20.0,
        min_dollar_volume=10_000_000,
        min_price=5.0,
        max_atr_pct=8.0,
        min_score=st.session_state.min_score,
        fee_bps=5.0,
        slip_bps=5.0,
    )


# -----------------------------------------------------------------------------
# 4. 股票池（保留 Quantum 1 preset，同时补一个更宽的跨行业池）
# -----------------------------------------------------------------------------
INDEX_PRESET_POOLS = {
    "🔥 精选核心科技 (15只)": ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN", "SMCI"],
    "💻 半导体与芯片产业链": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "MU", "TXN", "AMAT", "LRCX", "ADI", "KLAC", "ARM", "MRVL"],
    "🏥 医疗生物与医药巨头": ["LLY", "NVO", "PFE", "JNJ", "UNH", "ABBV", "MRK", "AMGN", "GILD", "BMY", "CVS", "ISRG", "TMO", "DHR"],
    "🚀 科技七巨头 & AI": ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "PLTR", "ORCL", "IBM", "AMD", "NOW"],
    "🌐 核心ETF与资产类别": ["SPY", "QQQ", "IWM", "SOXX", "XLV", "XLF", "XLE", "ARKK", "TLT", "GLD"],
    "📦 Quantum 2 跨行业核心池": [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","ORCL","AMD","INTC","TSM","ASML","MU","QCOM",
        "AMAT","LRCX","KLAC","ARM","MRVL","TXN","ADI","PLTR","CRM","NOW","ADBE","IBM","CSCO","PANW","CRWD",
        "SNOW","DDOG","NET","SHOP","UBER","ABNB","NFLX","DIS","SPOT","PYPL","COIN","HOOD","JPM","BAC","WFC",
        "GS","MS","V","MA","AXP","BRK-B","BLK","SCHW","XOM","CVX","COP","SLB","CAT","DE","GE","HON","RTX",
        "LMT","NOC","BA","UPS","UNP","FDX","WM","COST","WMT","HD","LOW","PG","KO","PEP","MCD","SBUX","NKE",
        "LLY","JNJ","UNH","ABBV","MRK","TMO","DHR","ISRG","AMGN","GILD","NVO","ABT","MDT","BMY","NEE","DUK",
        "SO","PLD","AMT","EQIX","SPG","O","LIN","FCX","NEM","APD","SPY","QQQ","IWM","DIA","SOXX","XLK","XLV","XLF","XLE","XLI","XLP","XLU","TLT","GLD"
    ],
    "📊 标普 500 动态池": "SP500_AUTO",
}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_sp500_tickers():
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        frame = tables[0]
        return frame["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    except Exception:
        return ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "TSLA", "LLY"]


def parse_symbols(text):
    items = re.split(r"[,，;；\s]+", str(text).strip().upper())
    out = []
    for symbol in items:
        symbol = symbol.replace(".", "-").strip()
        if symbol and not re.fullmatch(r"[A-Z][A-Z0-9-]{0,14}", symbol):
            raise ValueError(f"无效代码：{symbol}")
        if symbol and symbol not in out:
            out.append(symbol)
    return out


# -----------------------------------------------------------------------------
# 5. SQLite 自选清单（保留 Quantum 1）
# -----------------------------------------------------------------------------
DB_FILE = "quant_terminal_watch.db"


def init_quant_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            added_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def add_to_watchlist(symbol, name="", category="推荐自选"):
    symbol = parse_symbols(symbol)
    if len(symbol) != 1:
        raise ValueError("请输入一个有效美国股票代码")
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)",
        (symbol[0], name or symbol[0], category, datetime.now().strftime("%Y-%m-%d")),
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
# 6. 行情抓取：沿用 Quantum 1 yfinance，不新增依赖
# -----------------------------------------------------------------------------
@st.cache_data(ttl=21600, show_spinner=False)
def fetch_history(symbol: str, period: str = "3y"):
    symbol = symbol.upper().strip()
    frame = yf.Ticker(symbol).history(
        period=period,
        interval="1d",
        auto_adjust=True,
        actions=False,
    )
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
    valid = (frame[["Open", "High", "Low", "Close"]] > 0).all(axis=1) & (frame.Volume >= 0)
    valid &= frame.High >= frame[["Open", "Close", "Low"]].max(axis=1)
    valid &= frame.Low <= frame[["Open", "Close", "High"]].min(axis=1)
    frame = frame.loc[valid]
    return frame if len(frame) >= 35 else None


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_histories(symbols_tuple, period="3y"):
    """批量抓取：扫描时复用同一批请求；失败标记由调用端显示。"""
    symbols = tuple(dict.fromkeys(symbols_tuple))
    out, errors = {}, []
    for symbol in symbols:
        try:
            frame = fetch_history(symbol, period=period)
            if frame is None or frame.empty:
                errors.append({"代码": symbol, "错误": "无有效日线数据 / 数据源限流"})
            else:
                out[symbol] = frame
        except Exception as exc:
            errors.append({"代码": symbol, "错误": str(exc)})
    return out, errors


# -----------------------------------------------------------------------------
# 7. Quantum 2 指标：clean + Wilder + Supertrend + 六维评分
# -----------------------------------------------------------------------------
def clean(frame):
    d = frame.copy()
    d.index = pd.DatetimeIndex(d.index)
    try:
        d.index = d.index.tz_localize(None)
    except Exception:
        pass
    d.index = d.index.normalize()
    d = d.loc[~d.index.duplicated(keep="last")].sort_index()
    fields = ["Open", "High", "Low", "Close", "Volume"]
    d = d[fields].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    valid = (d[fields[:4]] > 0).all(axis=1) & (d.Volume >= 0)
    valid &= (d.High >= d[["Open", "Close", "Low"]].max(axis=1))
    valid &= (d.Low <= d[["Open", "Close", "High"]].min(axis=1))
    return d.loc[valid]


def wilder(series, n=14):
    values = series.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    for i in range(n - 1, len(values)):
        if i == 0 or np.isnan(output[i - 1]):
            window = values[i - n + 1:i + 1]
            if np.isfinite(window).all():
                output[i] = window.mean()
        elif np.isfinite(values[i]):
            output[i] = (output[i - 1] * (n - 1) + values[i]) / n
    return pd.Series(output, index=series.index)


def indicators(frame, benchmark=None):
    d = clean(frame)
    c, h, l, v = d.Close, d.High, d.Low, d.Volume

    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    d["TR"] = tr
    d["ATR"] = wilder(tr, 14)

    for n in (20, 50, 200):
        d[f"MA{n}"] = c.rolling(n).mean()
    d["EMA20"] = c.ewm(span=20, adjust=False).mean()

    # Wilder RSI：保留 Quantum 2 的 SMA seed，而不是单点初始化。
    delta = c.diff()
    gain = wilder(delta.clip(lower=0), 14)
    loss = wilder(-delta.clip(upper=0), 14)
    rs = gain / loss.replace(0, np.nan)
    d["RSI"] = 100 - 100 / (1 + rs)
    d.loc[(loss == 0) & (gain > 0), "RSI"] = 100
    d.loc[(gain == 0) & (loss > 0), "RSI"] = 0
    d.loc[(gain == 0) & (loss == 0), "RSI"] = 50

    # MACD：金叉与多头状态分开。
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACDSignal"] = d.MACD.ewm(span=9, adjust=False).mean()
    d["Hist"] = d.MACD - d.MACDSignal
    d["CrossUp"] = (d.MACD > d.MACDSignal) & (d.MACD.shift() <= d.MACDSignal.shift())
    d["CrossDown"] = (d.MACD < d.MACDSignal) & (d.MACD.shift() >= d.MACDSignal.shift())

    # 20 日成交量加权典型价格：不再把累计历史价格错误称为日内 VWAP。
    typical = (h + l + c) / 3
    d["VWMA20"] = (typical * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    d["Upper"] = d.MA20 + 2 * c.rolling(20).std()
    d["Lower"] = d.MA20 - 2 * c.rolling(20).std()
    d["DollarVolume"] = (c * v).rolling(20).mean()
    d["RelVolume"] = v / v.shift().rolling(20).mean().replace(0, np.nan)
    d["ATRpct"] = d.ATR / c * 100
    d["Support"] = l.rolling(20).min()
    d["Resistance"] = h.shift().rolling(20).max()
    d["Return63"] = c.pct_change(63, fill_method=None)

    # Benchmark / SPY。
    if benchmark is not None and not benchmark.empty:
        b = clean(benchmark).Close.reindex(d.index)
        d["Relative63"] = d.Return63 - b.pct_change(63, fill_method=None)
        d["MarketMA200"] = b.rolling(200).mean()
        d["MarketOK"] = b > d.MarketMA200
        d["MarketKnown"] = b.rolling(200).count().eq(200)
        d["BenchmarkClose"] = b
    else:
        d["Relative63"] = np.nan
        d["MarketMA200"] = np.nan
        d["MarketOK"] = False
        d["MarketKnown"] = False
        d["BenchmarkClose"] = np.nan

    # Quantum 2 Supertrend：有效 ATR seed + final band + persistent direction state。
    at10 = wilder(tr, 10).to_numpy()
    ub = ((h + l) / 2).to_numpy() + 3 * at10
    lb = ((h + l) / 2).to_numpy() - 3 * at10
    fu = ub.copy()
    fl = lb.copy()
    direction = np.zeros(len(d), dtype=int)
    line = np.full(len(d), np.nan)
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
        line[i] = fl[i] if direction[i] == 1 else fu[i]

    d["STDirection"] = direction
    d["Supertrend"] = line

    # 六维固定评分：30 + 20 + 20 + 10 + 10 + 10 = 100。
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
    d["LiquidityScore"] = np.select(
        [d.DollarVolume >= 50e6, d.DollarVolume >= 10e6],
        [10, 5],
        default=0,
    )
    d["VolatilityScore"] = np.select(
        [d.ATRpct.between(1, 4), d.ATRpct.between(0.3, 6)],
        [10, 5],
        default=0,
    )
    d["MarketScore"] = d.MarketOK.astype(int) * 10
    score_cols = [
        "TrendScore", "StrengthScore", "MomentumScore",
        "LiquidityScore", "VolatilityScore", "MarketScore"
    ]
    d["Score"] = d[score_cols].sum(axis=1).astype(int)

    return d


# -----------------------------------------------------------------------------
# 8. Quantum 2 交易计划：参考买点 / 结构止损 / RR 目标 / Eligibility
# -----------------------------------------------------------------------------
def plan(row, cfg=None):
    cfg = cfg or Config()
    required = ["Close", "ATR", "MA200", "Support", "EMA20", "RSI"]
    if any(k not in row or not np.isfinite(row[k]) for k in required) or row.ATR <= 0:
        return None

    entry = min(float(row.Close), float(row.EMA20))
    stop = min(entry - 1.5 * row.ATR, row.Support - 0.25 * row.ATR)
    risk = entry - stop
    target = entry + cfg.rr * risk

    reasons = []
    if row.Close < cfg.min_price:
        reasons.append("价格低于门槛")
    if row.DollarVolume < cfg.min_dollar_volume:
        reasons.append("20日平均成交额不足")
    if row.ATRpct > cfg.max_atr_pct:
        reasons.append("波动率过高")
    if not row.MarketKnown:
        reasons.append("SPY 200日数据不足")
    elif not row.MarketOK:
        reasons.append("SPY 低于200日均线")
    if not (row.Close > row.MA50 > row.MA200):
        reasons.append("长期趋势未确认")
    if row.Score < cfg.min_score:
        reasons.append("综合评分不足")
    if row.RSI > 75:
        reasons.append("RSI过热")
    if risk > 4 * row.ATR:
        reasons.append("结构止损距离过大")
    if stop <= 0:
        reasons.append("止损无效")
    if entry < row.Close - 2 * row.ATR:
        reasons.append("回踩区距离过远")

    entry_low = max(stop + 0.1 * risk, entry - 0.25 * row.ATR)
    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "entry_low": entry_low,
        "eligible": not reasons,
        "reasons": reasons,
        "score": int(row.Score),
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
        raise ValueError("至少需要 210 个有效交易日")
    row = d.iloc[-1]
    p = plan(row, cfg)
    if p is None:
        raise ValueError("指标无效或 ATR 为零")
    return {
        "代码": symbol,
        "评分": p["score"],
        "状态": "候选 · 等待回踩" if p["eligible"] else "观察 · 暂不入选",
        "收盘价": float(row.Close),
        "买入参考": p["entry"],
        "止损": p["stop"],
        "目标": p["target"],
        "RSI": float(row.RSI),
        "ATR%": float(row.ATRpct),
        "20日成交额": float(row.DollarVolume),
        "相对SPY63日%": float(row.Relative63 * 100) if np.isfinite(row.Relative63) else None,
        "行情日期": d.index[-1].strftime("%Y-%m-%d"),
        "原因": "；".join(p["reasons"]) or "满足筛选条件",
        "TrendScore": int(row.TrendScore),
        "StrengthScore": int(row.StrengthScore),
        "MomentumScore": int(row.MomentumScore),
        "LiquidityScore": int(row.LiquidityScore),
        "VolatilityScore": int(row.VolatilityScore),
        "MarketScore": int(row.MarketScore),
        "Trend": "多头" if row.Close > row.MA50 > row.MA200 else "未确认",
        "Supertrend": "多头" if row.STDirection == 1 else "空头",
        "MACD": "当日金叉" if row.CrossUp else "当日死叉" if row.CrossDown else "多头状态" if row.Hist > 0 else "空头状态",
    }


# -----------------------------------------------------------------------------
# 9. Quantum 2 时间顺序回测：前一日信号 -> 次日限价入场 -> 次日生效移动止损
# -----------------------------------------------------------------------------
def simulate(d, cfg=None, initial=10000.0, start=None):
    cfg = cfg or Config()
    if initial <= 0:
        raise ValueError("初始资金必须大于 0")
    if len(d) < 212:
        raise ValueError("历史不足；需要至少 212 个有效交易日")

    if start is None:
        start_i = 210
    else:
        start_i = max(210, int(d.index.searchsorted(pd.Timestamp(start))))
    if start_i >= len(d):
        raise ValueError("所选区间没有有效交易日")

    fee = cfg.fee_bps / 1e4
    slip = cfg.slip_bps / 1e4
    cash = float(initial)
    pos = 0
    entry = 0.0
    stop = 0.0
    target = 0.0
    basis = 0.0
    trades = []
    curve = [{"Date": d.index[start_i - 1], "Equity": cash, "Benchmark": initial}]
    benchmark_entry = float(d.Open.iloc[start_i])

    for i in range(start_i, len(d)):
        row = d.iloc[i]
        prev = d.iloc[i - 1]
        date = d.index[i]
        exited = False
        entered_intraday = False

        def sell(price, reason):
            nonlocal cash, pos
            if pos <= 0:
                return
            proceeds = pos * price * (1 - fee)
            cash += proceeds
            trades.append({
                "日期": date,
                "操作": "卖出",
                "原因": reason,
                "价格": price,
                "股数": pos,
                "费用": pos * price * fee,
                "净盈亏": proceeds - basis,
            })
            pos = 0

        if pos:
            if row.Open <= stop:
                sell(float(row.Open) * (1 - slip), "跳空止损")
                exited = True
            elif prev.Close < prev.MA50 or not prev.MarketOK:
                sell(float(row.Open) * (1 - slip), "次日开盘趋势退出")
                exited = True
            elif row.Open >= target:
                sell(float(target), "目标限价（不计有利跳空）")
                exited = True

        if not pos and not exited:
            p = plan(prev, cfg)
            if p and p["eligible"] and row.Low <= p["entry"]:
                if row.Open > p["stop"]:
                    fill = min(float(row.Open), p["entry"]) if row.Open <= p["entry"] else p["entry"]
                    q = quantity(cash, fill, p["stop"], cfg)
                    if q:
                        pos = q
                        entry = fill
                        stop = p["stop"]
                        target = entry + cfg.rr * (entry - stop)
                        basis = pos * entry * (1 + fee)
                        cash -= basis
                        entered_intraday = row.Open > p["entry"]
                        trades.append({
                            "日期": date,
                            "操作": "买入",
                            "原因": "前一日信号／次日回踩限价",
                            "价格": entry,
                            "股数": pos,
                            "费用": pos * entry * fee,
                            "净盈亏": None,
                        })

        if pos:
            # OHLC 无法知道盘中顺序；双触发保守地优先止损。
            if row.Low <= stop:
                sell(float(stop) * (1 - slip), "止损（同日双触发优先止损）")
            elif not entered_intraday and row.High >= target:
                sell(float(target), "止盈限价")
            if pos:
                # 移动止损只在下一交易日生效，不回溯当日。
                stop = max(stop, float(row.High - 2 * row.ATR))

        curve.append({
            "Date": date,
            "Equity": cash + pos * row.Close,
            "Benchmark": initial * row.Close / benchmark_entry,
        })

    eq = pd.DataFrame(curve).set_index("Date")
    ledger = pd.DataFrame(trades)
    sells = [t["净盈亏"] for t in trades if t["操作"] == "卖出"]
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
        "胜率%": sum(p > 0 for p in sells) / len(sells) * 100 if sells else None,
        "盈亏金额比": gains / losses if losses else None,
        "未平仓股数": pos,
        "未实现盈亏": pos * float(d.Close.iloc[-1]) - basis if pos else 0.0,
        "总交易笔数": len(trades),
    }
    return metrics, eq, ledger


# -----------------------------------------------------------------------------
# 10. UI 数据转换 + 专业图表
# -----------------------------------------------------------------------------
def recommendation(score, eligible):
    if not eligible:
        return "❄️ 观察 / 防守"
    if score >= 85:
        return "🔥 A+ 强候选"
    if score >= 75:
        return "🟢 A 重点候选"
    if score >= 65:
        return "🟡 B 条件候选"
    return "⚪ 未入选"


def signal_distance(row, plan_data):
    if not plan_data:
        return np.nan
    return (float(row.Close) - plan_data["entry"]) / float(row.Close) * 100


def make_signal(symbol, frame, cfg, benchmark):
    d = indicators(frame, benchmark)
    summary = build_summary(symbol, d, cfg)
    p = plan(d.iloc[-1], cfg)
    return {
        "symbol": symbol,
        "name": symbol,
        "df": d,
        "summary": summary,
        "plan": p,
        "current_price": float(d.Close.iloc[-1]),
        "change_pct": float(d.Close.pct_change().iloc[-1] * 100),
        "quant_score": int(summary["评分"]),
        "eligible": bool(p["eligible"]),
        "recommendation": recommendation(summary["评分"], p["eligible"]),
        "rsi": float(d.RSI.iloc[-1]),
        "atr_pct": float(d.ATRpct.iloc[-1]),
        "relative63": float(d.Relative63.iloc[-1] * 100) if np.isfinite(d.Relative63.iloc[-1]) else np.nan,
        "macd_status": summary["MACD"],
        "supertrend_signal": summary["Supertrend"],
        "trend_label": "🔥 长期多头确认" if summary["Trend"] == "多头" else "⚠️ 长期趋势未确认",
    }


def render_professional_chart(sig_data, days=90):
    d = sig_data["df"].tail(days)
    p = sig_data["plan"]
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.62, 0.18, 0.20],
        subplot_titles=(
            f"📈 {sig_data['symbol']} · 价格 / 趋势 / 交易计划",
            "📊 MACD 动能",
            "⚡ RSI + 动量",
        ),
    )

    fig.add_trace(
        go.Candlestick(
            x=d.index,
            open=d.Open,
            high=d.High,
            low=d.Low,
            close=d.Close,
            name="复权日K",
            increasing_line_color="#00ff66",
            decreasing_line_color="#ff3366",
        ),
        row=1,
        col=1,
    )
    for col, label, color, width in [
        ("EMA20", "EMA20", "#00f0ff", 1.4),
        ("MA50", "MA50", "#ffaa00", 1.2),
        ("MA200", "MA200", "#b87cff", 1.2),
        ("Supertrend", "Supertrend", "#ffffff", 1.1),
    ]:
        fig.add_trace(
            go.Scatter(x=d.index, y=d[col], name=label, line=dict(color=color, width=width)),
            row=1,
            col=1,
        )

    if p:
        for key, label, color in [
            ("entry", "⚡ 买入参考", "#ccff00"),
            ("entry_low", "回踩区下沿", "#888888"),
            ("stop", "🛡 止损", "#ff3366"),
            ("target", f"🎯 {sig_data['summary']['评分']}分 / {cfg_from_session().rr:.1f}R 目标", "#00f0ff"),
        ]:
            fig.add_hline(
                y=p[key],
                line_dash="dash",
                line_color=color,
                annotation_text=label,
                row=1,
                col=1,
                opacity=0.85,
            )

    hist_colors = ["#00ff66" if x >= 0 else "#ff3366" for x in d.Hist.fillna(0)]
    fig.add_trace(go.Bar(x=d.index, y=d.Hist, marker_color=hist_colors, name="MACD Hist"), row=2, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACD, line=dict(color="#00f0ff", width=1), name="DIF"), row=2, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACDSignal, line=dict(color="#ffaa00", width=1), name="DEA"), row=2, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, line=dict(color="#b87cff", width=1.5), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", opacity=0.75, row=3, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="#6e7681", opacity=0.6, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", opacity=0.75, row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0b0e14",
        plot_bgcolor="#161b22",
        height=650,
        showlegend=False,
        margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#21262d", rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridcolor="#21262d")
    return fig


def score_panel(summary):
    items = [
        ("趋势", summary["TrendScore"], 30),
        ("相对 SPY", summary["StrengthScore"], 20),
        ("动量", summary["MomentumScore"], 20),
        ("流动性", summary["LiquidityScore"], 10),
        ("波动率", summary["VolatilityScore"], 10),
        ("大盘环境", summary["MarketScore"], 10),
    ]
    body = []
    for label, score, maximum in items:
        width = 0 if maximum == 0 else max(0, min(100, score / maximum * 100))
        body.append(
            f"<div class='score-row'>"
            f"<div class='score-label'>{html.escape(label)}</div>"
            f"<div class='score-bar'><div class='score-fill' style='width:{width:.0f}%'></div></div>"
            f"<div class='score-number'>{score}/{maximum}</div>"
            f"</div>"
        )
    return "<div class='score-panel'>" + "".join(body) + "</div>"


def metric_card(title, value, css_class=""):
    return (
        f"<div class='tech-card'>"
        f"<div class='metric-title'>{html.escape(title)}</div>"
        f"<div class='metric-value {css_class}'>{html.escape(str(value))}</div>"
        f"</div>"
    )


def results_table(results):
    rows = []
    for r in results:
        p = r["plan"]
        s = r["summary"]
        rows.append(
            {
                "代码": r["symbol"],
                "评分": r["quant_score"],
                "评级": r["recommendation"],
                "状态": s["状态"],
                "收盘": r["current_price"],
                "买入参考": p["entry"],
                "止损": p["stop"],
                "目标": p["target"],
                "RSI": r["rsi"],
                "ATR%": r["atr_pct"],
                "相对SPY63%": r["relative63"],
                "原因": s["原因"],
            }
        )
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# 11. 页面顶部 + Sidebar：外壳维持 Quantum 1
# -----------------------------------------------------------------------------
st.markdown('<h3 class="tech-header">⚡ QUANTUM TERMINAL PRO</h3>', unsafe_allow_html=True)
st.markdown(
    '<div class="tech-subtitle">Quantum 1 UI · Quantum 2 Quant Engine · Daily US Market Research</div>',
    unsafe_allow_html=True,
)


def on_nav_change():
    st.session_state.current_page = st.session_state.nav_radio_choice


with st.sidebar:
    st.markdown("### 🎛️ 终端控制台")
    current_idx = NAV_OPTIONS.index(st.session_state.current_page)
    st.radio(
        "导航菜单",
        NAV_OPTIONS,
        index=current_idx,
        key="nav_radio_choice",
        on_change=on_nav_change,
        label_visibility="collapsed",
    )
    st.markdown("---")
    with st.form("global_setting_form"):
        st.markdown("#### ⚙️ 策略风控")
        new_rr = st.slider("目标盈亏比", 1.0, 5.0, float(st.session_state.rr_ratio), 0.5)
        new_risk = st.slider("单笔风险 %", 0.1, 5.0, float(st.session_state.risk_pct), 0.1)
        new_min_score = st.slider("最低评分", 0, 100, int(st.session_state.min_score), 5)
        new_capital = st.number_input("账户资金 ($)", min_value=100.0, value=float(st.session_state.capital), step=1000.0)
        form_submitted = st.form_submit_button("保存配置", use_container_width=True)
        if form_submitted:
            st.session_state.rr_ratio = new_rr
            st.session_state.risk_pct = new_risk
            st.session_state.min_score = new_min_score
            st.session_state.capital = new_capital
            st.rerun()

cfg = cfg_from_session()
app_mode = st.session_state.current_page


# -----------------------------------------------------------------------------
# 12. 页面 1：自动扫描 & 智能推荐
# -----------------------------------------------------------------------------
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 量化自动扫描与推荐")
    st.caption(
        "评分不是胜率。现在的筛选优先回答三件事：趋势有没有确认？相对大盘强不强？当前价格离合理风险位置有多远？"
    )

    c_preset, c_custom, c_btn = st.columns([2.5, 3.5, 1.5])
    with c_preset:
        selected_preset = st.selectbox("📦 选择扫描预设池", list(INDEX_PRESET_POOLS.keys()))
    selected_pool = INDEX_PRESET_POOLS[selected_preset]
    if selected_pool == "SP500_AUTO":
        default_pool = fetch_sp500_tickers()
    else:
        default_pool = selected_pool

    with c_custom:
        custom_pool_str = st.text_input("待扫描代码（逗号分隔）", value=", ".join(default_pool))
    with c_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动扫描", use_container_width=True)

    try:
        symbols_to_scan = parse_symbols(custom_pool_str)
    except ValueError as exc:
        symbols_to_scan = []
        st.error(str(exc))

    if run_scan:
        if not symbols_to_scan:
            st.warning("股票池为空，请先输入代码。")
        else:
            progress = st.progress(0, text="准备量化引擎…")
            benchmark = fetch_history("SPY", period="3y")
            if benchmark is None:
                st.error("SPY 基准下载失败，本次扫描取消，因为相对强度与市场评分无法可靠计算。")
            else:
                # 并发 4 个单标的任务，保留 Q1 的 UI，同时不在扫描中请求 info/news。
                results = []
                errors = []
                total = len(symbols_to_scan)
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future_map = {
                        executor.submit(fetch_history, symbol, "3y"): symbol
                        for symbol in symbols_to_scan
                    }
                    done_count = 0
                    for future in as_completed(future_map):
                        symbol = future_map[future]
                        done_count += 1
                        try:
                            frame = future.result()
                            if frame is None:
                                raise ValueError("没有有效日线数据")
                            signal = make_signal(symbol, frame, cfg, benchmark)
                            results.append(signal)
                        except Exception as exc:
                            errors.append({"代码": symbol, "错误": str(exc)})
                        progress.progress(done_count / total, text=f"量化处理中：{done_count}/{total}")
                progress.empty()
                results.sort(key=lambda x: (x["eligible"], x["quant_score"]), reverse=True)
                st.session_state.scan_results = results
                st.session_state.scan_errors = errors
                st.session_state.scan_source = selected_preset
                st.session_state.scan_date = results[0]["summary"]["行情日期"] if results else "—"

    results = st.session_state.get("scan_results", [])
    errors = st.session_state.get("scan_errors", [])

    if results:
        eligible_results = [r for r in results if r["eligible"]]
        st.markdown(
            f"<div class='signal-strip'><b>扫描完成</b> · {len(results)} 个有效结果 · "
            f"{len(eligible_results)} 个符合候选条件 · 数据日期 {st.session_state.get('scan_date','—')}</div>",
            unsafe_allow_html=True,
        )

        # 最上层只展示“真正候选”，避免把高分但未过硬过滤的标的误当成推荐。
        leaders = eligible_results[:3] if eligible_results else results[:3]
        st.markdown("#### 🔥 Top 3：真正值得进一步看的标的")
        top_cols = st.columns(min(3, len(leaders)))
        for i, col in enumerate(top_cols):
            res = leaders[i]
            p = res["plan"]
            with col:
                status_class = "metric-good" if res["eligible"] else "metric-warn"
                st.markdown(
                    f"""
                    <div class='tech-card'>
                      <div style='font-size:10px;color:#00f0ff;font-weight:800;'>TOP {i+1}</div>
                      <div style='font-size:20px;color:#fff;font-weight:800;'>{res['symbol']}</div>
                      <div style='font-size:17px;font-weight:800;' class='{status_class}'>
                        {res['quant_score']} / 100
                      </div>
                      <div style='font-size:11px;color:#8b949e;margin-top:3px;'>{html.escape(res['recommendation'])}</div>
                      <hr style='border-color:#30363d;margin:7px 0;'>
                      <div style='font-size:11px;color:#8b949e;'>收盘 <b style='color:#fff;'>${res['current_price']:.2f}</b></div>
                      <div style='font-size:11px;color:#ccff00;'>⚡ 买入参考 <b>${p['entry']:.2f}</b></div>
                      <div style='font-size:11px;color:#ff3366;'>🛡 止损 <b>${p['stop']:.2f}</b></div>
                      <div style='font-size:11px;color:#00f0ff;'>🎯 目标 <b>${p['target']:.2f}</b></div>
                      <div style='font-size:10px;color:#8b949e;margin-top:7px;'>RSI {res['rsi']:.1f} · 相对SPY63日 {res['relative63']:.1f}%</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(f"🔍 诊断 {res['symbol']}", key=f"scan_detail_{res['symbol']}"):
                    st.session_state.selected_ticker = res["symbol"]
                    st.session_state.current_page = "🔍 单标的全量诊断"
                    st.rerun()

        st.markdown("#### 📊 全量矩阵：直接看出差异")
        df_result = results_table(results)
        only = st.checkbox("只显示符合候选条件", value=True, key="scan_only_eligible")
        display_df = df_result[df_result["状态"].str.startswith("候选")] if only else df_result
        limit = st.selectbox("手机显示条数", [20, 50, 100], index=0, key="scan_display_limit")
        if display_df.empty:
            st.info("当前没有满足全部硬过滤条件的候选；系统不会为了凑 Top 3 强行推荐。")
        else:
            st.dataframe(
                display_df[["代码", "评分", "评级", "收盘", "买入参考", "止损", "目标", "RSI", "ATR%", "相对SPY63%", "原因"]]
                .head(limit)
                .round(2),
                use_container_width=True,
                hide_index=True,
            )
            selected = st.selectbox("选择一只进入完整诊断", display_df["代码"].tolist(), key="scan_select_symbol")
            if st.button("打开完整诊断", key="scan_open_detail", use_container_width=True):
                st.session_state.selected_ticker = selected
                st.session_state.current_page = "🔍 单标的全量诊断"
                st.rerun()

        csv = df_result.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 下载完整扫描 CSV", csv, "quantum_scan.csv", "text/csv")

        if errors:
            with st.expander(f"⚠️ 未纳入结果的代码（{len(errors)}）"):
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# 13. 页面 2：单标的全量诊断
# -----------------------------------------------------------------------------
elif app_mode == "🔍 单标的全量诊断":
    st.markdown("### 🔍 标的量化诊断")
    st.caption("这里是 Quantum 2 数学模型完整展开：100 分评分 → 硬过滤 → 交易计划 → 仓位风险。")

    with st.form("symbol_search_form"):
        c_in, c_b = st.columns([3, 1])
        with c_in:
            target_symbol = st.text_input(
                "股票代码",
                value=st.session_state.get("selected_ticker", "NVDA"),
            ).upper().strip()
        with c_b:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            search_submitted = st.form_submit_button("⚡ 诊断", use_container_width=True)
    if search_submitted:
        try:
            parsed = parse_symbols(target_symbol)
            if len(parsed) != 1:
                raise ValueError("请输入一个股票代码")
            st.session_state.selected_ticker = parsed[0]
        except ValueError as exc:
            st.error(str(exc))

    target_symbol = st.session_state.selected_ticker
    if target_symbol:
        with st.spinner(f"正在分析 {target_symbol}…"):
            frame = fetch_history(target_symbol, period="3y")
            benchmark = fetch_history("SPY", period="3y")

        if frame is None or benchmark is None:
            st.error("行情不足或数据源暂时不可用。")
        else:
            try:
                sig = make_signal(target_symbol, frame, cfg, benchmark)
                d = sig["df"]
                p = sig["plan"]
                summary = sig["summary"]

                status_css = "metric-good" if sig["eligible"] else "metric-warn"
                st.markdown(
                    f"<div class='signal-strip'><b>{sig['symbol']}</b> · {html.escape(sig['trend_label'])} · "
                    f"得分 <b class='{status_css}'>{sig['quant_score']} / 100</b> · {html.escape(sig['recommendation'])} · "
                    f"数据日期 {summary['行情日期']}</div>",
                    unsafe_allow_html=True,
                )

                # 第一屏先给用户真正想知道的四个数。
                cards_html = (
                    metric_card("当前收盘价", f"${sig['current_price']:.2f}")
                    + metric_card("⚡ 回踩买入参考", f"${p['entry']:.2f}", "metric-buy")
                    + metric_card("🛡 初始结构止损", f"${p['stop']:.2f}", "metric-stop")
                    + metric_card("🎯 目标价", f"${p['target']:.2f}", "metric-take")
                )
                st.markdown(
                    f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{cards_html}</div>",
                    unsafe_allow_html=True,
                )

                # 第二层：距离和 R/R。
                upside = (p["target"] / sig["current_price"] - 1) * 100
                downside = (p["stop"] / sig["current_price"] - 1) * 100
                entry_gap = (sig["current_price"] - p["entry"]) / sig["current_price"] * 100
                st.markdown(
                    f"""
                    <div class='decision-box'>
                      <b>🎯 现在最值得看的答案</b><br>
                      <span style='color:#8b949e;font-size:11px;'>
                      现价距离回踩参考：<b style='color:#ccff00'>{entry_gap:+.2f}%</b> ·
                      止损空间：<b style='color:#ff3366'>{downside:.2f}%</b> ·
                      目标空间：<b style='color:#00f0ff'>{upside:+.2f}%</b> ·
                      设定 RR：<b style='color:#fff'>{cfg.rr:.1f}R</b>
                      </span><br>
                      <span style='color:#6e7681;font-size:10px;'>
                      回踩观察区：${p['entry_low']:.2f} – ${p['entry']:.2f}。参考价是规则计算值，不代表必然成交。
                      </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if sig["eligible"]:
                    st.success("✅ 当前满足趋势、大盘、流动性、波动率、评分等硬过滤条件，可以进入候选池。")
                else:
                    st.warning("⚠️ 当前未满足全部硬过滤条件，因此即使评分不错，也只显示为观察状态。")
                    st.caption("未通过原因：" + summary["原因"])

                # Score breakdown：比 Quantum 1 单纯显示一个数字更容易看出“为什么”。
                left, right = st.columns([1.2, 1])
                with left:
                    st.markdown("#### 🧠 100 分评分拆解")
                    st.markdown(score_panel(summary), unsafe_allow_html=True)
                    st.caption("固定规则：趋势30 + 相对SPY20 + 动量20 + 流动性10 + 波动率10 + 大盘10。评分不是概率。")
                with right:
                    st.markdown("#### 📡 市场状态")
                    mini = [
                        ("趋势", summary["Trend"]),
                        ("Supertrend", summary["Supertrend"]),
                        ("MACD", summary["MACD"]),
                        ("RSI", f"{sig['rsi']:.1f}"),
                        ("ATR", f"{sig['atr_pct']:.1f}%"),
                        ("相对 SPY 63日", "—" if not np.isfinite(sig['relative63']) else f"{sig['relative63']:+.1f}%"),
                    ]
                    for k, v in mini:
                        st.markdown(
                            f"<div class='tech-card'><span class='metric-title'>{k}</span><div class='metric-value'>{html.escape(v)}</div></div>",
                            unsafe_allow_html=True,
                        )

                st.markdown("#### 📈 价格结构 + 交易计划")
                days = st.select_slider("图表周期", [45, 90, 180], value=90, key="detail_chart_days")
                st.plotly_chart(render_professional_chart(sig, days), use_container_width=True, config={"displayModeBar": False})

                st.markdown("#### 💰 仓位风险估算")
                q = quantity(st.session_state.capital, p["entry"], p["stop"], cfg) if sig["eligible"] else 0
                risk_budget = st.session_state.capital * cfg.risk_pct / 100
                position_value = q * p["entry"]
                pc1, pc2, pc3, pc4 = st.columns(4)
                with pc1: st.metric("风险预算", f"${risk_budget:,.2f}")
                with pc2: st.metric("建议最大股数", f"{q:,}")
                with pc3: st.metric("计划投入", f"${position_value:,.2f}")
                with pc4: st.metric("占账户", f"{position_value / st.session_state.capital * 100:.1f}%")
                st.caption("仓位同时受账户风险预算与单只持仓上限约束；实际跳空可能令损失超过计划风险。")

                if st.button("➕ 加入自选清单", use_container_width=True):
                    add_to_watchlist(sig["symbol"], sig["symbol"], "推荐自选")
                    st.success("已成功保存到自选。")
            except Exception as exc:
                st.error(f"诊断失败：{exc}")


# -----------------------------------------------------------------------------
# 14. 页面 3：策略历史回测引擎
# -----------------------------------------------------------------------------
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 策略历史回测引擎")
    st.caption("与 Quantum 2 一样：前一日信号 → 次日回踩限价 → 止损/止盈 → 移动止损次日生效。")

    with st.form("backtest_form"):
        c_sym, c_cap, c_start, c_btn = st.columns([1.5, 1.5, 1.8, 1.2])
        with c_sym:
            bt_symbol = st.text_input("回测代码", value=st.session_state.get("selected_ticker", "NVDA")).upper().strip()
        with c_cap:
            init_capital = st.number_input("初始资金 ($)", min_value=100.0, value=float(st.session_state.capital), step=1000.0)
        with c_start:
            start_date = st.date_input("开始日期", value=(pd.Timestamp.now() - pd.DateOffset(years=2)).date())
        with c_btn:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            run_bt = st.form_submit_button("🚀 回测", use_container_width=True)

    if run_bt:
        try:
            parsed = parse_symbols(bt_symbol)
            if len(parsed) != 1:
                raise ValueError("请输入一个股票代码")
            bt_symbol = parsed[0]
            with st.spinner(f"正在回测 {bt_symbol}…"):
                frame = fetch_history(bt_symbol, period="5y")
                benchmark = fetch_history("SPY", period="5y")
                if frame is None or benchmark is None:
                    raise ValueError("股票或 SPY 数据不足")
                d = indicators(frame, benchmark)
                metrics, equity_df, ledger = simulate(d, cfg, initial=init_capital, start=str(start_date))
            st.session_state.bt_metrics = metrics
            st.session_state.bt_equity = equity_df
            st.session_state.bt_ledger = ledger
            st.session_state.bt_symbol = bt_symbol
            st.session_state.bt_start = str(start_date)
            st.session_state.bt_config_rr = cfg.rr
        except Exception as exc:
            st.error(f"回测失败：{exc}")

    metrics = st.session_state.get("bt_metrics")
    equity_df = st.session_state.get("bt_equity")
    ledger = st.session_state.get("bt_ledger")
    bt_symbol = st.session_state.get("bt_symbol", bt_symbol if 'bt_symbol' in locals() else "NVDA")

    if metrics and equity_df is not None:
        strategy_return = metrics["收益率%"]
        benchmark_return = metrics["买入持有%"]
        relative_alpha = strategy_return - benchmark_return
        cards_html = (
            metric_card("策略收益率", f"{strategy_return:+.2f}%", "metric-good" if strategy_return >= 0 else "metric-stop")
            + metric_card("买入持有", f"{benchmark_return:+.2f}%")
            + metric_card("相对差额", f"{relative_alpha:+.2f}%", "metric-good" if relative_alpha >= 0 else "metric-stop")
            + metric_card("最大回撤", f"{metrics['最大回撤%']:.2f}%", "metric-stop")
        )
        st.markdown(
            f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{cards_html}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("#### 📈 策略 vs 买入持有")
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=equity_df.Equity,
                name="策略净值",
                line=dict(color="#00f0ff", width=2.2),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=equity_df.Benchmark,
                name="同标的买入持有",
                line=dict(color="#777777", width=1.6, dash="dot"),
            )
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0b0e14",
            plot_bgcolor="#161b22",
            height=380,
            margin=dict(l=10, r=10, t=35, b=10),
            legend=dict(orientation="h", y=-0.18),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        b1, b2, b3, b4 = st.columns(4)
        with b1: st.metric("年化收益", f"{metrics['年化收益%']:+.2f}%")
        with b2: st.metric("胜率", "—" if metrics["胜率%"] is None else f"{metrics['胜率%']:.1f}%")
        with b3: st.metric("盈亏金额比", "—" if metrics["盈亏金额比"] is None else f"{metrics['盈亏金额比']:.2f}")
        with b4: st.metric("已平仓笔数", f"{metrics['已平仓笔数']}")

        st.markdown("#### 🧾 交易明细")
        if ledger is not None and not ledger.empty:
            st.dataframe(ledger.round(3), use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ 下载交易明细",
                ledger.to_csv(index=False).encode("utf-8-sig"),
                "quantum_trades.csv",
                "text/csv",
            )
        else:
            st.info("该区间没有形成已平仓交易。")

        st.download_button(
            "⬇️ 下载净值曲线 CSV",
            equity_df.to_csv().encode("utf-8-sig"),
            "quantum_equity.csv",
            "text/csv",
        )
        with st.expander("🧪 回测假设与限制"):
            st.write(
                "日线 OHLC 无法知道同一根 K 线内高低点先后，因此双触发时优先止损；"
                "盘中限价入场当天不假定目标价一定先触发；移动止损只在下一交易日生效。"
            )
            st.write(
                "采用复权日线近似模拟，未模拟税费、真实股息现金入账、退市、停牌和盘口容量；"
                "Yahoo 数据可能出现延迟、限流或历史调整。该回测是单标的规则验证，不是全市场组合回测。"
            )
            st.json(metrics)


# -----------------------------------------------------------------------------
# 15. 页面 4：自选清单监控
# -----------------------------------------------------------------------------
else:
    st.markdown("### 📋 自选清单监控")
    st.caption("这里继续保持 Quantum 1 的使用方式，但每一只自选股都直接显示 Quantum 2 的 100 分模型结果。")

    with st.form("watch_add_form"):
        c1, c2 = st.columns([3, 1])
        with c1:
            add_symbol = st.text_input("添加美国股票代码")
        with c2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            add_submit = st.form_submit_button("➕ 添加", use_container_width=True)
    if add_submit:
        try:
            add_to_watchlist(add_symbol)
            st.success("已加入自选。")
        except ValueError as exc:
            st.error(str(exc))

    watch_df = get_watchlist()
    if watch_df.empty:
        st.info("清单为空。先加入几只股票，就能在这里横向比较评分与风险计划。")
    else:
        watch_results = []
        progress = st.progress(0, text="刷新自选量化状态…")
        benchmark = fetch_history("SPY", period="3y")
        if benchmark is not None:
            total = len(watch_df)
            for i, row in enumerate(watch_df.itertuples(index=False), start=1):
                try:
                    frame = fetch_history(row.symbol, period="3y")
                    if frame is not None:
                        sig = make_signal(row.symbol, frame, cfg, benchmark)
                        watch_results.append(sig)
                except Exception:
                    pass
                progress.progress(i / total, text=f"更新 {i}/{total}")
        progress.empty()

        if watch_results:
            watch_results.sort(key=lambda x: (x["eligible"], x["quant_score"]), reverse=True)
            dfw = results_table(watch_results)
            st.dataframe(
                dfw[["代码", "评分", "评级", "收盘", "买入参考", "止损", "目标", "RSI", "ATR%", "相对SPY63%", "状态"]]
                .round(2),
                use_container_width=True,
                hide_index=True,
            )
            selected = st.selectbox("选择股票进入诊断", dfw["代码"].tolist(), key="watch_selected")
            if st.button("🔍 打开诊断", key="watch_open_detail", use_container_width=True):
                st.session_state.selected_ticker = selected
                st.session_state.current_page = "🔍 单标的全量诊断"
                st.rerun()

        st.markdown("#### 🛠 自选清单管理")
        remove_symbol = st.selectbox("选择要移除的代码", watch_df["symbol"].tolist())
        if st.button("移除自选", key="watch_remove"):
            remove_from_watchlist(remove_symbol)
            st.rerun()
        st.download_button(
            "⬇️ 导出自选备份",
            watch_df.to_csv(index=False).encode("utf-8-sig"),
            "quantum_watchlist.csv",
            "text/csv",
        )


# -----------------------------------------------------------------------------
# 16. 底部说明
# -----------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "QuantumSignal PRO · Quantum 1 UI + Quantum 2 Quant Engine · "
    "美国股票/ETF已收盘日线研究工具 · 评分不是胜率 · 参考买点不代表必然成交 · 非自动交易系统"
)
