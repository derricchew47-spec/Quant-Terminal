import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. 页面配置与赛博黑客极简视觉样式 (Cyberpunk Dark Theme)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="QuantumSignal Terminal PRO",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
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
        margin-bottom: 20px;
    }
    
    .tech-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 14px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        margin-bottom: 12px;
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
        font-size: 20px;
        font-weight: 700;
        color: #00ff66;
        text-shadow: 0 0 8px rgba(0, 255, 102, 0.3);
    }

    .metric-value-nearbuy {
        font-size: 20px;
        font-weight: 700;
        color: #ccff00;
        text-shadow: 0 0 8px rgba(204, 255, 0, 0.3);
    }
    
    .metric-value-stop {
        font-size: 20px;
        font-weight: 700;
        color: #ff3366;
        text-shadow: 0 0 8px rgba(255, 51, 102, 0.3);
    }
    
    .metric-value-take {
        font-size: 20px;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
    }

    .news-card {
        background-color: #161b22;
        border-left: 3px solid #00f0ff;
        padding: 10px 12px;
        margin-bottom: 8px;
        border-radius: 4px;
    }

    /* Streamlit 原生组件覆盖 */
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
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.3) !important;
        transition: all 0.3s ease;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. SQLite 本地存储与数据库逻辑
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

# 默认高质量扫描候选池
DEFAULT_SCANNER_POOL = [
    "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOGL", "META", 
    "AMD", "AVGO", "PLTR", "QCOM", "SPY", "QQQ", "COIN", "SMCI"
]

