# ============================================================================
# QuantumSignal PRO | 整合优化版 (Pro 2 引擎 + 旧版经典架构)
# ============================================================================

from dataclasses import dataclass, asdict
import math
import html
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf

# ----------------------------------------------------------------------------
# 1. 核心风控配置与数据清洗
# ----------------------------------------------------------------------------
VERSION = '2.1.0-Integrated'

@dataclass(frozen=True)
class Config:
    rr: float = 2.0
    risk_pct: float = 0.5
    max_position_pct: float = 20.0
    min_dollar_volume: float = 10_000_000
    min_price: float = 5.0
    max_atr_pct: float = 8.0
    min_score: int = 65
    fee_bps: float = 5.0
    slip_bps: float = 5.0

def clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d = d.loc[~d.index.duplicated(keep='last')].sort_index()
    fields = ['Open', 'High', 'Low', 'Close', 'Volume']
    for f in fields:
        if f not in d.columns:
            return pd.DataFrame()
    d = d[fields].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
    valid = (d[fields[:4]] > 0).all(axis=1) & (d.Volume >= 0)
    valid &= (d.High >= d[['Open', 'Close', 'Low']].max(axis=1)) & (d.Low <= d[['Open', 'Close', 'High']].min(axis=1))
    return d.loc[valid]

# ----------------------------------------------------------------------------
# 2. PRO 2 精确数学模型（Wilder, Supertrend, Indicators, Plan）
# ----------------------------------------------------------------------------
def wilder_smoothing(s: pd.Series, n: int = 14) -> pd.Series:
    a = s.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    for i in range(n - 1, len(a)):
        if i == n - 1 or np.isnan(out[i - 1]):
            if np.isfinite(a[i - n + 1:i + 1]).all():
                out[i] = a[i - n + 1:i + 1].mean()
        elif np.isfinite(a[i]):
            out[i] = (out[i - 1] * (n - 1) + a[i]) / n
    return pd.Series(out, index=s.index)

