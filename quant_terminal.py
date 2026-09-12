# ============================================================================
# QuantumSignal Terminal ULTRA | Bull/Bear Adaptive Quantitative System
# Version: ULTRA_4.4_PRECISION
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

VERSION = "ULTRA_4.4_PRECISION"

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
    header[data-testid="stHeader"] { 
        visibility: hidden; 
        height: 0px; 
    }
    .stApp {
        background-color: #0b0e14;
        color: #c9d1d9;
        font-family: 'Fira Code', monospace, -apple-system, BlinkMacSystemFont, sans-serif;
    }
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
    .signal-strip {
        background: linear-gradient(90deg,rgba(0,240,255,.08),rgba(112,0,255,.08));
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 10px 13px;
        margin: 8px 0 14px 0;
    }
    .diag-box {
        background: #121821;
        border: 1px solid #2d333b;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    .diag-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        margin-right: 6px;
    }
    .tag-bull { background: rgba(0,255,102,0.15); color: #00ff66; border: 1px solid #00ff66; }
    .tag-bear { background: rgba(255,51,102,0.15); color: #ff3366; border: 1px solid #ff3366; }
    .tag-neutral { background: rgba(0,240,255,0.15); color: #00f0ff; border: 1px solid #00f0ff; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# 2. Session State / 全局路由跳转
# -----------------------------------------------------------------------------
NAV_OPTIONS = [
    "🚀 自动扫描 & 智能推荐",
    "🔍 单标的全量诊断",
    "🧪 策略历史回测引擎",
    "📊 自选清单监控",
]

if "target_page" in st.session_state and st.session_state.target_page:
    st.session_state.current_page = st.session_state.target_page
    st.session_state.target_page = None

for key, val in [
    ("current_page", NAV_OPTIONS[0]),
    ("selected_ticker", "MU"),
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
        min_price=2.0,
        max_atr_pct=15.0,
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
# 4. 股票池预设 & 数据库
# -----------------------------------------------------------------------------
INDEX_PRESET_POOLS = {
    "🔥 核心巨头与科技 (15只)": ["MU", "NVDA", "AAPL", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN"],
    "🧬 生物医药与前沿医疗 (含肿瘤突破/黑马)": ["LLY", "NVO", "MRNA", "BNTX", "REGN", "VRTX", "CRSP", "EDIT", "BEAM", "ILMN", "AMGN", "GILD", "BIIB", "TMO", "PFE"],
    "🎮 T2/二线高动能成长股": ["TTWO", "U", "NET", "SNOW", "DDOG", "RBLX", "PATH", "DKNG", "CROX", "CELH", "SMCI", "ARM", "APP", "MSTR", "PLTR"],
    "💻 半导体与芯片产业链": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "MU", "TXN", "AMAT", "LRCX", "ADI", "KLAC", "ARM", "MRVL"],
    "🌐 全球核心 ETF 组合": ["SPY", "QQQ", "IWM", "SOXX", "XBI", "XLV", "XLF", "XLE", "ARKK", "TLT", "GLD"],
}


def parse_symbols(text):
    items = re.split(r"[,，;；\s]+", str(text).strip().upper())
    out = []
    for symbol in items:
        symbol = symbol.replace(".", "-").strip()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


DB_FILE = "quant_terminal_ultra.db"


def init_quant_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT, category TEXT, added_at TEXT)")
    conn.commit()
    conn.close()


def add_to_watchlist(symbol):
    syms = parse_symbols(symbol)
    if syms:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)", (syms[0], syms[0], "推荐自选", datetime.now().strftime("%Y-%m-%d")))
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
# 5. 行情与多维精细评分矩阵 (Scoring Matrix)
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
        return frame if len(frame) >= 35 else None
    except Exception:
        return None


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

    delta = c.diff()
    gain = wilder(delta.clip(lower=0), 14)
    loss = wilder(-delta.clip(upper=0), 14)
    rs = gain / loss.replace(0, np.nan)
    d["RSI"] = 100 - 100 / (1 + rs)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACDSignal"] = d.MACD.ewm(span=9, adjust=False).mean()
    d["Hist"] = d.MACD - d.MACDSignal

    d["DollarVolume"] = (c * v).rolling(20).mean()
    d["ATRpct"] = d.ATR / c * 100
    d["Support"] = l.rolling(20).min()
    d["Return63"] = c.pct_change(63, fill_method=None)

    if benchmark is not None and not benchmark.empty:
        b = benchmark.Close.reindex(d.index)
        d["Relative63"] = (d.Return63 - b.pct_change(63, fill_method=None)) * 100
        d["MarketMA200"] = b.rolling(200).mean()
        d["MarketOK"] = b > d.MarketMA200
    else:
        d["Relative63"] = 0.0
        d["MarketOK"] = True

    # -------------------------------------------------------------------------
    # 精细量化打分矩阵 (Scoring Matrix 满分 100 分)
    # -------------------------------------------------------------------------
    # 1. 均线与趋势结构 (最高 30 分)
    trend_score = (
        (c > d.EMA10).astype(int) * 8
        + (d.EMA10 > d.EMA20).astype(int) * 8
        + (d.EMA20 > d.MA50).astype(int) * 8
        + (d.MA50 > d.MA200).astype(int) * 6
    )

    # 2. MACD 强弱度 (最高 25 分)
    macd_score = (
        (d.MACD > 0).astype(int) * 10
        + (d.Hist > 0).astype(int) * 10
        + (d.Hist > d.Hist.shift(1)).astype(int) * 5
    )

    # 3. RSI 健康度 (最高 20 分)
    rsi_score = pd.Series(0, index=d.index)
    rsi_score += np.where(d.RSI.between(52, 68), 20, 0)
    rsi_score += np.where(d.RSI.between(45, 52) | d.RSI.between(68, 75), 12, 0)
    rsi_score += np.where(d.RSI.between(35, 45), 5, 0)

    # 4. Alpha 相对大盘强度 (最高 15 分)
    alpha_score = pd.Series(0, index=d.index)
    alpha_score += np.where(d.Relative63 > 15, 15, 0)
    alpha_score += np.where((d.Relative63 > 5) & (d.Relative63 <= 15), 10, 0)
    alpha_score += np.where((d.Relative63 > 0) & (d.Relative63 <= 5), 5, 0)

    # 5. 量能与波动率健康度 (最高 10 分)
    vol_score = (
        (v > v.rolling(20).mean()).astype(int) * 5
        + (d.ATRpct.between(1.5, 7.0)).astype(int) * 5
    )

    d["Score"] = trend_score + macd_score + rsi_score + alpha_score + vol_score
    return d


def analyze_technical_aspects(row):
    """提取深度技术面形态诊断"""
    features = {}

    # 均线形态
    if row["EMA10"] > row["EMA20"] and row["EMA20"] > row["MA50"]:
        features["ma_status"] = "🟢 完美多头排列 (EMA10 > EMA20 > MA50)"
        features["ma_tag"] = "tag-bull"
    elif row["Close"] > row["MA50"]:
        features["ma_status"] = "🟡 站上中轨 (Close > MA50)"
        features["ma_tag"] = "tag-neutral"
    else:
        features["ma_status"] = "🔴 空头受压 (Close < MA50)"
        features["ma_tag"] = "tag-bear"

    # MACD 形态
    if row["MACD"] > 0 and row["Hist"] > 0:
        features["macd_status"] = "🟢 零轴上方金叉主升 (MACD & Hist 双正)"
        features["macd_tag"] = "tag-bull"
    elif row["Hist"] > 0:
        features["macd_status"] = "🟡 水下金叉反弹 (Hist 向上)"
        features["macd_tag"] = "tag-neutral"
    else:
        features["macd_status"] = "🔴 死柱向下调整 (Hist < 0)"
        features["macd_tag"] = "tag-bear"

    # RSI 形态
    rsi_val = row["RSI"]
    if 50 <= rsi_val <= 68:
        features["rsi_status"] = f"🟢 黄金动力区 (RSI: {rsi_val:.1f})"
        features["rsi_tag"] = "tag-bull"
    elif rsi_val > 70:
        features["rsi_status"] = f"⚠️ 超买高位警戒 (RSI: {rsi_val:.1f})"
        features["rsi_tag"] = "tag-neutral"
    else:
        features["rsi_status"] = f"🔴 动能弱势/超卖 (RSI: {rsi_val:.1f})"
        features["rsi_tag"] = "tag-bear"

    # 大盘相对强度 Alpha
    rel = row.get("Relative63", 0.0)
    if rel > 10:
        features["alpha_status"] = f"🚀 显著跑赢大盘 (超额收益 +{rel:.1f}%)"
    elif rel > 0:
        features["alpha_status"] = f"📈 微弱跑赢大盘 (+{rel:.1f}%)"
    else:
        features["alpha_status"] = f"📉 跑输大盘 ({rel:.1f}%)"

    return features


def plan(row, cfg=None):
    cfg = cfg or Config()
    required = ["Close", "ATR", "MA50", "MA200", "Support", "EMA10", "EMA20", "RSI", "Score"]
    if any(k not in row or not np.isfinite(row[k]) for k in required) or row.ATR <= 0:
        return None

    reasons = []
    is_bear_market = not row.MarketOK or (row.Close < row.MA200 and row.MA50 < row.MA200)
    if is_bear_market:
        reasons.append("🚫 熊市拦截：大盘或标的破位200日线")

    is_super_bull = row.Close > row.MA50 and row.EMA10 > row.EMA20

    if is_super_bull and not is_bear_market:
        entry = max(float(row.EMA10), float(row.Close * 0.985))
        buy_mode = "🚀 大牛市突破/主升跟进"
    else:
        entry = min(float(row.Close), float(row.EMA20))
        buy_mode = "⚡ 逢低回踩跟进"

    stop = min(entry - 1.5 * row.ATR, row.Support - 0.25 * row.ATR)
    risk = entry - stop
    target = entry + cfg.rr * risk

    if row.Close < cfg.min_price: reasons.append("价格低于门槛")
    if row.Score < cfg.min_score: reasons.append("综合评分不足")

    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "score": int(row.Score),
        "buy_mode": buy_mode,
        "is_bear": is_bear_market,
        "is_super_bull": is_super_bull,
        "atr_pct": float(row.ATRpct),
        "relative63": float(row.get("Relative63", 0.0)),
    }


def make_signal(symbol, frame, cfg, benchmark):
    d = indicators(frame, benchmark)
    last_row = d.iloc[-1]
    p = plan(last_row, cfg)
    tech_diag = analyze_technical_aspects(last_row)
    return {
        "symbol": symbol,
        "df": d,
        "plan": p,
        "tech_diag": tech_diag,
        "current_price": float(d.Close.iloc[-1]),
        "quant_score": int(p["score"]) if p else 0,
        "eligible": bool(p["eligible"]) if p else False,
        "summary": {
            "状态": "候选 · 入场挂单" if p and p["eligible"] else "观察中",
            "原因": "；".join(p["reasons"]) if p and p["reasons"] else "满足自适应筛选条件",
        },
    }


# -----------------------------------------------------------------------------
# 6. 回测引擎 (牛市移动止损 + 重新开仓)
# -----------------------------------------------------------------------------
def simulate(d, cfg=None, initial=10000.0, start=None):
    cfg = cfg or Config()
    start_i = 210 if start is None else max(210, int(d.index.searchsorted(pd.Timestamp(start))))
    if start_i >= len(d):
        raise ValueError("有效回测区间不足")

    fee = cfg.fee_bps / 1e4
    cash = float(initial)
    pos, entry, stop, basis = 0, 0.0, 0.0, 0.0
    trades = []
    curve = [{"Date": d.index[start_i - 1], "Equity": cash, "Benchmark": initial}]
    benchmark_entry = float(d.Open.iloc[start_i])

    for i in range(start_i, len(d)):
        row, prev, date = d.iloc[i], d.iloc[i - 1], d.index[i]

        if pos > 0:
            trailing_stop = max(stop, float(row.High - 2.5 * row.ATR))
            stop = trailing_stop

            if row.Low <= stop:
                exit_price = min(row.Open, stop) if row.Open < stop else stop
                proceeds = pos * exit_price * (1 - fee)
                cash += proceeds
                trades.append({"日期": date, "操作": "卖出", "原因": "移动止损/趋势保护", "价格": exit_price, "净盈亏": proceeds - basis})
                pos = 0

        if pos == 0:
            p = plan(prev, cfg)
            if p and p["eligible"]:
                fill_price = float(row.Open)
                stop = p["stop"]
                q = math.floor((cash * 0.95) / (fill_price * (1 + fee)))
                if q > 0:
                    pos = q
                    entry = fill_price
                    basis = pos * entry * (1 + fee)
                    cash -= basis
                    trades.append({"日期": date, "操作": "买入", "原因": p.get("buy_mode", "趋势开仓"), "价格": entry, "净盈亏": None})

        current_equity = cash + (pos * row.Close if pos > 0 else 0)
        curve.append({"Date": date, "Equity": current_equity, "Benchmark": initial * (row.Close / benchmark_entry)})

    eq = pd.DataFrame(curve).set_index("Date")
    ledger = pd.DataFrame(trades)
    sells = [t["净盈亏"] for t in trades if t["操作"] == "卖出" and t["净盈亏"] is not None]
    final = float(eq.Equity.iloc[-1])

    metrics = {
        "最终资产": final,
        "收益率%": (final / initial - 1) * 100,
        "买入持有%": (eq.Benchmark.iloc[-1] / initial - 1) * 100,
        "最大回撤%": float((eq.Equity / eq.Equity.cummax() - 1).min() * 100),
        "已平仓笔数": len(sells),
        "胜率%": (sum(p > 0 for p in sells) / len(sells) * 100) if sells else 0.0,
    }
    return metrics, eq, ledger


# -----------------------------------------------------------------------------
# 7. 3-Subplot 独立图表
# -----------------------------------------------------------------------------
def render_segmented_chart(sig_data, days=120):
    d = sig_data["df"].tail(days)
    p = sig_data["plan"]

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.22, 0.23],
        subplot_titles=None
    )

    fig.add_trace(go.Candlestick(
        x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close,
        name="日K",
        increasing_line_color='#00ff66', decreasing_line_color='#ff3366'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.EMA10, name="EMA10", line=dict(color="#00f0ff", width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.EMA20, name="EMA20", line=dict(color="#ffaa00", width=1.2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MA50, name="MA50", line=dict(color="#b87cff", width=1.5)), row=1, col=1)

    if p:
        fig.add_hline(y=p["entry"], line_dash="dash", line_color="#ccff00", annotation_text="买入参考", row=1, col=1)
        fig.add_hline(y=p["stop"], line_dash="dash", line_color="#ff3366", annotation_text="止损", row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI(14)", line=dict(color="#00f0ff", width=1.5)), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", row=2, col=1)

    colors = np.where(d.Hist >= 0, '#00ff66', '#ff3366')
    fig.add_trace(go.Bar(x=d.index, y=d.Hist, name="MACD Hist", marker_color=colors), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACD, name="DIF", line=dict(color="#00f0ff", width=1)), row=3, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACDSignal, name="DEA", line=dict(color="#ffaa00", width=1)), row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0b0e14",
        plot_bgcolor="#121821",
        height=660,
        margin=dict(l=15, r=15, t=10, b=15),
        showlegend=False,
        hovermode="x unified"
    )
    fig.update_xaxes(showgrid=True, gridcolor="#1e2631", rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridcolor="#1e2631")

    return fig


def metric_card(title, value, css_class=""):
    return f"<div class='tech-card'><div class='metric-title'>{html.escape(title)}</div><div class='metric-value {css_class}'>{html.escape(str(value))}</div></div>"


# -----------------------------------------------------------------------------
# 8. STREAMLIT 主交互界面
# -----------------------------------------------------------------------------
st.markdown('<h3 class="tech-header">⚡ QUANTUM TERMINAL ULTRA</h3>', unsafe_allow_html=True)
st.markdown('<div class="tech-subtitle">Bull/Bear Adaptive Quantitative System</div>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🎛️ 终端控制台")
    selected_nav = st.radio(
        "导航菜单",
        NAV_OPTIONS,
        index=NAV_OPTIONS.index(st.session_state.current_page),
    )
    if selected_nav != st.session_state.current_page:
        st.session_state.current_page = selected_nav
        st.rerun()

    st.markdown("---")
    st.session_state.rr_ratio = st.slider("目标盈亏比 (R/R)", 1.0, 5.0, float(st.session_state.rr_ratio), 0.5)
    st.session_state.risk_pct = st.slider("单笔风控 %", 0.1, 5.0, float(st.session_state.risk_pct), 0.1)
    st.session_state.min_score = st.slider("最低筛选评分门槛", 40, 95, int(st.session_state.min_score), 5)

cfg = cfg_from_session()
app_mode = st.session_state.current_page

# =============================================================================
# TAB 1: 自动扫描 & 智能推荐
# =============================================================================
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 市场全池自动扫描")
    c1, c2, c3 = st.columns([2.5, 3.5, 1.5])
    with c1: 
        selected_preset = st.selectbox("预设股票池", list(INDEX_PRESET_POOLS.keys()))
    with c2: 
        custom_pool_str = st.text_input("待扫描代码（自由追加）", value=", ".join(INDEX_PRESET_POOLS[selected_preset]))
    with c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动扫描", use_container_width=True)

    if run_scan:
        symbols = parse_symbols(custom_pool_str)
        benchmark = fetch_history("SPY", "3y")
        results = []
        progress = st.progress(0, text="计算多维度 Scoring Matrix 打分中...")
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_map = {executor.submit(fetch_history, s, "3y"): s for s in symbols}
            done = 0
            for future in as_completed(future_map):
                s = future_map[future]
                done += 1
                frame = future.result()
                if frame is not None and benchmark is not None:
                    try:
                        results.append(make_signal(s, frame, cfg, benchmark))
                    except Exception:
                        pass
                progress.progress(done / len(symbols))
        progress.empty()
        results.sort(key=lambda x: (x["eligible"], x["quant_score"]), reverse=True)
        st.session_state.scan_results = results

    res = st.session_state.get("scan_results", [])
    if res:
        eligible_res = [r for r in res if r["eligible"]]
        st.markdown(f"<div class='signal-strip'><b>扫描完成</b> · 候选达标标的 <b>{len(eligible_res)}</b> 只 / 共扫描 {len(res)} 只</div>", unsafe_allow_html=True)
        
        top3 = eligible_res[:3] if eligible_res else res[:3]
        cols = st.columns(len(top3))
        for i, r in enumerate(top3):
            p = r.get("plan", {})
            buy_mode_str = p.get("buy_mode", "⚡ 动态量化") if p else "未触发"
            with cols[i]:
                st.markdown(
                    f"""<div class='tech-card'>
                    <div style='display:flex;justify-content:space-between;'>
                        <span style='color:#00f0ff;font-weight:800;'>TOP {i+1} · {r['symbol']}</span>
                        <span style='color:#ccff00;font-weight:800;'>{r['quant_score']}分</span>
                    </div>
                    <div style='font-size:22px;font-weight:800;color:#fff;margin-top:4px;'>${r['current_price']:.2f}</div>
                    <div style='font-size:12px;color:#8b949e'>模式: {html.escape(buy_mode_str)}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if st.button(f"🔎 查看 {r['symbol']} 诊断", key=f"btn_diag_{r['symbol']}", use_container_width=True):
                    st.session_state.selected_ticker = r['symbol']
                    st.session_state.target_page = "🔍 单标的全量诊断"
                    st.rerun()

        # 补全全面数据列的扫描结果表格
        df_display = pd.DataFrame([{
            "代码": r["symbol"], 
            "精细评分 (Score)": r["quant_score"], 
            "状态": r["summary"]["状态"], 
            "现价": f"${r['current_price']:.2f}", 
            "建议买入位": f"${r['plan']['entry']:.2f}" if r["plan"] else "N/A",
            "建议止损位": f"${r['plan']['stop']:.2f}" if r["plan"] else "N/A",
            "目标价": f"${r['plan']['target']:.2f}" if r["plan"] else "N/A",
            "ATR波动率%": f"{r['plan']['atr_pct']:.2f}%" if r["plan"] else "N/A",
            "相对大盘Alpha": f"{r['plan']['relative63']:+.2f}%" if r["plan"] else "N/A",
            "信号及筛选说明": r["summary"]["原因"]
        } for r in res])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 2: 单标的全量诊断 (恢复全面技术特征面板)
# =============================================================================
elif app_mode == "🔍 单标的全量诊断":
    st.markdown("### 🔍 标的深度诊断")
    c1, c2 = st.columns([3, 1])
    with c1: 
        ticker_input = st.text_input("输入股票代码（如 MU, T2, TTWO, LLY 等）", value=st.session_state.selected_ticker).upper().strip()
    with c2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("⚡ 诊断标的", use_container_width=True):
            st.session_state.selected_ticker = parse_symbols(ticker_input)[0]
            st.rerun()

    sym = st.session_state.selected_ticker
    frame = fetch_history(sym, "3y")
    benchmark = fetch_history("SPY", "3y")

    if frame is not None and benchmark is not None:
        sig = make_signal(sym, frame, cfg, benchmark)
        p = sig["plan"]
        td = sig["tech_diag"]

        # 指标卡片
        html_cards = (
            metric_card("现价 / 综合评分", f"${sig['current_price']:.2f} ({sig['quant_score']}分)")
            + metric_card("自适应买入位", f"${p['entry']:.2f}" if p else "N/A", "metric-buy")
            + metric_card("结构止损位", f"${p['stop']:.2f}" if p else "N/A", "metric-stop")
            + metric_card("目标价 (盈亏比 " + str(cfg.rr) + ")", f"${p['target']:.2f}" if p else "N/A", "metric-take")
        )
        st.markdown(f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{html_cards}</div>", unsafe_allow_html=True)
        
        # 恢复深度技术特征诊断面板
        st.markdown(f"""
        <div class='diag-box'>
            <div style='font-size:14px;font-weight:700;color:#00f0ff;margin-bottom:8px;'>📊 {sym} 技术面深度特征提取</div>
            <div style='display:grid;grid-template-columns:repeat(2,1fr);gap:10px;font-size:13px;'>
                <div>• <b>均线排列结构</b>：<span class='diag-tag {td['ma_tag']}'>{td['ma_status']}</span></div>
                <div>• <b>MACD 柱状图动能</b>：<span class='diag-tag {td['macd_tag']}'>{td['macd_status']}</span></div>
                <div>• <b>RSI 震荡指标状态</b>：<span class='diag-tag {td['rsi_tag']}'>{td['rsi_status']}</span></div>
                <div>• <b>大盘相对强度 (Alpha)</b>：<b>{td['alpha_status']}</b></div>
            </div>
            <div style='margin-top:8px;font-size:12px;color:#8b949e;border-top:1px solid #21262d;padding-top:6px;'>
                💡 <b>系统综合建议</b>：{sig['summary']['原因']}
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.plotly_chart(render_segmented_chart(sig), use_container_width=True)
    else:
        st.error(f"无法获取代码 {sym} 的行情数据，请检查代码。")

# =============================================================================
# TAB 3: 策略历史回测引擎
# =============================================================================
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 牛熊自适应策略回测引擎")
    with st.form("bt_form"):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: bt_sym = st.text_input("回测代码", value=st.session_state.selected_ticker).upper()
        with c2: start_d = st.date_input("开始日期", value=pd.Timestamp("2026-01-01"))
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
                + metric_card("最大回撤", f"{metrics['最大回撤%']:.2f}%", "metric-stop")
                + metric_card("平仓胜率", f"{metrics['胜率%']:.1f}% ({metrics['已平仓笔数']}笔)", "metric-buy")
            )
            st.markdown(f"<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:10px'>{html_bt_cards}</div>", unsafe_allow_html=True)

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Equity, name="Quantum 趋势追踪策略", line=dict(color="#00f0ff", width=2)))
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.Benchmark, name="标的买入持有", line=dict(color="#6e7681", width=1.5, dash="dot")))
            fig_eq.update_layout(template="plotly_dark", paper_bgcolor="#0b0e14", plot_bgcolor="#161b22", height=380)
            st.plotly_chart(fig_eq, use_container_width=True)

            st.markdown("#### 🧾 详细交易明细")
            st.dataframe(ledger, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 4: 自选清单监控
# =============================================================================
else:
    st.markdown("### 📊 自选清单实时监控")
    watch_df = get_watchlist()
    if not watch_df.empty:
        benchmark = fetch_history("SPY", "3y")
        watch_results = []
        for sym in watch_df["symbol"]:
            frame = fetch_history(sym, "3y")
            if frame is not None and benchmark is not None:
                try: watch_results.append(make_signal(sym, frame, cfg, benchmark))
                except Exception: pass
        if watch_results:
            df_w = pd.DataFrame([{
                "代码": r["symbol"], 
                "精细评分": r["quant_score"], 
                "现价": f"${r['current_price']:.2f}", 
                "买入参考": f"${r.get('plan', {}).get('entry', 0.0):.2f}",
                "止损参考": f"${r.get('plan', {}).get('stop', 0.0):.2f}"
            } for r in watch_results])
            st.dataframe(df_w, use_container_width=True, hide_index=True)
