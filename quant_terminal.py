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
    initial_sidebar_state="collapsed"  # 手机端默认折叠侧边栏，提升首次开屏渲染速度
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

    .news-card {
        background-color: #161b22;
        border-left: 3px solid #00f0ff;
        padding: 8px 10px;
        margin-bottom: 6px;
        border-radius: 4px;
    }

    /* 侧边栏按钮样式 */
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
# 2. State 初始化 & 懒加载预设池字典
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

# 优化1：高时长 TTL 缓存（24小时），避免移动网络重复请求 Wikipedia 网页
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
# 4. 多维度量化指标计算 & 智能推选打分引擎
# -----------------------------------------------------------------------------
# 优化2：隐藏加载 Spinners，提升手机流畅度
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_advanced_quant_signals(symbol: str, risk_reward_ratio: float = 2.0, period: str = "1y"):
    if not symbol or not symbol.strip():
        return None
    try:
        ticker = yf.Ticker(symbol.strip().upper())
        df = ticker.history(period=period)
        if df.empty or len(df) < 35:
            return None
        
        current_price = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2])
        change_pct = ((current_price - prev_close) / prev_close) * 100

        df['High-Low'] = df['High'] - df['Low']
        df['High-Close'] = np.abs(df['High'] - df['Close'].shift(1))
        df['Low-Close'] = np.abs(df['Low'] - df['Close'].shift(1))
        df['TR'] = df[['High-Low', 'High-Close', 'Low-Close']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        atr = float(df['ATR'].iloc[-1])

        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['MA20'] + (2 * df['STD20'])
        df['Lower_Band'] = df['MA20'] - (2 * df['STD20'])
        lower_band = float(df['Lower_Band'].iloc[-1])
        upper_band = float(df['Upper_Band'].iloc[-1])

        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        ema10 = float(df['EMA10'].iloc[-1])
        df['VWAP'] = (df['Volume'] * (df['High'] + df['Low'] + df['Close']) / 3).cumsum() / df['Volume'].cumsum()
        vwap = float(df['VWAP'].iloc[-1])

        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        rsi = float(df['RSI'].iloc[-1])

        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        macd_val = float(df['MACD'].iloc[-1])
        macd_sig = float(df['MACD_Signal'].iloc[-1])
        is_macd_bullish = macd_val > macd_sig
        macd_status = "🟢 金叉 (Bullish)" if is_macd_bullish else "🔴 死叉 (Bearish)"

        st_multiplier, st_period = 3.0, 10
        hl2 = (df['High'] + df['Low']) / 2
        df['Basic_UB'] = hl2 + (st_multiplier * df['ATR'])
        df['Basic_LB'] = hl2 - (st_multiplier * df['ATR'])
        df['Final_UB'] = 0.0
        df['Final_LB'] = 0.0
        for i in range(1, len(df)):
            df.loc[df.index[i], 'Final_UB'] = df['Basic_UB'].iloc[i] if (df['Basic_UB'].iloc[i] < df['Final_UB'].iloc[i-1] or df['Close'].iloc[i-1] > df['Final_UB'].iloc[i-1]) else df['Final_UB'].iloc[i-1]
            df.loc[df.index[i], 'Final_LB'] = df['Basic_LB'].iloc[i] if (df['Basic_LB'].iloc[i] > df['Final_LB'].iloc[i-1] or df['Close'].iloc[i-1] < df['Final_LB'].iloc[i-1]) else df['Final_LB'].iloc[i-1]
        supertrend_is_buy = current_price > df['Final_UB'].iloc[-1]
        supertrend_signal = "🟢 多头轨道 (BUY)" if supertrend_is_buy else "🔴 空头轨道 (SELL)"

        df['MA50'] = df['Close'].rolling(window=50).mean()
        ma20 = float(df['MA20'].iloc[-1])
        ma50 = float(df['MA50'].iloc[-1]) if len(df) >= 50 else ma20

        if current_price > ma20 and ma20 > ma50:
            trend_label = "🔥 强力多头 (Strong Uptrend)"
            trend_code = "UPTREND"
        elif current_price < ma20 and ma20 < ma50:
            trend_label = "❄️ 降维空头 (Downtrend Risk)"
            trend_code = "DOWNTREND"
        elif current_price > ma20 and current_price < ma50:
            trend_label = "↗️ 弱势反弹 (Weak Recovery)"
            trend_code = "RECOVERY"
        else:
            trend_label = "⚡ 宽幅震荡 (Sideways)"
            trend_code = "SIDEWAYS"

        ideal_buy_price = min(lower_band, ma50)
        if trend_code == "UPTREND":
            near_market_buy = min(current_price, max(ema10, vwap, current_price * 0.992))
        elif trend_code == "SIDEWAYS":
            near_market_buy = min(current_price, (ma20 + vwap) / 2)
        else:
            near_market_buy = min(current_price, current_price - (0.5 * atr))

        stop_loss = near_market_buy - (2 * atr)
        take_profit = near_market_buy + (2 * atr * risk_reward_ratio)

        news_list = []
        news_sentiment_score = 0
        try:
            raw_news = ticker.news
            if raw_news:
                for item in raw_news[:5]:
                    title = item.get('title', '')
                    news_list.append({
                        "title": title if title else 'No Title',
                        "publisher": item.get('publisher', 'Unknown'),
                        "link": item.get('link', '#'),
                        "providerPublishTime": datetime.fromtimestamp(item.get('providerPublishTime', 0)).strftime('%m-%d %H:%M') if item.get('providerPublishTime') else ''
                    })
                    title_upper = title.upper()
                    if any(w in title_upper for w in ['RECORD', 'SURGE', 'BEAT', 'GROWTH', 'RAISE', 'BULL']):
                        news_sentiment_score += 3
                    elif any(w in title_upper for w in ['DROP', 'MISS', 'CUT', 'DOWN', 'RISK', 'BEAR']):
                        news_sentiment_score -= 3
        except Exception:
            pass

        quant_score = 0
        if trend_code == "UPTREND": quant_score += 30
        elif trend_code == "RECOVERY": quant_score += 18
        elif trend_code == "SIDEWAYS": quant_score += 10

        price_gap_pct = abs(current_price - near_market_buy) / current_price * 100
        if price_gap_pct <= 1.0: quant_score += 30
        elif price_gap_pct <= 2.5: quant_score += 20
        elif price_gap_pct <= 4.0: quant_score += 12
        else: quant_score += 5

        if 48 <= rsi <= 65: quant_score += 20
        elif 35 <= rsi < 48: quant_score += 12
        elif rsi > 70: quant_score += 3

        if is_macd_bullish: quant_score += 5
        if supertrend_is_buy: quant_score += 5
        quant_score += min(10, max(-5, news_sentiment_score))
        quant_score = int(min(100, max(0, quant_score)))

        if quant_score >= 80: recommendation = "🔥 极力推荐 (High Alpha)"
        elif quant_score >= 65: recommendation = "👀 重点关注 (Watch Opportunity)"
        else: recommendation = "❄️ 观望/防守 (Avoid)"

        info = ticker.info or {}
        return {
            "df": df, "symbol": symbol.upper().strip(),
            "name": info.get('shortName', symbol.upper()),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "near_market_buy": round(near_market_buy, 2),
            "ideal_buy_price": round(ideal_buy_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "atr": round(atr, 2), "rsi": round(rsi, 1),
            "ema10": round(ema10, 2), "lower_band": round(lower_band, 2),
            "upper_band": round(upper_band, 2), "vwap": round(vwap, 2),
            "macd_status": macd_status, "supertrend_signal": supertrend_signal,
            "trend_label": trend_label, "quant_score": quant_score,
            "recommendation": recommendation, "news": news_list
        }
    except Exception:
        return None

# -----------------------------------------------------------------------------
# 5. 高级历史回测引擎 (带移动止损与突破双重触发)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def run_backtest_engine(symbol: str, initial_capital: float = 10000.0, risk_reward_ratio: float = 2.0, period: str = "2y"):
    ticker = yf.Ticker(symbol.upper().strip())
    df = ticker.history(period=period)
    if df.empty or len(df) < 50:
        return None, None

    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    
    df['High-Low'] = df['High'] - df['Low']
    df['High-Close'] = np.abs(df['High'] - df['Close'].shift(1))
    df['Low-Close'] = np.abs(df['Low'] - df['Close'].shift(1))
    df['TR'] = df[['High-Low', 'High-Close', 'Low-Close']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=14).mean()

    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    stop_loss = 0.0
    highest_price_after_entry = 0.0
    trades = []
    equity_curve = []

    for i in range(50, len(df)):
        current_date = df.index[i]
        price = df['Close'].iloc[i]
        high = df['High'].iloc[i]
        low = df['Low'].iloc[i]
        atr = df['ATR'].iloc[i]
        ma20 = df['MA20'].iloc[i]
        ma50 = df['MA50'].iloc[i]
        ema5 = df['EMA5'].iloc[i]

        if position > 0:
            highest_price_after_entry = max(highest_price_after_entry, high)
            trailing_stop = highest_price_after_entry - (2.0 * atr)
            stop_loss = max(stop_loss, trailing_stop)

            if low <= stop_loss or price < ma20:
                sell_price = min(price, stop_loss) if low <= stop_loss else price
                revenue = position * sell_price
                profit = revenue - (position * entry_price)
                capital += revenue
                trades.append({
                    "date": current_date, 
                    "type": "SELL (移动止损/趋势离场)", 
                    "price": round(sell_price, 2), 
                    "profit": round(profit, 2), 
                    "capital": round(capital, 2)
                })
                position = 0.0

        if position == 0:
            is_uptrend = price > ma20 and ma20 > ma50
            is_dip_buy = (price <= ema5 * 1.01)
            is_breakout = (price >= df['High'].iloc[i-20:i].max())

            if is_uptrend and (is_dip_buy or is_breakout):
                entry_price = price
                highest_price_after_entry = high
                stop_loss = entry_price - (1.8 * atr)
                
                position = capital / entry_price
                capital = 0.0
                trades.append({
                    "date": current_date, 
                    "type": "BUY", 
                    "price": round(entry_price, 2), 
                    "profit": 0.0, 
                    "capital": round(position * entry_price, 2)
                })

        current_total = capital + (position * price)
        equity_curve.append({"Date": current_date, "Capital": current_total})

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
# 6. 移动端轻量级画图引擎 (渲染节点减半，禁用全屏卡顿工具条)
# -----------------------------------------------------------------------------
def render_professional_chart(sig_data):
    # 优化3：手机端限制只渲染最新 45 天 K 线，体积缩小一倍，秒级渲染
    df = sig_data['df'].tail(45)
    
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

    fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='#ff00ea', width=1.2, dash='dot'), name="VWAP"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA10'], line=dict(color='#00f0ff', width=1.2), name="EMA10"), row=1, col=1)

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
        margin=dict(l=10, r=10, t=25, b=10), height=550, showlegend=False, # 隐藏图例提高手机屏幕利用率
        xaxis3_rangeslider_visible=False
    )
    fig.update_xaxes(showgrid=True, gridcolor='#21262d')
    fig.update_yaxes(showgrid=True, gridcolor='#21262d')
    return fig

