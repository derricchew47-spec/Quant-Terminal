import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. 页面配置与赛博黑客科技风 CSS
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
        background-color: #0d1117;
        color: #c9d1d9;
        font-family: 'Fira Code', monospace, -apple-system, sans-serif;
    }
    
    .tech-header {
        font-family: 'Fira Code', monospace;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);
        margin-bottom: 20px;
    }
    
    .tech-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        margin-bottom: 15px;
        position: relative;
    }
    
    .tech-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 2px;
        background: linear-gradient(90deg, #00f0ff, #7000ff);
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
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
        padding: 10px 14px;
        margin-bottom: 10px;
        border-radius: 4px;
    }

    /* Streamlit 原生组件覆盖 */
    .stTextInput input, .stNumberInput input, .stSelectbox div {
        background-color: #0d1117 !important;
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
# 2. 数据库与本地持仓列表
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

def remove_from_watchlist(symbol):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
    conn.commit()
    conn.close()

def get_watchlist():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM watchlist", conn)
    conn.close()
    return df

init_quant_db()

# -----------------------------------------------------------------------------
# 3. 双层买点与多维趋势判定算法引擎
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

        # --- A. 基础与均线指标 ---
        # 1. ATR (14)
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

        # 3. EMA10 (短线极速均线)
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        ema10 = float(df['EMA10'].iloc[-1])

        # 4. VWAP (机构成交量加权均价)
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
        macd_status = "🟢 金叉 (Bullish)" if macd_val > macd_sig else "🔴 死叉 (Bearish)"

        # 7. Supertrend (超级趋势算法)
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

        # 均线系统
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        ma20 = float(df['MA20'].iloc[-1])
        ma50 = float(df['MA50'].iloc[-1]) if len(df) >= 50 else ma20
        ma200 = float(df['MA200'].iloc[-1]) if len(df) >= 200 else ma50

        # --- B. 趋势判定算法矩阵 ---
        if current_price > ma20 and ma20 > ma50:
            trend_label = "🔥 强力多头 (Strong Uptrend)"
            trend_code = "UPTREND"
        elif current_price < ma20 and ma20 < ma50:
            trend_label = "❄️ 空头排列 (Downtrend Risk)"
            trend_code = "DOWNTREND"
        elif current_price > ma20 and current_price < ma50:
            trend_label = "↗️ 弱势反弹 (Weak Recovery)"
            trend_code = "RECOVERY"
        else:
            trend_label = "⚡ 宽幅震荡 (Sideways Consolidation)"
            trend_code = "SIDEWAYS"

        # --- C. 双层买点与止损止盈算价逻辑 ---
        # 1. 理想回调买点 (适合挂单做中长线/大回调)
        ideal_buy_price = min(lower_band, ma50)

        # 2. 贴合现价买点 (适合右侧建仓/防止漏单)
        if trend_code == "UPTREND":
            # 强多头模式：回调至 EMA10 或 VWAP 即为贴合买点，若现价已贴近则取现价回撤 0.5%
            near_market_buy = min(current_price, max(ema10, vwap, current_price * 0.992))
        elif trend_code == "SIDEWAYS":
            # 震荡模式：取 MA20 与 VWAP 的支撑均值
            near_market_buy = min(current_price, (ma20 + vwap) / 2)
        else:
            # 空头/反弹模式：贴合买点设为现价下撤 1 个 ATR 浮动
            near_market_buy = min(current_price, current_price - (0.5 * atr))

        # 止损止盈（基于贴合买点进行精准算价）
        stop_loss = near_market_buy - (2 * atr)
        take_profit = near_market_buy + (2 * atr * risk_reward_ratio)

        # --- D. 实时新闻与财报事件 ---
        news_list = []
        try:
            raw_news = ticker.news
            if raw_news:
                for item in raw_news[:5]:
                    news_list.append({
                        "title": item.get('title', 'No Title'),
                        "publisher": item.get('publisher', 'Unknown'),
                        "link": item.get('link', '#'),
                        "providerPublishTime": datetime.fromtimestamp(item.get('providerPublishTime', 0)).strftime('%m-%d %H:%M') if item.get('providerPublishTime') else ''
                    })
        except:
            pass

        calendar_date = "暂无数据"
        try:
            cal = ticker.calendar
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                calendar_date = str(cal['Earnings Date'][0])
            elif isinstance(cal, pd.DataFrame) and not cal.empty:
                calendar_date = str(cal.iloc[0, 0])
        except:
            pass

        info = ticker.info or {}
        market_cap = info.get('marketCap', 'N/A')
        pe_ratio = info.get('trailingPE', 'N/A')

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
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "news": news_list,
            "earnings_date": calendar_date,
            "pe_ratio": round(pe_ratio, 2) if isinstance(pe_ratio, (int, float)) else "N/A",
            "market_cap": f"{market_cap / 1e9:.2f} B" if isinstance(market_cap, (int, float)) else "N/A"
        }
    except Exception as e:
        return None

