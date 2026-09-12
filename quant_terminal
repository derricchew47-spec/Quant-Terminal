import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime
import os

# -----------------------------------------------------------------------------
# 1. 页面配置与赛博黑客科技风 CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="QuantumSignal Terminal",
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
    
    /* 科技感主标题与卡片 */
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
        font-size: 12px;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .metric-value-buy {
        font-size: 22px;
        font-weight: 700;
        color: #00ff66;
        text-shadow: 0 0 8px rgba(0, 255, 102, 0.3);
    }
    
    .metric-value-stop {
        font-size: 22px;
        font-weight: 700;
        color: #ff3366;
        text-shadow: 0 0 8px rgba(255, 51, 102, 0.3);
    }
    
    .metric-value-take {
        font-size: 22px;
        font-weight: 700;
        color: #00f0ff;
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
    }

    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: #161b22 !important;
        border-right: 1px solid #30363d;
    }

    /* Streamlit 原生组件科技风覆盖 */
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

    div.stButton > button:hover {
        box-shadow: 0 0 25px rgba(0, 240, 255, 0.6) !important;
        transform: translateY(-1px);
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 数据库与本地持仓列表管理 (可选)
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
# 3. 核心量化算法引擎 (带缓存)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=900)
def fetch_quant_signals(symbol: str, risk_reward_ratio: float = 2.0, period: str = "1y"):
    """
    量化计算核心引擎:
    - ATR (14) 真实波动幅度
    - 布林带 (20, 2)
    - RSI (14) 相对强弱指标
    - 移动平均线 (MA20, MA50, MA200)
    """
    if not symbol or not symbol.strip():
        return None
    try:
        ticker = yf.Ticker(symbol.strip().upper())
        df = ticker.history(period=period)
        if df.empty or len(df) < 30:
            return None
        
        # 基础数据
        current_price = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2])
        change_pct = ((current_price - prev_close) / prev_close) * 100
        
        # 1. 计算 ATR (14)
        df['High-Low'] = df['High'] - df['Low']
        df['High-Close'] = np.abs(df['High'] - df['Close'].shift(1))
        df['Low-Close'] = np.abs(df['Low'] - df['Close'].shift(1))
        df['TR'] = df[['High-Low', 'High-Close', 'Low-Close']].max(axis=1)
        df['ATR'] = df['TR'].rolling(window=14).mean()
        atr = float(df['ATR'].iloc[-1])
        
        # 2. 计算布林带 (20, 2)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['MA20'] + (2 * df['STD20'])
        df['Lower_Band'] = df['MA20'] - (2 * df['STD20'])
        lower_band = float(df['Lower_Band'].iloc[-1])
        upper_band = float(df['Upper_Band'].iloc[-1])
        
        # 3. 计算 RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        rsi = float(df['RSI'].iloc[-1])
        
        # 4. 移动平均线
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        ma20 = float(df['MA20'].iloc[-1])
        ma50 = float(df['MA50'].iloc[-1]) if len(df) >= 50 else ma20
        ma200 = float(df['MA200'].iloc[-1]) if len(df) >= 200 else ma50

        # 5. 买点/止损点/止盈点算价逻辑
        # 相对较优买点取 现价 与 布林带下轨/20日均线支撑位 的重合交点
        good_buy_price = min(current_price, lower_band)
        stop_loss = current_price - (2 * atr)
        take_profit = current_price + (2 * atr * risk_reward_ratio)

        # 趋势判断
        if current_price > ma20 and ma20 > ma50:
            trend = "🔥 强力多头 (Bullish)"
        elif current_price < ma20 and ma20 < ma50:
            trend = "❄️ 空头排列 (Bearish)"
        else:
            trend = "⚡ 震荡盘整 (Consolidation)"

        return {
            "df": df,
            "symbol": symbol.upper().strip(),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "good_buy_price": round(good_buy_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "atr": round(atr, 2),
            "rsi": round(rsi, 1),
            "lower_band": round(lower_band, 2),
            "upper_band": round(upper_band, 2),
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "trend": trend
        }
    except Exception as e:
        return None

# -----------------------------------------------------------------------------
# 4. Plotly 赛博黑客风 K 线与量化图表
# -----------------------------------------------------------------------------
def render_tech_chart(sig_data):
    df = sig_data['df'].tail(90)  # 近 90 个交易日
    
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, subplot_titles=('', ''), 
        row_width=[0.25, 0.75]
    )

    # 1. K 线图
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="K-Line",
        increasing_line_color='#00ff66', decreasing_line_color='#ff3366'
    ), row=1, col=1)

    # 2. 布林带轨道
    fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(0,240,255,0.4)', width=1), name="Upper Band"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(0,240,255,0.4)', width=1), fill='tonexty', fillcolor='rgba(0,240,255,0.05)', name="Lower Band"), row=1, col=1)

    # 3. 关键位水平线 (买点/止损/止盈)
    fig.add_hline(y=sig_data['good_buy_price'], line_dash="dash", line_color="#00ff66", annotation_text=" Ideal Buy", row=1, col=1)
    fig.add_hline(y=sig_data['stop_loss'], line_dash="dash", line_color="#ff3366", annotation_text=" Stop Loss (2x ATR)", row=1, col=1)
    fig.add_hline(y=sig_data['take_profit'], line_dash="dash", line_color="#00f0ff", annotation_text=" Take Profit (1:2 RR)", row=1, col=1)

    # 4. RSI 副图
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#7000ff', width=2), name="RSI (14)"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#ff3366", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00ff66", row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='#0d1117',
        plot_bgcolor='#161b22',
        margin=dict(l=10, r=10, t=20, b=20),
        height=520,
        showlegend=False,
        xaxis_rangeslider_visible=False
    )
    return fig