# -----------------------------------------------------------------------------
# 7. UI 主体逻辑与无卡顿交互路由
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

    # 优化4：懒加载逻辑，在需要标普500数据时才去调用，避免首页加载超时
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

# --- 模式 2: 单标的精细化诊断 ---
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
            st.markdown(f"**{sig['symbol']}** ({sig['name']}) | 得分: `{sig['quant_score']}分` (`{sig['recommendation']}`)")

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                color_str = "#00ff66" if sig['change_pct'] >= 0 else "#ff3366"
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">当前价格</div>
                    <div style="font-size:16px; font-weight:700; color:{color_str};">${sig['current_price']}</div>
                </div>""", unsafe_allow_html=True)

            with k2:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">⚡ 贴合现价买点</div>
                    <div class="metric-value-nearbuy">${sig['near_market_buy']}</div>
                </div>""", unsafe_allow_html=True)

            with k3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🛡️ 动态止损线</div>
                    <div class="metric-value-stop">${sig['stop_loss']}</div>
                </div>""", unsafe_allow_html=True)

            with k4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎉 目标止盈线</div>
                    <div class="metric-value-take">${sig['take_profit']}</div>
                </div>""", unsafe_allow_html=True)

            st.plotly_chart(render_professional_chart(sig), use_container_width=True, config={'displayModeBar': False})

            st.markdown("#### 🤖 量化指标状态")
            st.write(f"- **趋势**: `{sig['trend_label']}` | **RSI**: `{sig['rsi']}` | **MACD**: `{sig['macd_status']}`")

            if st.button(f"➕ 加入自选清单", use_container_width=True):
                add_to_watchlist(sig['symbol'], sig['name'], "推荐自选")
                st.success("已成功保存！")

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