# -----------------------------------------------------------------------------
# 4. 图表渲染 (包含双买点轨)
# -----------------------------------------------------------------------------
def render_tech_chart(sig_data):
    df = sig_data['df'].tail(90)
    
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03,
        row_width=[0.2, 0.2, 0.6]
    )

    # 1. K 线图与布林带
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K-Line", increasing_line_color='#00ff66', decreasing_line_color='#ff3366'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(0,240,255,0.3)', width=1), name="Upper Band"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(0,240,255,0.3)', width=1), fill='tonexty', fillcolor='rgba(0,240,255,0.03)', name="Lower Band"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='#ff00ea', width=1.5, dash='dot'), name="VWAP"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['EMA10'], line=dict(color='#ccff00', width=1), name="EMA10"), row=1, col=1)

    # 标记买点线
    fig.add_hline(y=sig_data['near_market_buy'], line_dash="dash", line_color="#ccff00", annotation_text=" Near-Market Buy (贴合)", row=1, col=1)
    fig.add_hline(y=sig_data['ideal_buy_price'], line_dash="dash", line_color="#00ff66", annotation_text=" Ideal Dip Buy (理想)", row=1, col=1)
    fig.add_hline(y=sig_data['stop_loss'], line_dash="dash", line_color="#ff3366", annotation_text=" Stop Loss", row=1, col=1)

    # 2. RSI 副图
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#7000ff', width=1.5), name="RSI"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", row=2, col=1)

    # 3. MACD 副图
    colors = np.where(df['MACD_Hist'] >= 0, '#00ff66', '#ff3366')
    fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=colors, name="MACD Hist"), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#00f0ff', width=1), name="DIF"), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#ffaa00', width=1), name="DEA"), row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='#0d1117',
        plot_bgcolor='#161b22',
        margin=dict(l=10, r=10, t=10, b=10),
        height=620,
        showlegend=False,
        xaxis_rangeslider_visible=False
    )
    return fig

