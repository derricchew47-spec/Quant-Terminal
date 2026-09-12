import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. 页面配置与移动端轻量级极简视觉 (Cyberpunk Dark Theme)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="QuantumSignal Terminal PRO",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600;700&display=swap');
    
    .stApp {
        background-color: #0b0e14;
        color: #c9d1d9;
        font-family: 'Fira Code', monospace, -apple-system, sans-serif;
    }
    
    .tech-header {
        font-family: 'Fira Code', monospace;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 12px rgba(0, 240, 255, 0.4);
        margin-bottom: 15px;
    }
    
    .tech-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
        margin-bottom: 10px;
        position: relative;
    }
    
    .tech-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 2px;
        background: linear-gradient(90deg, #00f0ff, #7000ff);
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }

    .metric-title {
        font-size: 11px;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .metric-value-buy {
        font-size: 18px;
        font-weight: 700;
        color: #00ff66;
        text-shadow: 0 0 8px rgba(0, 255, 102, 0.3);
    }

    .metric-value-nearbuy {
        font-size: 18px;
        font-weight: 700;
        color: #ccff00;
        text-shadow: 0 0 8px rgba(204, 255, 0, 0.3);
    }
    
    .metric-value-stop {
        font-size: 18px;
        font-weight: 700;
        color: #ff3366;
        text-shadow: 0 0 8px rgba(255, 51, 102, 0.3);
    }
    
    .metric-value-take {
        font-size: 18px;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
    }

    /* 侧边栏样式 */
    div[data-testid="stSidebar"] .stRadio > div {
        gap: 8px;
    }

    div[data-testid="stSidebar"] .stRadio > div > label {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 10px 12px;
        width: 100%;
        cursor: pointer;
        transition: all 0.2s ease-in-out;
    }

    div[data-testid="stSidebar"] .stRadio > div > label:hover {
        border-color: #00f0ff;
        background-color: #1c2129;
    }

    div[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background: linear-gradient(135deg, rgba(0, 240, 255, 0.15) 0%, rgba(112, 0, 255, 0.15) 100%);
        border: 1.5px solid #00f0ff !important;
    }

    div[data-testid="stSidebar"] .stRadio > div > label > div:first-child {
        display: none;
    }

    .stTextInput input, .stNumberInput input, .stSelectbox div {
        background-color: #0b0e14 !important;
        color: #00f0ff !important;
        border: 1px solid #30363d !important;
        border-radius: 6px !important;
        font-family: 'Fira Code', monospace !important;
    }

    div.stButton > button {
        background: linear-gradient(135deg, #00f0ff 0%, #7000ff 100%) !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 700 !important;
        border-radius: 6px !important;
        box-shadow: 0 0 10px rgba(0, 240, 255, 0.3) !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. State 初始化 & 预设池字典
# -----------------------------------------------------------------------------
NAV_OPTIONS = [
    "🚀 自动扫描 & 智能推荐", 
    "🔍 单标的全量诊断", 
    "🧪 策略历史回测引擎", 
    "📊 自选清单监控"
]

if 'current_page' not in st.session_state:
    st.session_state['current_page'] = NAV_OPTIONS[0]
if 'selected_ticker' not in st.session_state:
    st.session_state['selected_ticker'] = "NVDA"
if 'rr_ratio' not in st.session_state:
    st.session_state['rr_ratio'] = 2.0

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_sp500_tickers():
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        return tickers
    except Exception:
        return ["AAPL", "NVDA", "INTC", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "LLY"]

INDEX_PRESET_POOLS = {
    "🔥 精选核心科技 (15只)": ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN", "SMCI"],
    "💻 半导体与芯片产业链 (含 INTC/TSM)": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "MU", "TXN", "AMAT", "LRCX", "ADI", "KLAC", "ARM", "SMCI", "MRVL"],
    "🏥 医疗生物与医药巨头": ["LLY", "NVO", "PFE", "JNJ", "UNH", "ABBV", "MRK", "AMGN", "GILD", "BMY", "CVS", "ISRG", "TMO", "DHR"],
    "🚀 科技七巨头 & 衍生 AI 概念": ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "PLTR", "ORCL", "IBM", "AMD", "NOW"],
    "🌐 核心ETF与资产类别": ["SPY", "QQQ", "IWM", "SOXX", "XLV", "XLF", "XLE", "ARKK", "TLT", "GLD"],
    "📊 标普 500 (S&P 500) 全量动态池": "SP500_AUTO"
}

# -----------------------------------------------------------------------------
# 3. SQLite 本地存储
# -----------------------------------------------------------------------------
DB_FILE = "quant_terminal_watch.db"

def init_quant_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            added_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_to_watchlist(symbol, name, category):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)",
              (symbol.upper().strip(), name, category, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()

def get_watchlist():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM watchlist", conn)
    conn.close()
    return df

init_quant_db()

# -----------------------------------------------------------------------------
# 4. Pro 数学指标计算 & Wilder 平滑算法库
# -----------------------------------------------------------------------------
def clean_df(frame):
    d = frame.copy()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d = d.loc[~d.index.duplicated(keep='last')].sort_index()
    fields = ['Open', 'High', 'Low', 'Close', 'Volume']
    d = d[fields].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
    valid = (d[fields[:4]] > 0).all(axis=1) & (d.Volume >= 0)
    valid &= (d.High >= d[['Open','Close','Low']].max(axis=1)) & (d.Low <= d[['Open','Close','High']].min(axis=1))
    return d.loc[valid]

def wilder_smooth(s, n=14):
    a = s.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    for i in range(n-1, len(a)):
        if i == 0 or np.isnan(out[i-1]):
            if np.isfinite(a[i-n+1:i+1]).all():
                out[i] = a[i-n+1:i+1].mean()
        elif np.isfinite(a[i]):
            out[i] = (out[i-1]*(n-1) + a[i])/n
    return pd.Series(out, index=s.index)

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_spy_benchmark(period="2y"):
    try:
        spy = yf.Ticker("SPY").history(period=period)
        return clean_df(spy)
    except Exception:
        return None

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_advanced_quant_signals(symbol: str, risk_reward_ratio: float = 2.0, period: str = "2y"):
    if not symbol or not symbol.strip():
        return None
    try:
        ticker = yf.Ticker(symbol.strip().upper())
        df = ticker.history(period=period)
        if df.empty or len(df) < 210:
            return None
        
        df = clean_df(df)
        c, h, l, v = df.Close, df.High, df.Low, df.Volume
        
        # 1. ATR
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        df['ATR'] = wilder_smooth(tr, 14)
        
        # 2. 均线
        for n in (20, 50, 200):
            df[f'MA{n}'] = c.rolling(n).mean()
        df['EMA10'] = c.ewm(span=10, adjust=False).mean()
        df['EMA20'] = c.ewm(span=20, adjust=False).mean()
        
        # 3. RSI
        delta = c.diff()
        gain, loss = wilder_smooth(delta.clip(lower=0)), wilder_smooth(-delta.clip(upper=0))
        df['RSI'] = 100 - 100/(1 + gain/loss.replace(0, np.nan))
        df.loc[(loss == 0) & (gain > 0), 'RSI'] = 100
        df.loc[(gain == 0) & (loss > 0), 'RSI'] = 0
        df.loc[(gain == 0) & (loss == 0), 'RSI'] = 50
        
        # 4. MACD
        df['MACD'] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        
        # 5. Bollinger Bands & VWMA20
        df['VWMA20'] = (((h+l+c)/3)*v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
        df['STD20'] = c.rolling(20).std()
        df['Upper_Band'] = df['MA20'] + (2 * df['STD20'])
        df['Lower_Band'] = df['MA20'] - (2 * df['STD20'])
        
        # 6. Supertrend
        at10 = wilder_smooth(tr, 10).to_numpy()
        ub = ((h+l)/2).to_numpy() + 3*at10
        lb = ((h+l)/2).to_numpy() - 3*at10
        fu, fl = ub.copy(), lb.copy()
        direction = np.zeros(len(df), dtype=int)
        line = np.full(len(df), np.nan)
        prices = c.to_numpy()
        for i in range(len(df)):
            if not np.isfinite(at10[i]): continue
            if i == 0 or not np.isfinite(at10[i-1]):
                direction[i] = 1 if prices[i] >= (h.iloc[i]+l.iloc[i])/2 else -1
            else:
                fu[i] = ub[i] if ub[i] < fu[i-1] or prices[i-1] > fu[i-1] else fu[i-1]
                fl[i] = lb[i] if lb[i] > fl[i-1] or prices[i-1] < fl[i-1] else fl[i-1]
                direction[i] = direction[i-1]
                if direction[i-1] == -1 and prices[i] > fu[i]: direction[i] = 1
                elif direction[i-1] == 1 and prices[i] < fl[i]: direction[i] = -1
            line[i] = fl[i] if direction[i] == 1 else fu[i]
        df['STDirection'], df['Supertrend'] = direction, line

        # 7. 相对 SPY 的 Alpha
        spy_df = fetch_spy_benchmark(period=period)
        df['Return63'] = c.pct_change(63, fill_method=None)
        if spy_df is not None and not spy_df.empty:
            b = spy_df.Close.reindex(df.index)
            df['Relative63'] = df['Return63'] - b.pct_change(63, fill_method=None)
            df['MarketOK'] = b > b.rolling(200).mean()
        else:
            df['Relative63'] = np.nan
            df['MarketOK'] = False

        df['DollarVolume'] = (c * v).rolling(20).mean()
        df['ATRpct'] = df['ATR'] / c * 100

        # 8. 打分引擎并补充量化得分序列 (量化得分列命名为 QuantScore 供回测使用)
        trend_score = ((df.Close > df.MA50).astype(int)*10 + (df.MA50 > df.MA200).astype(int)*10 + (df.MA50 > df.MA50.shift(10)).astype(int)*10)
        rel_val = df.Relative63.fillna(-1)
        strength_score = np.where(rel_val > 0.10, 20, np.where(rel_val > 0.03, 15, np.where(rel_val > 0, 10, 0)))
        momentum_score = (np.where((df.RSI >= 45) & (df.RSI <= 65), 10, 0) + np.where(df.MACD_Hist > 0, 5, 0) + np.where(df.STDirection == 1, 5, 0))
        dvol = df.DollarVolume
        liquidity_score = np.where(dvol >= 50e6, 10, np.where(dvol >= 10e6, 5, 0))
        atr_p = df.ATRpct
        volatility_score = np.where((atr_p >= 1) & (atr_p <= 4), 10, np.where((atr_p >= 0.3) & (atr_p <= 6), 5, 0))
        market_score = np.where(df.MarketOK, 10, 0)
        
        df['QuantScore'] = (trend_score + strength_score + momentum_score + liquidity_score + volatility_score + market_score).astype(int)

        r_last = df.iloc[-1]
        quant_score = int(r_last.QuantScore)

        # 9. 风控位计算
        current_price = float(r_last.Close)
        prev_close = float(df.Close.iloc[-2])
        change_pct = ((current_price - prev_close) / prev_close) * 100
        
        near_market_buy = min(current_price, float(r_last.EMA20))
        support = float(df.Low.rolling(20).min().iloc[-1])
        stop_loss = min(near_market_buy - 1.5 * float(r_last.ATR), support - 0.25 * float(r_last.ATR))
        stop_loss = max(stop_loss, 0.01)
        risk = near_market_buy - stop_loss
        take_profit = near_market_buy + (risk * risk_reward_ratio)
        ideal_buy_price = near_market_buy - (0.25 * float(r_last.ATR))

        if quant_score >= 80: recommendation = "🔥 极力推荐 (High Alpha)"
        elif quant_score >= 65: recommendation = "👀 重点关注 (Watch Opportunity)"
        else: recommendation = "❄️ 观望/防守 (Avoid)"

        macd_status = "🟢 金叉 (Bullish)" if r_last.MACD > r_last.MACD_Signal else "🔴 死叉 (Bearish)"
        supertrend_signal = "🟢 多头轨道 (BUY)" if r_last.STDirection == 1 else "🔴 空头轨道 (SELL)"

        if current_price > r_last.MA20 and r_last.MA20 > r_last.MA50:
            trend_label = "🔥 强力多头 (Strong Uptrend)"
        elif current_price < r_last.MA20 and r_last.MA20 < r_last.MA50:
            trend_label = "❄️ 降维空头 (Downtrend Risk)"
        else:
            trend_label = "⚡ 宽幅震荡 (Sideways)"

        return {
            "df": df, "symbol": symbol.upper().strip(),
            "name": symbol.upper(),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "near_market_buy": round(near_market_buy, 2),
            "ideal_buy_price": round(ideal_buy_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "atr": round(float(r_last.ATR), 2),
            "rsi": round(float(r_last.RSI), 1),
            "ema10": round(float(r_last.EMA10), 2),
            "lower_band": round(float(r_last.Lower_Band), 2),
            "upper_band": round(float(r_last.Upper_Band), 2),
            "vwap": round(float(r_last.VWMA20), 2),
            "macd_status": macd_status,
            "supertrend_signal": supertrend_signal,
            "trend_label": trend_label,
            "quant_score": quant_score,
            "recommendation": recommendation
        }
    except Exception:
        return None

# -----------------------------------------------------------------------------
# 5. 高级历史回测引擎 (已修复字段未定义引发的 AttributeError)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def run_backtest_engine(symbol: str, initial_capital: float = 10000.0, risk_reward_ratio: float = 2.0, period: str = "2y"):
    sig_data = fetch_advanced_quant_signals(symbol, risk_reward_ratio=risk_reward_ratio, period=period)
    if not sig_data:
        return None, None
        
    df = sig_data['df']
    if len(df) < 212:
        return None, None

    fee, slip = 0.0005, 0.0005
    capital = float(initial_capital)
    pos = 0.0
    entry_price = 0.0
    stop_loss = 0.0
    target_price = 0.0
    basis = 0.0
    
    trades = []
    equity_curve = []
    
    start_i = 210
    equity_curve.append({'Date': df.index[start_i-1], 'Capital': capital})

    for i in range(start_i, len(df)):
        r, prev = df.iloc[i], df.iloc[i-1]
        date = df.index[i]
        exited = False
        entered_intraday = False
        
        # 1. 离场机制
        if pos > 0:
            if r.Open <= stop_loss:
                sell_price = float(r.Open) * (1 - slip)
                proceeds = pos * sell_price * (1 - fee)
                capital += proceeds
                trades.append({"date": date, "type": "SELL (跳空止损)", "price": round(sell_price, 2), "profit": round(proceeds - basis, 2), "capital": round(capital, 2)})
                pos = 0.0
                exited = True
            elif prev.Close < prev.MA50:
                sell_price = float(r.Open) * (1 - slip)
                proceeds = pos * sell_price * (1 - fee)
                capital += proceeds
                trades.append({"date": date, "type": "SELL (趋势破坏)", "price": round(sell_price, 2), "profit": round(proceeds - basis, 2), "capital": round(capital, 2)})
                pos = 0.0
                exited = True
            elif r.Open >= target_price:
                sell_price = float(target_price)
                proceeds = pos * sell_price * (1 - fee)
                capital += proceeds
                trades.append({"date": date, "type": "SELL (开盘跳空止盈)", "price": round(sell_price, 2), "profit": round(proceeds - basis, 2), "capital": round(capital, 2)})
                pos = 0.0
                exited = True

        # 2. 开仓买入（解决 prev.QuantScore 字段匹配问题）
        if pos == 0 and not exited:
            if prev.Close > prev.MA50 > prev.MA200 and prev.QuantScore >= 60 and r.Low <= min(prev.Close, prev.EMA20):
                if r.Open > (min(prev.Close, prev.EMA20) - 1.5 * prev.ATR):
                    fill = min(float(r.Open), min(float(prev.Close), float(prev.EMA20)))
                    proposed_stop = max(fill - 1.5 * float(prev.ATR), 0.01)
                    per_share_risk = fill - proposed_stop * (1 - slip) + fee * (fill + proposed_stop)
                    
                    if per_share_risk > 0:
                        max_shares = max(0, int(capital * 0.20 / (fill * (1 + fee))))
                        risk_shares = max(0, int(capital * 0.005 / per_share_risk))
                        q = min(max_shares, risk_shares)
                        
                        if q > 0:
                            pos = float(q)
                            entry_price = fill
                            stop_loss = proposed_stop
                            target_price = entry_price + risk_reward_ratio * (entry_price - stop_loss)
                            basis = pos * entry_price * (1 + fee)
                            capital -= basis
                            entered_intraday = r.Open > min(prev.Close, prev.EMA20)
                            trades.append({"date": date, "type": "BUY", "price": round(entry_price, 2), "profit": 0.0, "capital": round(pos * entry_price, 2)})

        # 3. 盘中双触发检测
        if pos > 0:
            if r.Low <= stop_loss:
                sell_price = float(stop_loss) * (1 - slip)
                proceeds = pos * sell_price * (1 - fee)
                capital += proceeds
                trades.append({"date": date, "type": "SELL (止损离场)", "price": round(sell_price, 2), "profit": round(proceeds - basis, 2), "capital": round(capital, 2)})
                pos = 0.0
            elif not entered_intraday and r.High >= target_price:
                sell_price = float(target_price)
                proceeds = pos * sell_price * (1 - fee)
                capital += proceeds
                trades.append({"date": date, "type": "SELL (目标止盈)", "price": round(sell_price, 2), "profit": round(proceeds - basis, 2), "capital": round(capital, 2)})
                pos = 0.0
                
            if pos > 0:
                stop_loss = max(stop_loss, float(r.High - 2 * r.ATR))

        current_total = capital + (pos * float(r.Close))
        equity_curve.append({"Date": date, "Capital": current_total})

    equity_df = pd.DataFrame(equity_curve)
    if not equity_df.empty:
        total_return = ((equity_df['Capital'].iloc[-1] - initial_capital) / initial_capital) * 100
        equity_df['Max_Capital'] = equity_df['Capital'].cummax()
        equity_df['Drawdown'] = (equity_df['Capital'] - equity_df['Max_Capital']) / equity_df['Max_Capital']
        max_drawdown = equity_df['Drawdown'].min() * 100
        
        sell_trades = [t for t in trades if "SELL" in t['type']]
        win_trades = [t for t in sell_trades if t['profit'] > 0]
        win_rate = (len(win_trades) / len(sell_trades) * 100) if sell_trades else 0.0
        
        metrics = {
            "initial_capital": initial_capital,
            "final_capital": round(equity_df['Capital'].iloc[-1], 2),
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "win_rate": round(win_rate, 1),
            "total_trades": len(sell_trades)
        }
        return metrics, equity_df
    return None, None

# -----------------------------------------------------------------------------
# 6. Quantum One Plotly 绘图引擎
# -----------------------------------------------------------------------------
def render_professional_chart(sig_data):
    df = sig_data['df'].tail(60)
    
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(
            f"📈 {sig_data['symbol']} 主图", 
            "📊 MACD 动能量能", 
            "⚡ RSI 相对强弱"
        )
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K线", increasing_line_color='#00ff66', decreasing_line_color='#ff3366'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['VWMA20'], line=dict(color='#ff00ea', width=1.2, dash='dot'), name="VWMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA10'], line=dict(color='#00f0ff', width=1.2), name="EMA10"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Supertrend'], line=dict(color='#a996ef', width=1.2), name="Supertrend"), row=1, col=1)

    fig.add_hline(y=sig_data['near_market_buy'], line_dash="dash", line_color="#ccff00", annotation_text="⚡ 买点", row=1, col=1)
    fig.add_hline(y=sig_data['ideal_buy_price'], line_dash="dash", line_color="#00ff66", annotation_text="🎯 理想买", row=1, col=1)
    fig.add_hline(y=sig_data['stop_loss'], line_dash="dash", line_color="#ff3366", annotation_text="🛡️ 止损", row=1, col=1)

    colors = np.where(df['MACD_Hist'] >= 0, '#00ff66', '#ff3366')
    fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors, name="MACD Hist"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#00f0ff', width=1), name="DIF"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#ffaa00', width=1), name="DEA"), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#ab47bc', width=1.5), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", opacity=0.7, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", opacity=0.7, row=3, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor='#0b0e14', plot_bgcolor='#161b22',
        margin=dict(l=10, r=10, t=25, b=10), height=550, showlegend=False,
        xaxis3_rangeslider_visible=False
    )
    fig.update_xaxes(showgrid=True, gridcolor='#21262d')
    fig.update_yaxes(showgrid=True, gridcolor='#21262d')
    return fig

# -----------------------------------------------------------------------------
# 7. UI 主体逻辑与无缝页面路由
# -----------------------------------------------------------------------------
st.markdown('<h3 class="tech-header">⚡ QUANTUM TERMINAL PRO</h3>', unsafe_allow_html=True)

def on_nav_change():
    st.session_state['current_page'] = st.session_state['nav_radio_choice']

with st.sidebar:
    st.markdown("### 🎛️ 终端控制台")
    current_idx = NAV_OPTIONS.index(st.session_state['current_page']) if st.session_state['current_page'] in NAV_OPTIONS else 0
    
    st.radio(
        "导航菜单",
        NAV_OPTIONS,
        index=current_idx,
        key="nav_radio_choice",
        on_change=on_nav_change,
        label_visibility="collapsed"
    )

    st.markdown("---")
    with st.form(key="global_setting_form"):
        st.markdown("#### ⚙️ 策略风控")
        new_rr = st.slider("目标盈亏比", 1.0, 4.0, float(st.session_state['rr_ratio']), 0.5)
        form_submitted = st.form_submit_button("保存配置", use_container_width=True)
        if form_submitted:
            st.session_state['rr_ratio'] = new_rr
            st.rerun()

app_mode = st.session_state['current_page']
rr_ratio = st.session_state['rr_ratio']

# --- 模式 1: 自动化全市场扫描推荐 ---
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 量化自动扫描与推荐")

    c_preset, c_custom, c_btn = st.columns([2.5, 3.5, 1.5])
    
    with c_preset:
        selected_preset = st.selectbox("📦 选择扫描预设池", list(INDEX_PRESET_POOLS.keys()))

    if INDEX_PRESET_POOLS[selected_preset] == "SP500_AUTO":
        default_pool_list = fetch_sp500_tickers()
    else:
        default_pool_list = INDEX_PRESET_POOLS[selected_preset]

    with c_custom:
        custom_pool_str = st.text_input("待扫描代码 (逗号分隔)", value=", ".join(default_pool_list))

    with c_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动扫描", use_container_width=True)

    symbols_to_scan = [s.strip().upper() for s in custom_pool_str.split(",") if s.strip()]

    if run_scan or 'scan_results' in st.session_state:
        if run_scan:
            progress_bar = st.progress(0)
            scan_data = []
            total_symbols = len(symbols_to_scan)
            for idx, sym in enumerate(symbols_to_scan):
                sig = fetch_advanced_quant_signals(sym, risk_reward_ratio=rr_ratio)
                if sig:
                    scan_data.append(sig)
                progress_bar.progress((idx + 1) / total_symbols)
            progress_bar.empty()
            scan_data.sort(key=lambda x: x['quant_score'], reverse=True)
            st.session_state.scan_results = scan_data

        results = st.session_state.get('scan_results', [])

        if results:
            st.markdown("#### 🔥 得分 Top 3 推荐标的")
            top_cols = st.columns(min(3, len(results)))
            for i, col in enumerate(top_cols):
                res = results[i]
                with col:
                    st.markdown(f"""
                    <div class="tech-card">
                        <div style="font-size:10px; color:#00f0ff; font-weight:700;">TOP {i+1}</div>
                        <div style="font-size:18px; font-weight:700; color:#ffffff;">{res['symbol']}</div>
                        <div style="font-size:16px; font-weight:700; color:#ccff00; margin-top:4px;">得分: {res['quant_score']}</div>
                        <div style="font-size:11px; color:#00ff66;">{res['recommendation']}</div>
                        <hr style="border-color:#30363d; margin:6px 0;">
                        <div style="font-size:11px; color:#8b949e;">现价: <b>${res['current_price']}</b></div>
                        <div style="font-size:11px; color:#ccff00;">⚡ 贴合买点: <b>${res['near_market_buy']}</b></div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"🔍 诊断 {res['symbol']}", key=f"btn_top_{res['symbol']}"):
                        st.session_state['selected_ticker'] = res['symbol']
                        st.session_state['current_page'] = "🔍 单标的全量诊断"
                        st.rerun()

            st.markdown("---")
            st.markdown("#### 📊 全量矩阵总表")
            table_rows = []
            for r in results:
                table_rows.append({
                    "代码": r['symbol'],
                    "综合得分": r['quant_score'],
                    "推荐评级": r['recommendation'],
                    "现价 ($)": r['current_price'],
                    "⚡ 贴合买点 ($)": r['near_market_buy'],
                    "🎯 理想买点 ($)": r['ideal_buy_price'],
                    "🛡️ 止损位 ($)": r['stop_loss'],
                    "🎉 止盈位 ($)": r['take_profit'],
                    "RSI": r['rsi']
                })
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# --- 模式 2: 单标的精细化诊断 (恢复经典的左右分栏醒目 UI) ---
elif app_mode == "🔍 单标的全量诊断":
    st.markdown("### 🔍 标的量化诊断")
    
    with st.form(key="symbol_search_form"):
        c_in, c_b = st.columns([3, 1])
        with c_in:
            target_symbol = st.text_input("股票代码", value=st.session_state.get('selected_ticker', 'NVDA')).upper().strip()
        with c_b:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            search_submitted = st.form_submit_button("⚡ 诊断", use_container_width=True)
            if search_submitted:
                st.session_state['selected_ticker'] = target_symbol

    target_symbol = st.session_state.get('selected_ticker', 'NVDA')
    if target_symbol:
        sig = fetch_advanced_quant_signals(target_symbol, risk_reward_ratio=rr_ratio)
        if sig:
            # 恢复经典的顶部左右分栏结构
            left_col, right_col = st.columns([1.2, 2.8])
            
            with left_col:
                st.markdown(f"""
                <div class="tech-card" style="padding: 16px;">
                    <div style="font-size:24px; font-weight:700; color:#ffffff;">{sig['symbol']}</div>
                    <div style="font-size:12px; color:#8b949e; margin-bottom: 8px;">{sig['name']}</div>
                    <div style="font-size:32px; font-weight:700; color:#00f0ff;">{sig['quant_score']} <span style="font-size:14px; color:#8b949e;">/ 100 分</span></div>
                    <div style="font-size:14px; font-weight:700; color:#00ff66; margin-top: 4px;">{sig['recommendation']}</div>
                    <hr style="border-color:#30363d; margin:12px 0;">
                    <div style="font-size:13px; margin-bottom: 4px;">现价: <b style="color:#ffffff;">${sig['current_price']}</b> ({sig['change_pct']}%)</div>
                    <div style="font-size:13px; margin-bottom: 4px;">⚡ 贴合买点: <b style="color:#ccff00;">${sig['near_market_buy']}</b></div>
                    <div style="font-size:13px; margin-bottom: 4px;">🎯 理想买点: <b style="color:#00ff66;">${sig['ideal_buy_price']}</b></div>
                    <div style="font-size:13px; margin-bottom: 4px;">🛡️ 动态止损位: <b style="color:#ff3366;">${sig['stop_loss']}</b></div>
                    <div style="font-size:13px;">🎉 目标止盈位: <b style="color:#00f0ff;">${sig['take_profit']}</b></div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"➕ 加入自选清单", use_container_width=True):
                    add_to_watchlist(sig['symbol'], sig['name'], "推荐自选")
                    st.success("已成功保存至自选表！")

            with right_col:
                rc1, rc2 = st.columns(2)
                with rc1:
                    st.markdown(f"""
                    <div class="tech-card">
                        <div class="metric-title">主线趋势状态 (Trend)</div>
                        <div style="font-size:15px; font-weight:700; color:#00f0ff; margin-top:5px;">{sig['trend_label']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="tech-card">
                        <div class="metric-title">MACD 交叉量能 (MACD)</div>
                        <div style="font-size:15px; font-weight:700; color:#00ff66; margin-top:5px;">{sig['macd_status']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with rc2:
                    st.markdown(f"""
                    <div class="tech-card">
                        <div class="metric-title">RSI 相对强弱 (RSI 14)</div>
                        <div style="font-size:15px; font-weight:700; color:#ab47bc; margin-top:5px;">{sig['rsi']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="tech-card">
                        <div class="metric-title">Supertrend 轨道 (Supertrend)</div>
                        <div style="font-size:15px; font-weight:700; color:#a996ef; margin-top:5px;">{sig['supertrend_signal']}</div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("---")
            st.plotly_chart(render_professional_chart(sig), use_container_width=True, config={'displayModeBar': False})

# --- 模式 3: 策略历史回测引擎 UI ---
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 策略历史回测 (Backtest Engine)")

    with st.form(key="backtest_form"):
        c_bt_sym, c_bt_cap, c_bt_btn = st.columns([2, 2, 1.5])
        with c_bt_sym:
            bt_symbol = st.text_input("回测代码", value=st.session_state.get('selected_ticker', 'NVDA')).upper().strip()
        with c_bt_cap:
            init_capital = st.number_input("初始资金 ($)", value=10000, step=1000)
        with c_bt_btn:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            run_bt = st.form_submit_button("🚀 回测", use_container_width=True)

    if run_bt or 'bt_metrics' in st.session_state:
        if run_bt:
            metrics, equity_df = run_backtest_engine(bt_symbol, initial_capital=float(init_capital), risk_reward_ratio=rr_ratio)
            st.session_state['bt_metrics'] = metrics
            st.session_state['bt_equity'] = equity_df

        metrics = st.session_state.get('bt_metrics')
        equity_df = st.session_state.get('bt_equity')

        if metrics and equity_df is not None:
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">累计总收益率</div>
                    <div style="font-size:16px; font-weight:700; color:#00ff66;">{metrics['total_return']}%</div>
                </div>""", unsafe_allow_html=True)
            with m2:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">策略胜率</div>
                    <div style="font-size:16px; font-weight:700; color:#00f0ff;">{metrics['win_rate']}%</div>
                </div>""", unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">历史最大回撤</div>
                    <div style="font-size:16px; font-weight:700; color:#ff3366;">{metrics['max_drawdown']}%</div>
                </div>""", unsafe_allow_html=True)
            with m4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">最终资产</div>
                    <div style="font-size:16px; font-weight:700; color:#ccff00;">${metrics['final_capital']:,.2f}</div>
                </div>""", unsafe_allow_html=True)

            fig_equity = go.Figure()
            fig_equity.add_trace(go.Scatter(x=equity_df['Date'], y=equity_df['Capital'], mode='lines', line=dict(color='#00f0ff', width=2)))
            fig_equity.update_layout(
                title=f"📈 {bt_symbol} 资产净值曲线",
                template="plotly_dark", paper_bgcolor='#0b0e14', plot_bgcolor='#161b22',
                height=350, margin=dict(l=10, r=10, t=35, b=10)
            )
            st.plotly_chart(fig_equity, use_container_width=True, config={'displayModeBar': False})

# --- 模式 4: 持仓自选清单监控 ---
elif app_mode == "📊 自选清单监控":
    st.markdown("### 📋 自选清单")
    df_w = get_watchlist()
    if df_w.empty:
        st.info("清单为空。")
    else:
        res = []
        for _, r in df_w.iterrows():
            s = fetch_advanced_quant_signals(r['symbol'], risk_reward_ratio=rr_ratio)
            if s:
                res.append({
                    "代码": s['symbol'],
                    "得分": s['quant_score'],
                    "评级": s['recommendation'],
                    "现价 ($)": s['current_price'],
                    "⚡ 贴合买点 ($)": s['near_market_buy'],
                    "🛡️ 止损 ($)": s['stop_loss'],
                    "🎉 止盈 ($)": s['take_profit']
                })
        if res:
            st.dataframe(pd.DataFrame(res), use_container_width=True, hide_index=True)