# -----------------------------------------------------------------------------
# 5. 主界面与交互逻辑
# -----------------------------------------------------------------------------
st.markdown('<h2 class="tech-header">⚡ QUANTUM SIGNAL TERMINAL</h2>', unsafe_allow_html=True)
st.caption("🤖 极客量化交易终端：基于布林带、14日 ATR 动态波动率与 RSI 构建的智能算价系统")

# 侧边栏
with st.sidebar:
    st.markdown("### 🎛️ 终端控制面板")
    app_mode = st.radio("选择运行模式", ["🔍 任意代码实时算价", "📊 批量监控清单"])
    
    st.markdown("---")
    st.markdown("### ⚙️ 算法风控参数")
    rr_ratio = st.slider("目标盈亏比 (Risk-Reward)", min_value=1.0, max_value=4.0, value=2.0, step=0.5)
    atr_period = st.number_input("ATR 波动乘数", value=2.0, step=0.5)

# -----------------------------------------------------------------------------
# 模式 1：任意代码实时查询
# -----------------------------------------------------------------------------
if app_mode == "🔍 任意代码实时算价":
    c_input, c_btn = st.columns([4, 1])
    with c_input:
        target_symbol = st.text_input("ENTER TICKER SYMBOL", value="AAPL", placeholder="例如: TSLA, VT, NVDA, AMD, QQQ").upper().strip()
    with c_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        btn_calc = st.button("⚡ 执行计算", use_container_width=True)

    if target_symbol:
        sig = fetch_quant_signals(target_symbol, risk_reward_ratio=rr_ratio)
        if sig:
            # 顶部核心指标看板
            st.markdown(f"### 📈 标的：{sig['symbol']} | 趋势状态: `{sig['trend']}`")
            
            k1, k2, k3, k4, k5 = st.columns(5)
            with k1:
                color_str = "#00ff66" if sig['change_pct'] >= 0 else "#ff3366"
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">当前实时价格</div>
                    <div style="font-size:22px; font-weight:700; color:{color_str};">${sig['current_price']}</div>
                    <div style="font-size:11px; color:{color_str};">{sig['change_pct']}%</div>
                </div>
                """, unsafe_allow_html=True)

            with k2:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎯 理想买点 (超卖/支撑)</div>
                    <div class="metric-value-buy">${sig['good_buy_price']}</div>
                    <div style="font-size:11px; color:#8b949e;">布林下轨: ${sig['lower_band']}</div>
                </div>
                """, unsafe_allow_html=True)

            with k3:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🛡️ 动态止损位 ({atr_period}x ATR)</div>
                    <div class="metric-value-stop">${sig['stop_loss']}</div>
                    <div style="font-size:11px; color:#8b949e;">ATR 波动度: ${sig['atr']}</div>
                </div>
                """, unsafe_allow_html=True)

            with k4:
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">🎉 动态止盈位 (1:{rr_ratio:.1f})</div>
                    <div class="metric-value-take">${sig['take_profit']}</div>
                    <div style="font-size:11px; color:#8b949e;">基于 ATR 目标扩展</div>
                </div>
                """, unsafe_allow_html=True)

            with k5:
                rsi_color = "#ff3366" if sig['rsi'] >= 70 else ("#00ff66" if sig['rsi'] <= 30 else "#00f0ff")
                st.markdown(f"""
                <div class="tech-card">
                    <div class="metric-title">📊 强弱指标 (RSI 14)</div>
                    <div style="font-size:22px; font-weight:700; color:{rsi_color};">{sig['rsi']}</div>
                    <div style="font-size:11px; color:#8b949e;">30超卖 / 70超买</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

            # 图表与分析
            col_chart, col_info = st.columns([3, 1])
            with col_chart:
                st.plotly_chart(render_tech_chart(sig), use_container_width=True)

            with col_info:
                st.markdown("#### 🤖 算法决策建议")
                if sig['current_price'] <= sig['good_buy_price'] * 1.01:
                    st.success("🟢 **信号：极佳买入区间**\n当前价格已触及或接近布林带下轨支撑位，且风险收益比极佳。")
                elif sig['rsi'] >= 70:
                    st.warning("🔴 **信号：短线超买警示**\nRSI 指标高于 70，短线有回调压力，不建议追高。")
                elif sig['rsi'] <= 30:
                    st.info("🔵 **信号：严重超卖**\n技术面出现严重超卖，可关注反弹买点。")
                else:
                    st.caption("🟡 **信号：观望/按计划持股**\n价格处于正常波动通道内，建议在理想买点挂单。")

                st.markdown("---")
                st.markdown("#### 📐 均线系统视角")
                st.write(f"- **MA20 (月线)**: `${sig['ma20']}`")
                st.write(f"- **MA50 (季线)**: `${sig['ma50']}`")
                st.write(f"- **MA200 (年线)**: `${sig['ma200']}`")

                st.markdown("---")
                if st.button(f"➕ 将 {sig['symbol']} 加入监控清单", use_container_width=True):
                    add_to_watchlist(sig['symbol'], sig['symbol'], "自选关注")
                    st.success("已添加至监控清单！")
        else:
            st.error(f"❌ 无法获取代码 `{target_symbol}` 的行情数据，请检查代码是否正确（美股填 AAPL, TSLA 等）。")

# -----------------------------------------------------------------------------
# 模式 2：批量监控清单
# -----------------------------------------------------------------------------
elif app_mode == "📊 批量监控清单":
    st.markdown("### 📋 自选标的批量量化看板")
    df_watch = get_watchlist()
    
    with st.expander("➕ 添加新标的到监控清单"):
        w_c1, w_c2, w_c3 = st.columns(3)
        w_sym = w_c1.text_input("股票代码", placeholder="如: VT").upper()
        w_name = w_c2.text_input("自定义名称", placeholder="如: 先锋领航全球股")
        w_cat = w_c3.selectbox("分类", ["核心持仓", "卫星配置", "自选观察"])
        if st.button("确认添加"):
            if w_sym:
                add_to_watchlist(w_sym, w_name or w_sym, w_cat)
                st.success("添加成功！")
                st.rerun()

    if df_watch.empty:
        st.info("💡 监控清单为空，请先添加标的代码。")
    else:
        results = []
        for _, r in df_watch.iterrows():
            sig = fetch_quant_signals(r['symbol'], risk_reward_ratio=rr_ratio)
            if sig:
                results.append({
                    "代码": sig['symbol'],
                    "名称": r['name'],
                    "分类": r['category'],
                    "现价 ($)": sig['current_price'],
                    "涨跌 (%)": f"{sig['change_pct']}%",
                    "🎯 建议买点 ($)": sig['good_buy_price'],
                    "🛡️ 止损位 ($)": sig['stop_loss'],
                    "🎉 止盈位 ($)": sig['take_profit'],
                    "RSI (14)": sig['rsi'],
                    "趋势状态": sig['trend']
                })

        if results:
            df_res = pd.DataFrame(results)
            st.dataframe(df_res, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            d_sym = st.selectbox("选择要移除的标的代码", df_watch['symbol'].tolist())
            if st.button("🗑️ 从清单移除"):
                remove_from_watchlist(d_sym)
                st.success("已移除！")
                st.rerun()