# -----------------------------------------------------------------------------
# 5. UI 交互界面
# -----------------------------------------------------------------------------
st.markdown('<h2 class="tech-header">⚡ QUANTUM TERMINAL PRO</h2>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🎛️ 终端模式选单")
    app_mode = st.radio("选择运行模式", ["🔍 实时算价与新闻观察", "📊 持仓/自选监控"])
    st.markdown("---")
    rr_ratio = st.slider("目标盈亏比 (Risk-Reward)", 1.0, 4.0, 2.0, 0.5)

# --- 模式 1: 单标的全方位算价 ---
if app_mode == "🔍 实时算价与新闻观察":
    c_in, c_b = st.columns([4, 1])
    with c_in:
        target_symbol = st.text_input("输入股票代码 (Ticker)", value="AAPL").upper().strip()
    with c_b:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        st.button("⚡ 运行全量分析", use_container_width=True)

    if target_symbol:
        sig = fetch_advanced_quant_signals(target_symbol, risk_reward_ratio=rr_ratio)
        if sig:
            # 顶部核心概况
            st.markdown(f"### 🎯 标的: **{sig['symbol']}** ({sig['name']}) | 趋势: `{sig['trend_label']}` | 📅 财报日: `{sig['earnings_date']}`")

            # 6 列核心指标看板（加入贴合买点）
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            with k1:
                color_str = "#00ff66" if sig['change_pct'] >= 0 else "#ff3366"
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">当前价格</div>
                    <div style="font-size:20px; font-weight:700; color:{color_str};">${sig['current_price']}</div>
                    <div style="font-size:11px; color:{color_str};">{sig['change_pct']}%</div>
                </div>""", unsafe_allow_html=True)

            with k2:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">⚡ 贴合现价买点</div>
                    <div class="metric-value-nearbuy">${sig['near_market_buy']}</div>
                    <div style="font-size:11px; color:#8b949e;">EMA10/VWAP支撑</div>
                </div>""", unsafe_allow_html=True)

            with k3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎯 理想回调买点</div>
                    <div class="metric-value-buy">${sig['ideal_buy_price']}</div>
                    <div style="font-size:11px; color:#8b949e;">布林下轨/MA50</div>
                </div>""", unsafe_allow_html=True)

            with k4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🛡️ 动态止损线</div>
                    <div class="metric-value-stop">${sig['stop_loss']}</div>
                    <div style="font-size:11px; color:#8b949e;">2x ATR 动态波动</div>
                </div>""", unsafe_allow_html=True)

            with k5:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎉 目标止盈线</div>
                    <div class="metric-value-take">${sig['take_profit']}</div>
                    <div style="font-size:11px; color:#8b949e;">盈亏比 1:{rr_ratio}</div>
                </div>""", unsafe_allow_html=True)

            with k6:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">📊 市值 & PE</div>
                    <div style="font-size:17px; font-weight:700; color:#00f0ff;">PE: {sig['pe_ratio']}</div>
                    <div style="font-size:11px; color:#8b949e;">{sig['market_cap']}</div>
                </div>""", unsafe_allow_html=True)

            # 主区：图表 + 算法状态 + 新闻
            c_chart, c_right = st.columns([2.5, 1.2])

            with c_chart:
                st.plotly_chart(render_tech_chart(sig), use_container_width=True)

            with c_right:
                st.markdown("#### 🤖 多维度量化算法状态")
                st.write(f"- **趋势定性**: `{sig['trend_label']}`")
                st.write(f"- **Supertrend**: `{sig['supertrend_signal']}`")
                st.write(f"- **MACD 信号**: `{sig['macd_status']}`")
                st.write(f"- **VWAP (机构成本)**: `${sig['vwap']}`")
                st.write(f"- **EMA10 (快线)**: `${sig['ema10']}`")
                st.write(f"- **RSI (14)**: `{sig['rsi']}`")
                
                st.markdown("---")
                st.markdown("#### 📰 实时追踪重大新闻")
                if sig['news']:
                    for n in sig['news']:
                        st.markdown(f"""
                        <div class="news-card">
                            <a href="{n['link']}" target="_blank" style="color:#c9d1d9; text-decoration:none; font-weight:600; font-size:12px;">{n['title']}</a>
                            <div style="font-size:10px; color:#8b949e; margin-top:4px;">来源: {n['publisher']} | {n['providerPublishTime']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.caption("暂未获取到最新报道新闻。")

                st.markdown("---")
                if st.button(f"➕ 加入监控清单", use_container_width=True):
                    add_to_watchlist(sig['symbol'], sig['name'], "自选观察")
                    st.success("已添加！")
        else:
            st.error(f"无法读取 `{target_symbol}` 数据，请确认代码是否有效。")

# --- 模式 2: 批量监控 ---
elif app_mode == "📊 持仓/自选监控":
    st.markdown("### 📋 监控清单多维度算法概览")
    df_w = get_watchlist()
    if df_w.empty:
        st.info("清单为空，请在模式1中添加标的。")
    else:
        res = []
        for _, r in df_w.iterrows():
            s = fetch_advanced_quant_signals(r['symbol'], risk_reward_ratio=rr_ratio)
            if s:
                res.append({
                    "代码": s['symbol'],
                    "现价 ($)": s['current_price'],
                    "⚡ 贴合买点 ($)": s['near_market_buy'],
                    "🎯 理想买点 ($)": s['ideal_buy_price'],
                    "🛡️ 止损位 ($)": s['stop_loss'],
                    "🎉 止盈位 ($)": s['take_profit'],
                    "趋势状态": s['trend_label'],
                    "Supertrend": s['supertrend_signal'],
                    "MACD": s['macd_status'],
                    "📅 财报日": s['earnings_date']
                })
        if res:
            st.dataframe(pd.DataFrame(res), use_container_width=True, hide_index=True)