def calculate_indicators(frame: pd.DataFrame, benchmark: pd.DataFrame = None) -> pd.DataFrame:
    d = clean_ohlcv(frame)
    if d.empty or len(d) < 50:
        return d
    
    c, h, l, v = d.Close, d.High, d.Low, d.Volume
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d['ATR'] = wilder_smoothing(tr, 14)
    
    for n in (20, 50, 200):
        d[f'MA{n}'] = c.rolling(n).mean()
    d['EMA20'] = c.ewm(span=20, adjust=False).mean()
    
    delta = c.diff()
    gain = wilder_smoothing(delta.clip(lower=0), 14)
    loss = wilder_smoothing(-delta.clip(upper=0), 14)
    d['RSI'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    d.loc[(loss == 0) & (gain > 0), 'RSI'] = 100
    d.loc[(gain == 0) & (loss > 0), 'RSI'] = 0
    d.loc[(gain == 0) & (loss == 0), 'RSI'] = 50
    
    d['MACD'] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d['MACDSignal'] = d.MACD.ewm(span=9, adjust=False).mean()
    d['Hist'] = d.MACD - d.MACDSignal
    d['CrossUp'] = (d.MACD > d.MACDSignal) & (d.MACD.shift() <= d.MACDSignal.shift())
    d['CrossDown'] = (d.MACD < d.MACDSignal) & (d.MACD.shift() >= d.MACDSignal.shift())
    
    d['VWMA20'] = (((h + l + c) / 3) * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    d['Upper'] = d.MA20 + 2 * c.rolling(20).std()
    d['Lower'] = d.MA20 - 2 * c.rolling(20).std()
    d['DollarVolume'] = (c * v).rolling(20).mean()
    d['ATRpct'] = d.ATR / c * 100
    d['Support'] = l.rolling(20).min()
    d['Resistance'] = h.shift().rolling(20).max()
    d['Return63'] = c.pct_change(63, fill_method=None)
    
    if benchmark is not None and not benchmark.empty:
        b = clean_ohlcv(benchmark).Close.reindex(d.index)
        d['Relative63'] = d.Return63 - b.pct_change(63, fill_method=None)
        d['MarketOK'] = b > b.rolling(200).mean()
        d['MarketKnown'] = b.rolling(200).count().eq(200)
    else:
        d['Relative63'] = np.nan
        d['MarketOK'] = True
        d['MarketKnown'] = True
        
    # Supertrend 状态计算
    at10 = wilder_smoothing(tr, 10).to_numpy()
    ub = ((h + l) / 2).to_numpy() + 3 * at10
    lb = ((h + l) / 2).to_numpy() - 3 * at10
    fu, fl = ub.copy(), lb.copy()
    direction = np.zeros(len(d), dtype=int)
    line = np.full(len(d), np.nan)
    prices = c.to_numpy()
    
    for i in range(len(d)):
        if not np.isfinite(at10[i]): continue
        if i == 0 or not np.isfinite(at10[i - 1]):
            direction[i] = 1 if prices[i] >= (h.iloc[i] + l.iloc[i]) / 2 else -1
        else:
            fu[i] = ub[i] if ub[i] < fu[i - 1] or prices[i - 1] > fu[i - 1] else fu[i - 1]
            fl[i] = lb[i] if lb[i] > fl[i - 1] or prices[i - 1] < fl[i - 1] else fl[i - 1]
            direction[i] = direction[i - 1]
            if direction[i - 1] == -1 and prices[i] > fu[i]: direction[i] = 1
            elif direction[i - 1] == 1 and prices[i] < fl[i]: direction[i] = -1
        line[i] = fl[i] if direction[i] == 1 else fu[i]
        
    d['STDirection'], d['Supertrend'] = direction, line

    # 规则评分系统
    d['TrendScore'] = ((c > d.MA50).astype(int)*10 + (d.MA50 > d.MA200).astype(int)*10 + (d.MA50 > d.MA50.shift(10)).astype(int)*10)
    d['StrengthScore'] = np.select([d.Relative63 > .10, d.Relative63 > .03, d.Relative63 > 0], [20, 15, 10], default=0)
    d['MomentumScore'] = d.RSI.between(45, 65).astype(int)*10 + (d.Hist > 0).astype(int)*5 + (d.STDirection == 1).astype(int)*5
    d['LiquidityScore'] = np.select([d.DollarVolume >= 50e6, d.DollarVolume >= 10e6], [10, 5], default=0)
    d['VolatilityScore'] = np.select([d.ATRpct.between(1, 4), d.ATRpct.between(.3, 6)], [10, 5], default=0)
    d['MarketScore'] = d.MarketOK.astype(int)*10
    d['Score'] = d[[x for x in d if x.endswith('Score')]].sum(axis=1).astype(int)
    
    return d

def generate_plan(row: pd.Series, cfg: Config = Config()):
    required = ['Close', 'ATR', 'MA200', 'Support', 'EMA20', 'RSI']
    if any(not np.isfinite(row.get(k, np.nan)) for k in required) or row.ATR <= 0:
        return None
    entry = min(float(row.Close), float(row.EMA20))
    stop = min(entry - 1.5 * row.ATR, row.Support - 0.25 * row.ATR)
    risk = entry - stop
    target = entry + cfg.rr * risk
    reasons = []
    if row.Close < cfg.min_price: reasons.append('股价低于门槛')
    if row.DollarVolume < cfg.min_dollar_volume: reasons.append('成交额不足')
    if row.ATRpct > cfg.max_atr_pct: reasons.append('波动率过高')
    if not row.MarketOK: reasons.append('大盘弱于200日均线')
    if not (row.Close > row.MA50 > row.MA200): reasons.append('趋势未确认')
    if row.Score < cfg.min_score: reasons.append('综合评分不足')
    if row.RSI > 75: reasons.append('RSI过热')
    if risk > 4 * row.ATR: reasons.append('止损空间过大')
    if stop <= 0: reasons.append('止损价无效')
    
    return dict(entry=entry, stop=stop, target=target, risk=risk,
                eligible=not reasons, reasons=reasons, score=int(row.Score))

# ----------------------------------------------------------------------------
# 3. Streamlit 经典界面UI搭建
# ----------------------------------------------------------------------------
st.set_page_config(page_title='QuantumSignal PRO', page_icon='⚡', layout='wide')

st.title('⚡ QuantumSignal PRO 终端')
st.caption('融合高阶 Wilder/Supertrend 算法模型与经典极简分析界面')

# Sidebar 参数设置
st.sidebar.header('⚙️ 策略与风控参数')
rr_val = st.sidebar.slider('目标盈亏比 (RR)', 1.0, 5.0, 2.0, 0.5)
risk_pct_val = st.sidebar.slider('单笔风险预算 (%)', 0.1, 5.0, 0.5, 0.1)
min_score_val = st.sidebar.slider('最低入选评分', 40, 90, 65, 5)
min_vol_val = st.sidebar.number_input('最低20日均成交额(M$)', value=10.0) * 1e6

cfg = Config(rr=rr_val, risk_pct=risk_pct_val, min_score=min_score_val, min_dollar_volume=min_vol_val)

# 主页面输入
col_input, col_btn = st.columns([3, 1])
with col_input:
    symbol = st.text_input('股票代码 (如: NVDA, AAPL, TSLA)', value='NVDA').upper().strip()
with col_btn:
    st.write(' ')
    st.write(' ')
    run_btn = st.button('分析标的', type='primary')

@st.cache_data(ttl=3600*4)
def load_data(sym: str):
    df = yf.download(sym, period='2y', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(sym, axis=1, level=1) if sym in df.columns.get_level_values(1) else df.droplevel(1, axis=1)
    return df

@st.cache_data(ttl=3600*4)
def load_spy():
    spy = yf.download('SPY', period='2y', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy = spy.droplevel(1, axis=1)
    return spy

if symbol:
    try:
        raw_df = load_data(symbol)
        spy_df = load_spy()
        
        if raw_df.empty:
            st.error(f"无法获取代码 {symbol} 的行情数据。")
        else:
            df = calculate_indicators(raw_df, spy_df)
            latest = df.iloc[-1]
            p = generate_plan(latest, cfg)
            
            # 顶部 Metrics 卡片
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("最新收盘价", f"${latest.Close:.2f}")
            c2.metric("综合评分", f"{latest.Score} / 100")
            c3.metric("买入参考价", f"${p['entry']:.2f}" if p else "-")
            c4.metric("止损价", f"${p['stop']:.2f}" if p else "-")
            c5.metric("目标价", f"${p['target']:.2f}" if p else "-")
            
            if p:
                if p['eligible']:
                    st.success("✅ 满足全部筛选条件，建议列入回踩观察区。")
                else:
                    st.warning(f"⚠️ 未通过筛选因素：{'；'.join(p['reasons'])}")
            
            # Plotly 三阶融合图表
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
            
            # K线与均线
            fig.add_trace(go.Candlestick(x=df.index, open=df.Open, high=df.High, low=df.Low, close=df.Close, name='K线'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df.EMA20, name='EMA20', line=dict(color='#42caff', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df.MA50, name='MA50', line=dict(color='#e7c56b', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df.Supertrend, name='Supertrend', line=dict(color='#a996ef', width=1.5)), row=1, col=1)
            
            if p:
                fig.add_hline(y=p['entry'], line_dash='dash', line_color='#e7c56b', annotation_text='买入参考', row=1, col=1)
                fig.add_hline(y=p['stop'], line_dash='dash', line_color='#ff6f91', annotation_text='止损', row=1, col=1)
                fig.add_hline(y=p['target'], line_dash='dash', line_color='#45ddbc', annotation_text='目标', row=1, col=1)

            # MACD
            colors = ['#45ddbc' if val >= 0 else '#ff6f91' for val in df.Hist]
            fig.add_trace(go.Bar(x=df.index, y=df.Hist, name='MACD柱', marker_color=colors), row=2, col=1)
            
            # RSI
            fig.add_trace(go.Scatter(x=df.index, y=df.RSI, name='RSI', line=dict(color='#a996ef')), row=3, col=1)
            fig.add_hline(y=70, line_dash='dot', line_color='red', row=3, col=1)
            fig.add_hline(y=30, line_dash='dot', line_color='green', row=3, col=1)
            
            fig.update_layout(template='plotly_dark', height=650, margin=dict(l=10, r=10, t=20, b=10), showlegend=True)
            fig.update_xaxes(rangeslider_visible=False)
            
            st.plotly_chart(fig, use_container_state_dict=True, use_container_width=True)
            
    except Exception as e:
        st.error(f"处理数据时出错: {str(e)}")