# -----------------------------------------------------------------------------
# 3. 多维度量化指标计算 & 智能推选打分引擎 (Alpha Scoring Engine)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=900)
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

        # --- A. 技术指标族计算 ---
        # 1. ATR (真实波幅)
        df['High-Low'] = df['High'] - df['Low']
        df['High-Close'] = np.abs(df['High'] - df['Close'].shift(1))
        df['Low-Close'] = np.abs(df['Low'] - df['Close'].shift(1))
        df['TR'] = df[['High-Low', 'High-Close', 'Low-Close']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        atr = float(df['ATR'].iloc[-1])

        # 2. 布林带 (20, 2)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['MA20'] + (2 * df['STD20'])
        df['Lower_Band'] = df['MA20'] - (2 * df['STD20'])
        lower_band = float(df['Lower_Band'].iloc[-1])
        upper_band = float(df['Upper_Band'].iloc[-1])

        # 3. EMA10 (短期极速移动平均线)
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        ema10 = float(df['EMA10'].iloc[-1])

        # 4. VWAP (机构成交量加权成本线)
        df['VWAP'] = (df['Volume'] * (df['High'] + df['Low'] + df['Close']) / 3).cumsum() / df['Volume'].cumsum()
        vwap = float(df['VWAP'].iloc[-1])

        # 5. RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        rsi = float(df['RSI'].iloc[-1])

        # 6. MACD (12, 26, 9)
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        macd_val = float(df['MACD'].iloc[-1])
        macd_sig = float(df['MACD_Signal'].iloc[-1])
        is_macd_bullish = macd_val > macd_sig
        macd_status = "🟢 金叉 (Bullish)" if is_macd_bullish else "🔴 死叉 (Bearish)"

        # 7. Supertrend (超级趋势轨道)
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

        # 趋势均线系统
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        ma20 = float(df['MA20'].iloc[-1])
        ma50 = float(df['MA50'].iloc[-1]) if len(df) >= 50 else ma20

        # --- B. 趋势判定算法矩阵 ---
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

        # --- C. 双层买点算价逻辑 ---
        ideal_buy_price = min(lower_band, ma50)

        if trend_code == "UPTREND":
            near_market_buy = min(current_price, max(ema10, vwap, current_price * 0.992))
        elif trend_code == "SIDEWAYS":
            near_market_buy = min(current_price, (ma20 + vwap) / 2)
        else:
            near_market_buy = min(current_price, current_price - (0.5 * atr))

        stop_loss = near_market_buy - (2 * atr)
        take_profit = near_market_buy + (2 * atr * risk_reward_ratio)

        # --- D. 新闻情绪解析与提取 ---
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
        except:
            pass

        # --- E. 多维度量化推选评分模型 ---
        quant_score = 0
        if trend_code == "UPTREND":
            quant_score += 30
        elif trend_code == "RECOVERY":
            quant_score += 18
        elif trend_code == "SIDEWAYS":
            quant_score += 10

        price_gap_pct = abs(current_price - near_market_buy) / current_price * 100
        if price_gap_pct <= 1.0:
            quant_score += 30
        elif price_gap_pct <= 2.5:
            quant_score += 20
        elif price_gap_pct <= 4.0:
            quant_score += 12
        else:
            quant_score += 5

        if 48 <= rsi <= 65:
            quant_score += 20
        elif 35 <= rsi < 48:
            quant_score += 12
        elif rsi > 70:
            quant_score += 3

        if is_macd_bullish:
            quant_score += 5
        if supertrend_is_buy:
            quant_score += 5
        quant_score += min(10, max(-5, news_sentiment_score))

        quant_score = int(min(100, max(0, quant_score)))

        if quant_score >= 80:
            recommendation = "🔥 极力推荐 (High Alpha)"
        elif quant_score >= 65:
            recommendation = "👀 重点关注 (Watch Opportunity)"
        else:
            recommendation = "❄️ 观望/防守 (Avoid)"

        info = ticker.info or {}
        return {
            "df": df,
            "symbol": symbol.upper().strip(),
            "name": info.get('shortName', symbol.upper()),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "near_market_buy": round(near_market_buy, 2),
            "ideal_buy_price": round(ideal_buy_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "atr": round(atr, 2),
            "rsi": round(rsi, 1),
            "ema10": round(ema10, 2),
            "lower_band": round(lower_band, 2),
            "upper_band": round(upper_band, 2),
            "vwap": round(vwap, 2),
            "macd_status": macd_status,
            "supertrend_signal": supertrend_signal,
            "trend_label": trend_label,
            "quant_score": quant_score,
            "recommendation": recommendation,
            "news": news_list,
            "pe_ratio": round(info.get('trailingPE', 0), 2) if isinstance(info.get('trailingPE'), (int, float)) else "N/A"
        }
    except Exception:
        return None

# -----------------------------------------------------------------------------
# 4. 新增：内置轻量级历史回测引擎 (Backtest Engine)
# -----------------------------------------------------------------------------
def run_backtest_engine(symbol: str, initial_capital: float = 10000.0, risk_reward_ratio: float = 2.0, period: str = "2y"):
    ticker = yf.Ticker(symbol.upper().strip())
    df = ticker.history(period=period)
    if df.empty or len(df) < 50:
        return None, None

    # 计算所需基础指标
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    
    df['High-Low'] = df['High'] - df['Low']
    df['High-Close'] = np.abs(df['High'] - df['Close'].shift(1))
    df['Low-Close'] = np.abs(df['Low'] - df['Close'].shift(1))
    df['TR'] = df[['High-Low', 'High-Close', 'Low-Close']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=14).mean()

    # 回测变量初始化
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
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

        # 1. 持仓状态：检测止损或止盈
        if position > 0:
            if low <= stop_loss:  # 触发止损
                sell_price = stop_loss
                revenue = position * sell_price
                profit = revenue - (position * entry_price)
                capital += revenue
                trades.append({
                    "date": current_date, "type": "SELL (止损)", 
                    "price": round(sell_price, 2), "profit": round(profit, 2), "capital": round(capital, 2)
                })
                position = 0.0
            elif high >= take_profit:  # 触发止盈
                sell_price = take_profit
                revenue = position * sell_price
                profit = revenue - (position * entry_price)
                capital += revenue
                trades.append({
                    "date": current_date, "type": "SELL (止盈)", 
                    "price": round(sell_price, 2), "profit": round(profit, 2), "capital": round(capital, 2)
                })
                position = 0.0

        # 2. 空仓状态：寻找买入信号（金叉/均线支撑+趋势向上）
        if position == 0:
            is_uptrend = price > ma20 and ma20 > ma50
            if is_uptrend and price <= df['EMA10'].iloc[i] * 1.005:  # 回踩 EMA10 买入
                entry_price = price
                stop_loss = entry_price - (2 * atr)
                take_profit = entry_price + (2 * atr * risk_reward_ratio)
                position = capital / entry_price
                capital = 0.0  # 全仓模式
                trades.append({
                    "date": current_date, "type": "BUY", 
                    "price": round(entry_price, 2), "profit": 0.0, "capital": round(position * entry_price, 2)
                })

        # 记录每日总资产
        current_total = capital + (position * price)
        equity_curve.append({"Date": current_date, "Capital": current_total})

    equity_df = pd.DataFrame(equity_curve)
    
    # 算回测指标
    if not equity_df.empty:
        total_return = ((equity_df['Capital'].iloc[-1] - initial_capital) / initial_capital) * 100
        equity_df['Max_Capital'] = equity_df['Capital'].cummax()
        equity_df['Drawdown'] = (equity_df['Capital'] - equity_df['Max_Capital']) / equity_df['Max_Capital']
        max_drawdown = equity_df['Drawdown'].min() * 100
        
        # 胜率计算
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
# 5. 专业级三分栏画图引擎
# -----------------------------------------------------------------------------
def render_professional_chart(sig_data):
    df = sig_data['df'].tail(90)
    
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.04,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(
            f"📈 {sig_data['symbol']} 主图 (K线 / 均线 / VWAP / 买点轨道)", 
            "📊 MACD 动能量能柱", 
            "⚡ RSI 相对强弱动能 (带30/70预警)"
        )
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K线", increasing_line_color='#00ff66', decreasing_line_color='#ff3366'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='#ff00ea', width=1.2, dash='dot'), name="VWAP (机构成本)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA10'], line=dict(color='#00f0ff', width=1.2), name="EMA10 (短期快线)"), row=1, col=1)

    fig.add_hline(y=sig_data['near_market_buy'], line_dash="dash", line_color="#ccff00", annotation_text=" ⚡ Near-Market Buy (贴合)", row=1, col=1)
    fig.add_hline(y=sig_data['ideal_buy_price'], line_dash="dash", line_color="#00ff66", annotation_text=" 🎯 Ideal Dip Buy (理想)", row=1, col=1)
    fig.add_hline(y=sig_data['stop_loss'], line_dash="dash", line_color="#ff3366", annotation_text=" 🛡️ Stop Loss (止损)", row=1, col=1)

    colors = np.where(df['MACD_Hist'] >= 0, '#00ff66', '#ff3366')
    fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors, name="MACD Hist"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#00f0ff', width=1), name="DIF (快线)"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#ffaa00', width=1), name="DEA (慢线)"), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#ab47bc', width=1.5), name="RSI"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", opacity=0.7, row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", opacity=0.7, row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='#0b0e14',
        plot_bgcolor='#161b22',
        margin=dict(l=15, r=15, t=30, b=15),
        height=720,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        xaxis3_rangeslider_visible=False
    )
    
    fig.update_xaxes(showgrid=True, gridcolor='#21262d')
    fig.update_yaxes(showgrid=True, gridcolor='#21262d')

    return fig

# -----------------------------------------------------------------------------
# 6. Streamlit 用户交互 UI
# -----------------------------------------------------------------------------
st.markdown('<h2 class="tech-header">⚡ QUANTUM TERMINAL PRO</h2>', unsafe_allow_html=True)

if 'selected_ticker' not in st.session_state:
    st.session_state.selected_ticker = "NVDA"

with st.sidebar:
    st.markdown("### 🎛️ 终端功能选单")
    # 增加了回测引擎菜单选项
    app_mode = st.radio("选择运行模式", [
        "🚀 自动扫描 & 智能推荐", 
        "🔍 单标的全量诊断", 
        "🧪 策略历史回测引擎", 
        "📊 自选清单监控"
    ])
    st.markdown("---")
    rr_ratio = st.slider("目标盈亏比 (Risk-Reward)", 1.0, 4.0, 2.0, 0.5)

# --- 模式 1: 自动化全市场扫描推荐 ---
if app_mode == "🚀 自动扫描 & 智能推荐":
    st.markdown("### 🛰️ 量化自动扫描与多维强推荐榜单")
    st.caption("后台自动计算：**趋势强度 + 贴合现价买点 + 动能健康度 + 新闻情绪**，输出综合 Alpha 得分。")

    c_pool, c_btn = st.columns([4, 1.5])
    with c_pool:
        custom_pool = st.text_input("待扫描股票池 (以逗号分隔)", value=", ".join(DEFAULT_SCANNER_POOL))
    with c_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        run_scan = st.button("⚡ 启动全量扫描", use_container_width=True)

    symbols_to_scan = [s.strip().upper() for s in custom_pool.split(",") if s.strip()]

    if run_scan or 'scan_results' in st.session_state:
        if run_scan:
            progress_bar = st.progress(0)
            scan_data = []
            for idx, sym in enumerate(symbols_to_scan):
                sig = fetch_advanced_quant_signals(sym, risk_reward_ratio=rr_ratio)
                if sig:
                    scan_data.append(sig)
                progress_bar.progress((idx + 1) / len(symbols_to_scan))
            progress_bar.empty()
            scan_data.sort(key=lambda x: x['quant_score'], reverse=True)
            st.session_state.scan_results = scan_data

        results = st.session_state.scan_results

        if results:
            st.markdown("#### 🔥 今日量化得分最高 Top 3 推荐标的")
            top_cols = st.columns(min(3, len(results)))
            for i, col in enumerate(top_cols):
                res = results[i]
                with col:
                    st.markdown(f"""
                    <div class="tech-card">
                        <div style="font-size:11px; color:#00f0ff; font-weight:700;">TOP {i+1} RANKING</div>
                        <div style="font-size:20px; font-weight:700; color:#ffffff;">{res['symbol']} <span style="font-size:12px; color:#8b949e;">{res['name']}</span></div>
                        <div style="margin-top:6px;">
                            <span style="font-size:18px; font-weight:700; color:#ccff00;">综合得分: {res['quant_score']} / 100</span>
                        </div>
                        <div style="font-size:12px; margin-top:4px; color:#00ff66;">{res['recommendation']}</div>
                        <hr style="border-color:#30363d; margin:8px 0;">
                        <div style="font-size:11px; color:#8b949e;">现价: <b>${res['current_price']}</b></div>
                        <div style="font-size:11px; color:#ccff00;">⚡ 贴合买点: <b>${res['near_market_buy']}</b></div>
                        <div style="font-size:11px; color:#00ff66;">🎯 理想买点: <b>${res['ideal_buy_price']}</b></div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"查看 {res['symbol']} 三分栏图表", key=f"btn_top_{res['symbol']}"):
                        st.session_state.selected_ticker = res['symbol']

            st.markdown("---")
            st.markdown("#### 📊 全扫描池量化打分矩阵总表")
            
            table_rows = []
            for r in results:
                table_rows.append({
                    "代码": r['symbol'],
                    "综合得分": r['quant_score'],
                    "推荐评级": r['recommendation'],
                    "现价 ($)": r['current_price'],
                    "⚡ 贴合现价买点 ($)": r['near_market_buy'],
                    "🎯 理想回调买点 ($)": r['ideal_buy_price'],
                    "🛡️ 止损位 ($)": r['stop_loss'],
                    "🎉 止盈位 ($)": r['take_profit'],
                    "趋势状态": r['trend_label'],
                    "RSI": r['rsi'],
                    "MACD": r['macd_status']
                })
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# --- 模式 2: 单标的精细化诊断 ---
elif app_mode == "🔍 单标的全量诊断":
    st.markdown("### 🔍 标的精细量化算价与图表诊断")
    c_in, c_b = st.columns([4, 1])
    with c_in:
        target_symbol = st.text_input("输入股票代码 (Ticker)", value=st.session_state.selected_ticker).upper().strip()
    with c_b:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        st.button("⚡ 诊断标的", use_container_width=True)

    if target_symbol:
        sig = fetch_advanced_quant_signals(target_symbol, risk_reward_ratio=rr_ratio)
        if sig:
            st.markdown(f"### 🎯 标的: **{sig['symbol']}** ({sig['name']}) | 量化得分: `{sig['quant_score']}分` (`{sig['recommendation']}`)")

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            with k1:
                color_str = "#00ff66" if sig['change_pct'] >= 0 else "#ff3366"
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">当前价格</div>
                    <div style="font-size:18px; font-weight:700; color:{color_str};">${sig['current_price']}</div>
                    <div style="font-size:11px; color:{color_str};">{sig['change_pct']}%</div>
                </div>""", unsafe_allow_html=True)

            with k2:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">⚡ 贴合现价买点</div>
                    <div class="metric-value-nearbuy">${sig['near_market_buy']}</div>
                    <div style="font-size:10px; color:#8b949e;">EMA10/VWAP支撑</div>
                </div>""", unsafe_allow_html=True)

            with k3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎯 理想回调买点</div>
                    <div class="metric-value-buy">${sig['ideal_buy_price']}</div>
                    <div style="font-size:10px; color:#8b949e;">布林下轨/MA50</div>
                </div>""", unsafe_allow_html=True)

            with k4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🛡️ 动态止损线</div>
                    <div class="metric-value-stop">${sig['stop_loss']}</div>
                    <div style="font-size:10px; color:#8b949e;">2x ATR 动态保护</div>
                </div>""", unsafe_allow_html=True)

            with k5:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎉 目标止盈线</div>
                    <div class="metric-value-take">${sig['take_profit']}</div>
                    <div style="font-size:10px; color:#8b949e;">盈亏比 1:{rr_ratio}</div>
                </div>""", unsafe_allow_html=True)

            with k6:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">📊 动态 RSI (14)</div>
                    <div style="font-size:18px; font-weight:700; color:#00f0ff;">{sig['rsi']}</div>
                    <div style="font-size:10px; color:#8b949e;">相对强弱指标</div>
                </div>""", unsafe_allow_html=True)

            c_chart, c_right = st.columns([2.6, 1.2])
            with c_chart:
                st.plotly_chart(render_professional_chart(sig), use_container_width=True)

            with c_right:
                st.markdown("#### 🤖 多维度量化状态")
                st.write(f"- **综合推选评分**: `{sig['quant_score']} / 100`")
                st.write(f"- **趋势定性**: `{sig['trend_label']}`")
                st.write(f"- **Supertrend**: `{sig['supertrend_signal']}`")
                st.write(f"- **MACD 状态**: `{sig['macd_status']}`")
                st.write(f"- **VWAP (机构成本)**: `${sig['vwap']}`")
                st.write(f"- **EMA10 (快线)**: `${sig['ema10']}`")
                
                st.markdown("---")
                st.markdown("#### 📰 实时资讯与新闻")
                if sig['news']:
                    for n in sig['news']:
                        st.markdown(f"""
                        <div class="news-card">
                            <a href="{n['link']}" target="_blank" style="color:#c9d1d9; text-decoration:none; font-weight:600; font-size:11px;">{n['title']}</a>
                            <div style="font-size:9px; color:#8b949e; margin-top:3px;">{n['publisher']} | {n['providerPublishTime']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.caption("暂无实时关联新闻。")

                st.markdown("---")
                if st.button(f"➕ 加入自选清单", use_container_width=True):
                    add_to_watchlist(sig['symbol'], sig['name'], "推荐自选")
                    st.success("已成功保存！")

# --- 模式 3: 新增历史策略回测引擎 UI ---
elif app_mode == "🧪 策略历史回测引擎":
    st.markdown("### 🧪 策略历史回测与绩效分析 (Backtest Engine)")
    st.caption("基于您设定的盈亏比与买卖信号算法，对标的近 2 年的历史数据进行全量真实仿真回测。")

    c_bt_sym, c_bt_cap, c_bt_btn = st.columns([2, 2, 1.5])
    with c_bt_sym:
        bt_symbol = st.text_input("回测股票代码", value="NVDA").upper().strip()
    with c_bt_cap:
        init_capital = st.number_input("初始资金 ($)", value=10000, step=1000)
    with c_bt_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        run_bt = st.button("🚀 启动回测", use_container_width=True)

    if run_bt or 'bt_metrics' in st.session_state:
        if run_bt:
            with st.spinner("正在抓取历史数据计算回测绩效..."):
                metrics, equity_df = run_backtest_engine(bt_symbol, initial_capital=float(init_capital), risk_reward_ratio=rr_ratio)
                st.session_state.bt_metrics = metrics
                st.session_state.bt_equity = equity_df

        metrics = st.session_state.bt_metrics
        equity_df = st.session_state.bt_equity

        if metrics and equity_df is not None:
            # 渲染核心绩效 Card
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">初始资金</div>
                    <div style="font-size:18px; font-weight:700; color:#ffffff;">${metrics['initial_capital']:,.2f}</div>
                </div>""", unsafe_allow_html=True)
            with m2:
                ret_color = "#00ff66" if metrics['total_return'] >= 0 else "#ff3366"
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">累计总收益率</div>
                    <div style="font-size:18px; font-weight:700; color:{ret_color};">{metrics['total_return']}%</div>
                    <div style="font-size:10px; color:{ret_color};">最终资产: ${metrics['final_capital']:,.2f}</div>
                </div>""", unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">策略胜率</div>
                    <div style="font-size:18px; font-weight:700; color:#00f0ff;">{metrics['win_rate']}%</div>
                    <div style="font-size:10px; color:#8b949e;">总交易次数: {metrics['total_trades']} 次</div>
                </div>""", unsafe_allow_html=True)
            with m4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">历史最大回撤</div>
                    <div style="font-size:18px; font-weight:700; color:#ff3366;">{metrics['max_drawdown']}%</div>
                    <div style="font-size:10px; color:#8b949e;">风控安全阀</div>
                </div>""", unsafe_allow_html=True)
            with m5:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">盈亏比设定</div>
                    <div style="font-size:18px; font-weight:700; color:#ccff00;">1 : {rr_ratio}</div>
                    <div style="font-size:10px; color:#8b949e;">动态 ATR 追踪</div>
                </div>""", unsafe_allow_html=True)

            # 资金增长曲线图
            fig_equity = go.Figure()
            fig_equity.add_trace(go.Scatter(
                x=equity_df['Date'], y=equity_df['Capital'], 
                mode='lines', line=dict(color='#00f0ff', width=2),
                name='账户总资产'
            ))
            fig_equity.update_layout(
                title=f"📈 {bt_symbol} 策略资产净值曲线 (Equity Curve)",
                template="plotly_dark",
                paper_bgcolor='#0b0e14',
                plot_bgcolor='#161b22',
                height=450,
                margin=dict(l=15, r=15, t=40, b=15)
            )
            st.plotly_chart(fig_equity, use_container_width=True)
        else:
            st.error("数据不足或无法完成回测，请换个股票代码重试。")

# --- 模式 4: 持仓自选清单监控 ---
elif app_mode == "📊 自选清单监控":
    st.markdown("### 📋 本地自选清单量化矩阵")
    df_w = get_watchlist()
    if df_w.empty:
        st.info("清单为空，请在上方模式中添加自选标的。")
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
                    "🎯 理想买点 ($)": s['ideal_buy_price'],
                    "🛡️ 止损位 ($)": s['stop_loss'],
                    "🎉 止盈位 ($)": s['take_profit'],
                    "趋势状态": s['trend_label'],
                    "MACD": s['macd_status']
                })
        if res:
            st.dataframe(pd.DataFrame(res), use_container_width=True, hide_index=True)
