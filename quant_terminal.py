"""Pure daily-bar indicators and an explicitly sequenced long-only simulator."""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

VERSION = '2.0.0'

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

    def __post_init__(self):
        if not (1 <= self.rr <= 5 and 0 < self.risk_pct <= 5 and 0 < self.max_position_pct <= 100):
            raise ValueError('Invalid risk settings')
        if min(self.fee_bps, self.slip_bps, self.min_dollar_volume, self.min_price) < 0:
            raise ValueError('Negative parameters')


def clean(frame):
    d = frame.copy()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d = d.loc[~d.index.duplicated(keep='last')].sort_index()
    fields = ['Open', 'High', 'Low', 'Close', 'Volume']
    d = d[fields].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
    valid = (d[fields[:4]] > 0).all(axis=1) & (d.Volume >= 0)
    valid &= (d.High >= d[['Open','Close','Low']].max(axis=1)) & (d.Low <= d[['Open','Close','High']].min(axis=1))
    return d.loc[valid]


def wilder(s, n=14):
    """Wilder smoothing with an SMA seed, not an arbitrary first observation."""
    a = s.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    for i in range(n-1, len(a)):
        if i == 0 or np.isnan(out[i-1]):
            if np.isfinite(a[i-n+1:i+1]).all():
                out[i] = a[i-n+1:i+1].mean()
        elif np.isfinite(a[i]):
            out[i] = (out[i-1]*(n-1) + a[i])/n
    return pd.Series(out, index=s.index)


def indicators(frame, benchmark=None):
    d = clean(frame)
    c, h, l, v = d.Close, d.High, d.Low, d.Volume
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    d['ATR'] = wilder(tr)
    for n in (20,50,200):
        d[f'MA{n}'] = c.rolling(n).mean()
    d['EMA20'] = c.ewm(span=20, adjust=False).mean()
    delta = c.diff()
    gain, loss = wilder(delta.clip(lower=0)), wilder(-delta.clip(upper=0))
    d['RSI'] = 100 - 100/(1 + gain/loss.replace(0, np.nan))
    d.loc[(loss == 0) & (gain > 0), 'RSI'] = 100
    d.loc[(gain == 0) & (loss > 0), 'RSI'] = 0
    d.loc[(gain == 0) & (loss == 0), 'RSI'] = 50
    d['MACD'] = c.ewm(span=12, adjust=False).mean()-c.ewm(span=26, adjust=False).mean()
    d['MACDSignal'] = d.MACD.ewm(span=9, adjust=False).mean()
    d['Hist'] = d.MACD-d.MACDSignal
    d['CrossUp'] = (d.MACD > d.MACDSignal) & (d.MACD.shift() <= d.MACDSignal.shift())
    d['CrossDown'] = (d.MACD < d.MACDSignal) & (d.MACD.shift() >= d.MACDSignal.shift())
    # Rolling volume weighted typical price, deliberately not called session VWAP.
    d['VWMA20'] = (((h+l+c)/3)*v).rolling(20).sum()/v.rolling(20).sum().replace(0,np.nan)
    d['Upper'] = d.MA20 + 2*c.rolling(20).std()
    d['Lower'] = d.MA20 - 2*c.rolling(20).std()
    d['DollarVolume'] = (c*v).rolling(20).mean()
    d['RelVolume'] = v/v.shift().rolling(20).mean().replace(0,np.nan)
    d['ATRpct'] = d.ATR/c*100
    d['Support'] = l.rolling(20).min()
    d['Resistance'] = h.shift().rolling(20).max()
    d['Return63'] = c.pct_change(63, fill_method=None)
    # Require same-session benchmark observations; do not forward-fill stale prices.
    if benchmark is not None and not benchmark.empty:
        b = clean(benchmark).Close.reindex(d.index)
        d['Relative63'] = d.Return63-b.pct_change(63, fill_method=None)
        d['MarketOK'] = b > b.rolling(200).mean()
        d['MarketKnown'] = b.rolling(200).count().eq(200)
    else:
        d['Relative63'] = np.nan
        d['MarketOK'] = False
        d['MarketKnown'] = False
    # Supertrend: valid ATR seed, final bands, then persistent direction state.
    at10 = wilder(tr,10).to_numpy()
    ub = ((h+l)/2).to_numpy()+3*at10
    lb = ((h+l)/2).to_numpy()-3*at10
    fu, fl = ub.copy(), lb.copy()
    direction = np.zeros(len(d), dtype=int)
    line = np.full(len(d),np.nan)
    prices = c.to_numpy()
    for i in range(len(d)):
        if not np.isfinite(at10[i]):
            continue
        if i == 0 or not np.isfinite(at10[i-1]):
            direction[i] = 1 if prices[i] >= (h.iloc[i]+l.iloc[i])/2 else -1
        else:
            fu[i] = ub[i] if ub[i] < fu[i-1] or prices[i-1] > fu[i-1] else fu[i-1]
            fl[i] = lb[i] if lb[i] > fl[i-1] or prices[i-1] < fl[i-1] else fl[i-1]
            direction[i] = direction[i-1]
            if direction[i-1] == -1 and prices[i] > fu[i]: direction[i] = 1
            elif direction[i-1] == 1 and prices[i] < fl[i]: direction[i] = -1
        line[i] = fl[i] if direction[i] == 1 else fu[i]
    d['STDirection'], d['Supertrend'] = direction, line
    # Fixed, inspectable weights; a score is NOT a probability or estimated alpha.
    d['TrendScore'] = ((c > d.MA50).astype(int)*10 + (d.MA50 > d.MA200).astype(int)*10 +
                       (d.MA50 > d.MA50.shift(10)).astype(int)*10)
    d['StrengthScore'] = np.select([d.Relative63 > .10,d.Relative63 > .03,d.Relative63 > 0],[20,15,10],default=0)
    d['MomentumScore'] = d.RSI.between(45,65).astype(int)*10 + (d.Hist > 0).astype(int)*5 + (d.STDirection == 1).astype(int)*5
    d['LiquidityScore'] = np.select([d.DollarVolume >= 50e6,d.DollarVolume >= 10e6],[10,5],default=0)
    d['VolatilityScore'] = np.select([d.ATRpct.between(1,4),d.ATRpct.between(.3,6)],[10,5],default=0)
    d['MarketScore'] = d.MarketOK.astype(int)*10
    d['Score'] = d[[x for x in d if x.endswith('Score')]].sum(axis=1).astype(int)
    return d


def plan(row, cfg=Config()):
    required = ['Close','ATR','MA200','Support','EMA20','RSI']
    if any(not np.isfinite(row[k]) for k in required) or row.ATR <= 0:
        return None
    entry = min(float(row.Close),float(row.EMA20))
    # Structural stop with a minimum volatility buffer; excessive distance is filtered.
    stop = min(entry-1.5*row.ATR, row.Support-.25*row.ATR)
    risk = entry-stop
    target = entry+cfg.rr*risk
    reasons = []
    if row.Close < cfg.min_price: reasons.append('价格低于门槛')
    if row.DollarVolume < cfg.min_dollar_volume: reasons.append('成交额不足')
    if row.ATRpct > cfg.max_atr_pct: reasons.append('波动率过高')
    if not row.MarketKnown: reasons.append('大盘数据不足')
    elif not row.MarketOK: reasons.append('SPY低于200日均线')
    if not (row.Close > row.MA50 > row.MA200): reasons.append('趋势未确认')
    if row.Score < cfg.min_score: reasons.append('评分不足')
    if row.RSI > 75: reasons.append('RSI过热')
    if risk > 4*row.ATR: reasons.append('结构止损距离过大')
    if stop <= 0: reasons.append('止损无效')
    if entry < row.Close-2*row.ATR: reasons.append('回踩区距离过远')
    return dict(entry=entry,stop=stop,target=target,risk=risk,
                entry_low=max(stop+.1*risk,entry-.25*row.ATR),
                eligible=not reasons,reasons=reasons,score=int(row.Score))


def quantity(cash, entry, stop, cfg):
    fee, slip = cfg.fee_bps/1e4, cfg.slip_bps/1e4
    # Stop slippage + round-trip fees included in sizing; gaps can exceed the budget.
    per_share = entry-stop*(1-slip)+fee*(entry+stop*(1-slip))
    if cash <= 0 or stop <= 0 or per_share <= 0: return 0
    return max(0,math.floor(min(cash*cfg.risk_pct/100/per_share,
                                cash*cfg.max_position_pct/100/(entry*(1+fee)))))


def summary(symbol, d, cfg):
    if len(d) < 210: raise ValueError('至少需要210个有效交易日')
    r = d.iloc[-1]
    p = plan(r,cfg)
    if p is None: raise ValueError('指标无效/ATR为零')
    return {'代码':symbol,'评分':p['score'],'状态':'候选：等待回踩' if p['eligible'] else '观察',
            '收盘价':float(r.Close),'买入参考':p['entry'],'止损':p['stop'],'目标':p['target'],
            'RSI':float(r.RSI),'ATR%':float(r.ATRpct),'20日成交额':float(r.DollarVolume),
            '相对SPY63日%':float(r.Relative63*100) if np.isfinite(r.Relative63) else None,
            '行情日期':d.index[-1].strftime('%Y-%m-%d'),'原因':'；'.join(p['reasons']) or '满足筛选条件',
            **{k:int(r[k]) for k in ('TrendScore','StrengthScore','MomentumScore','LiquidityScore','VolatilityScore','MarketScore')}}


def simulate(d, cfg=Config(), initial=10000., start=None):
    if initial <= 0: raise ValueError('初始资金必须大于0')
    if len(d) < 212: raise ValueError('历史不足；需要均线预热数据')
    start_i = max(210, int(d.index.searchsorted(pd.Timestamp(start)))) if start is not None else 210
    if start_i >= len(d): raise ValueError('所选区间没有有效交易日')
    fee, slip = cfg.fee_bps/1e4, cfg.slip_bps/1e4
    cash, pos, entry, stop, target, basis = float(initial),0,0.,0.,0.,0.
    trades, curve = [],[]
    # Include initial equity so an immediate first-day loss counts in drawdown.
    curve.append({'Date':d.index[start_i-1],'Equity':cash,'Benchmark':initial})
    benchmark_entry = float(d.Open.iloc[start_i])
    for i in range(start_i,len(d)):
        r, prev = d.iloc[i],d.iloc[i-1]
        date = d.index[i]
        exited, entered_intraday = False,False
        def sell(price,reason):
            nonlocal cash,pos
            proceeds = pos*price*(1-fee)
            cash += proceeds
            trades.append({'日期':date,'操作':'卖出','原因':reason,'价格':price,'股数':pos,'费用':pos*price*fee,'净盈亏':proceeds-basis})
            pos = 0
        if pos:
            # Orders carried from yesterday, before using today's high or close.
            if r.Open <= stop: sell(float(r.Open)*(1-slip),'跳空止损'); exited=True
            elif prev.Close < prev.MA50 or not prev.MarketOK: sell(float(r.Open)*(1-slip),'次日开盘趋势退出'); exited=True
            elif r.Open >= target: sell(float(target),'目标限价（不计有利跳空）'); exited=True
        if not pos and not exited:
            p = plan(prev,cfg)
            if p and p['eligible'] and r.Low <= p['entry']:
                # One-session limit order; conservative skip below planned stop.
                if r.Open > p['stop']:
                    fill = min(float(r.Open),p['entry']) if r.Open <= p['entry'] else p['entry']
                    q = quantity(cash,fill,p['stop'],cfg)
                    if q:
                        pos,entry,stop = q,fill,p['stop']
                        target = entry+cfg.rr*(entry-stop)
                        basis = pos*entry*(1+fee)
                        cash -= basis
                        entered_intraday = r.Open > p['entry']
                        trades.append({'日期':date,'操作':'买入','原因':'前一日信号／回踩限价','价格':entry,'股数':pos,'费用':pos*entry*fee,'净盈亏':None})
        if pos:
            # With daily OHLC the high/low order is unknown: stop wins ties.
            if r.Low <= stop: sell(float(stop)*(1-slip),'止损（同日双触发优先止损）')
            elif not entered_intraday and r.High >= target: sell(float(target),'止盈限价')
            if pos:
                # This update takes effect NEXT session, never retroactively today.
                stop = max(stop,float(r.High-2*r.ATR))
        curve.append({'Date':date,'Equity':cash+pos*r.Close,'Benchmark':initial*r.Close/benchmark_entry})
    eq = pd.DataFrame(curve).set_index('Date')
    ledger = pd.DataFrame(trades)
    sells = [t['净盈亏'] for t in trades if t['操作']=='卖出']
    gains, losses = sum(max(0,p) for p in sells),-sum(min(0,p) for p in sells)
    years = (eq.index[-1]-eq.index[0]).days/365.25
    final = float(eq.Equity.iloc[-1])
    metrics = {'最终资产':final,'收益率%':(final/initial-1)*100,
               '买入持有%':(eq.Benchmark.iloc[-1]/initial-1)*100,
               '最大回撤%':float((eq.Equity/eq.Equity.cummax()-1).min()*100),
               '年化收益%':((final/initial)**(1/years)-1)*100 if years else None,
               '已平仓笔数':len(sells),'胜率%':sum(p>0 for p in sells)/len(sells)*100 if sells else None,
               '盈亏金额比':gains/losses if losses else None,'未平仓股数':pos,
               '未实现盈亏':pos*float(d.Close.iloc[-1])-basis if pos else 0.}
    return metrics,eq,ledger


"""Bounded background work, disk snapshots and OHLCV caching. No Streamlit in workers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from io import StringIO
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import pandas as pd

CORE = 'AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO ORCL AMD INTC TSM ASML MU QCOM AMAT LRCX KLAC ARM MRVL TXN ADI PLTR CRM NOW ADBE IBM CSCO PANW CRWD SNOW DDOG NET SHOP UBER ABNB NFLX DIS SPOT PYPL COIN HOOD JPM BAC WFC GS MS V MA AXP BRK-B BLK SCHW XOM CVX COP SLB OXY CAT DE GE HON RTX LMT NOC BA UPS UNP FDX WM COST WMT TGT HD LOW PG KO PEP MCD SBUX NKE LULU LLY JNJ UNH ABBV MRK PFE TMO DHR ISRG AMGN GILD NVO ABT MDT CVS BMY NEE DUK SO PLD AMT EQIX SPG O LIN FCX NEM APD SPY QQQ IWM DIA SOXX XLK XLV XLF XLE XLI XLP XLU TLT GLD'.split()
POOL_NAMES = ['跨行业核心池','S&P 500 动态成分','美国上市股票（排除ETF）','美国上市ETF','自定义代码']
DATA_DIR = Path(os.getenv('QUANT_DATA_DIR','data')).resolve()
DATA_DIR.mkdir(parents=True,exist_ok=True)
DB = DATA_DIR/'quantum.db'


def connect():
    c = sqlite3.connect(DB,timeout=20)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, updated REAL, value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT, category TEXT, added_at TEXT)')
    return c


def read_cache(key, ttl=None):
    with connect() as c: row=c.execute('SELECT updated,value FROM cache WHERE key=?',(key,)).fetchone()
    if row and (ttl is None or time.time()-row[0]<ttl):
        return json.loads(row[1]),row[0]
    return None,None


def save_cache(key,value):
    payload=json.dumps(value,ensure_ascii=False,allow_nan=False)
    with connect() as c: c.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,time.time(),payload))


def watch(action='list', symbol=None):
    with connect() as c:
        if action=='add':
            parsed=parse_symbols(symbol)
            if len(parsed)!=1: raise ValueError('请输入一个有效的美国股票代码')
            c.execute('INSERT OR IGNORE INTO watchlist VALUES (?,?,?,date(\'now\'))',(parsed[0],parsed[0],'自选'))
        elif action=='delete': c.execute('DELETE FROM watchlist WHERE symbol=?',(symbol,))
        return pd.read_sql_query('SELECT * FROM watchlist ORDER BY symbol',c)


def migrate_legacy():
    """Copy once by primary key; keep the old database untouched."""
    legacy=Path('quant_terminal_watch.db')
    marker=DATA_DIR/'legacy-imported'
    if legacy.exists() and not marker.exists():
        with sqlite3.connect(legacy) as old:
            rows=old.execute('SELECT symbol,name,category,added_at FROM watchlist').fetchall()
        with connect() as new: new.executemany('INSERT OR IGNORE INTO watchlist VALUES (?,?,?,?)',rows)
        marker.touch()


def parse_symbols(text):
    items=re.split(r'[,，;；\s]+',text.strip().upper())
    result=[]
    for s in items:
        s=s.replace('.','-')
        if s and not re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}',s): raise ValueError(f'无效代码：{s}')
        if s and s not in result: result.append(s)
    if len(result)>10000: raise ValueError('最多10,000个代码')
    return result


def pool(name):
    if name==POOL_NAMES[0]: return CORE,'内置跨行业候选池（非指数成分）'
    if name==POOL_NAMES[4]: return [],'自定义'
    cached,stamp=read_cache('universe:'+name,86400)
    if cached: return cached['symbols'],cached['source']
    import requests
    def get(url):
        r=requests.get(url,headers={'User-Agent':'Mozilla/5.0 QuantumTerminal/2.0'},timeout=20)
        r.raise_for_status()
        return r.text
    if name==POOL_NAMES[1]:
        tables=pd.read_html(StringIO(get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')))
        frame=next(t for t in tables if 'Symbol' in t.columns)
        symbols=parse_symbols(' '.join(frame.Symbol))
        if len(symbols)<450: raise ValueError('成分表不完整，未替换缓存')
        source='Wikipedia S&P 500 成分表；'+pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d')
    else:
        symbols=[]
        etf='Y' if name==POOL_NAMES[3] else 'N'
        for filename,col in [('nasdaqlisted.txt','Symbol'),('otherlisted.txt','ACT Symbol')]:
            t=pd.read_csv(StringIO(get('https://www.nasdaqtrader.com/dynamic/SymDir/'+filename)),sep='|',dtype=str)
            t=t[(t['Test Issue']=='N') & (t['ETF']==etf)]
            if 'Financial Status' in t: t=t[t['Financial Status']=='N']
            # Exclude warrants/preferred/units and punctuation not supported here.
            t=t[~t['Security Name'].str.contains(r'warrant|preferred|depositary shares|\bunits?\b|\bright(s)?\b',case=False,na=False,regex=True)]
            for s in t[col].dropna():
                normalized=s.replace('.','-')
                if re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}',normalized): symbols.append(normalized)
        symbols=sorted(set(symbols))
        if len(symbols)<100: raise ValueError('上市目录不完整，未替换缓存')
        source='Nasdaq Trader 上市目录；排除测试证券和部分特殊证券；'+pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d')
    save_cache('universe:'+name,dict(symbols=symbols,source=source))
    return symbols,source


def completed_session():
    import exchange_calendars as xcals
    now=pd.Timestamp.now(tz='UTC')-pd.Timedelta(minutes=30)
    cal=xcals.get_calendar('XNYS')
    sched=cal.schedule.loc[(now-pd.Timedelta(days=14)).date().isoformat():now.date().isoformat()]
    closes=pd.to_datetime(sched['close'],utc=True)
    if not (closes<=now).any(): raise RuntimeError('交易日历未覆盖当前日期，请更新 exchange_calendars')
    return pd.Timestamp(sched.index[closes<=now][-1]).tz_localize(None).normalize()


def encode(d):
    return json.loads(d.to_json(orient='split',date_format='iso'))


def decode(value):
    d=pd.DataFrame(value['data'],columns=value['columns'],index=pd.to_datetime(value['index']))
    return clean(d)


class Service:
    def __init__(self):
        # Single outer worker prevents competing yfinance bulk downloads across sessions.
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='quant-worker')
        self.lock=threading.Lock()
        self.jobs={}
        migrate_legacy()

    def submit(self,kind,payload):
        key=hashlib.sha256(json.dumps([VERSION,kind,payload],sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key in self.jobs and self.jobs[key]['status'] in ('queued','running'): return key
            if sum(j['status'] in ('queued','running') for j in self.jobs.values())>=4:
                raise RuntimeError('后台已有4个任务，请等待或取消已有任务')
            for old in list(self.jobs):
                if len(self.jobs)<24: break
                if self.jobs[old]['status'] not in ('queued','running'): del self.jobs[old]
            self.jobs[key]=dict(status='queued',progress=0.,message='排队中',rows=[],errors=[],cancel=False)
        self.executor.submit(self._work,key,kind,payload)
        return key

    def status(self,key):
        with self.lock:
            j=self.jobs.get(key)
            return dict(j,rows=list(j['rows']),errors=list(j['errors'])) if j else None

    def update(self,key,**fields):
        with self.lock: self.jobs[key].update(fields)

    def cancel(self,key):
        with self.lock:
            if key in self.jobs: self.jobs[key]['cancel']=True

    def histories(self,symbols,period,cutoff):
        import yfinance as yf
        out,missing,errors={},[],[]
        for symbol in symbols:
            value,_=read_cache(f'ohlcv:{symbol}:{period}',21600)
            if value and value['cutoff']==str(cutoff.date()): out[symbol]=decode(value['frame'])
            else: missing.append(symbol)
        if missing:
            raw=yf.download(missing,period=period,interval='1d',auto_adjust=True,
                            actions=False,threads=4,progress=False,group_by='ticker',
                            multi_level_index=True,timeout=12)
            for symbol in missing:
                try:
                    if raw is None or raw.empty: raise ValueError('下载为空或数据源限流')
                    if isinstance(raw.columns,pd.MultiIndex):
                        if symbol in raw.columns.get_level_values(0): f=raw[symbol]
                        elif symbol in raw.columns.get_level_values(1): f=raw.xs(symbol,axis=1,level=1)
                        else: raise ValueError('下载未返回该代码')
                    else: f=raw
                    d=clean(f)
                    d=d.loc[d.index<=cutoff]
                    if d.empty: raise ValueError('没有已完成交易日')
                    if d.index[-1]!=cutoff: raise ValueError(f'行情过期：{d.index[-1].date()}')
                    out[symbol]=d
                    save_cache(f'ohlcv:{symbol}:{period}',dict(cutoff=str(cutoff.date()),frame=encode(d)))
                except Exception as e: errors.append({'代码':symbol,'错误':str(e)})
        return out,errors

    def _work(self,key,kind,p):
        started=time.perf_counter()
        try:
            if self.status(key)['cancel']:
                self.update(key,status='cancelled',message='已取消'); return
            self.update(key,status='running',message='后台处理中')
            if kind=='pool':
                symbols,source=pool(p['name'])
                self.update(key,result=dict(symbols=symbols,source=source))
            elif kind=='news':
                import yfinance as yf
                raw=yf.Ticker(p['symbol']).news or []
                rows=[]
                for item in raw[:8]:
                    c=item.get('content') or item
                    link=c.get('canonicalUrl') or c.get('clickThroughUrl') or {}
                    if isinstance(link,dict): link=link.get('url','')
                    link=link or c.get('link','')
                    if not link.startswith(('https://','http://')): link=''
                    rows.append(dict(title=c.get('title','无标题'),link=link))
                self.update(key,result={'symbol':p['symbol'],'items':rows})
            else:
                cutoff=completed_session()
                cfg=Config(**p['config'])
                if kind=='scan':
                    symbols=p['symbols']
                    benchmark,err=self.histories(['SPY'],'2y',cutoff)
                    if 'SPY' not in benchmark: raise ValueError('SPY基准不可用：'+str(err))
                    rows,errors=[],[]
                    for n in range(0,len(symbols),40):
                        if self.status(key)['cancel']:
                            self.update(key,status='cancelled',message='已取消；完整旧快照保留'); return
                        batch=symbols[n:n+40]
                        frames,fail=self.histories(batch,'2y',cutoff)
                        errors.extend(fail)
                        for s in batch:
                            if s not in frames: continue
                            try: rows.append(summary(s,indicators(frames[s],benchmark['SPY']),cfg))
                            except Exception as e: errors.append({'代码':s,'错误':str(e)})
                        self.update(key,rows=list(rows),errors=list(errors),progress=min(1,(n+len(batch))/len(symbols)),message=f'已处理 {min(n+40,len(symbols))}/{len(symbols)}')
                    if not rows: raise ValueError('没有有效结果；请检查失败清单、网络或稍后重试')
                    rows.sort(key=lambda r:r['评分'],reverse=True)
                    result=dict(rows=rows,errors=errors,config=p['config'],symbols=symbols,
                                cutoff=str(cutoff.date()),updated=pd.Timestamp.now(tz='UTC').isoformat(),
                                seconds=round(time.perf_counter()-started,2),version=VERSION,label=p.get('label',''))
                    save_cache('scan:'+key,result)
                    if p.get('label')!='自选清单': save_cache('last_scan',{'key':key})
                    self.update(key,result=result)
                else:
                    period='5y' if kind=='backtest' else '2y'
                    frames,err=self.histories(list(dict.fromkeys([p['symbol'],'SPY'])),period,cutoff)
                    if p['symbol'] not in frames or 'SPY' not in frames: raise ValueError(str(err))
                    d=indicators(frames[p['symbol']],frames['SPY'])
                    if kind=='detail': self.update(key,result=dict(frame=d,summary=summary(p['symbol'],d,cfg)))
                    elif kind=='backtest':
                        m,eq,ledger=simulate(d,cfg,p['capital'],p['start'])
                        self.update(key,result=dict(metrics=m,equity=eq,trades=ledger,symbol=p['symbol'],config=p['config'],start=p['start']))
            self.update(key,status='done',progress=1.,message=f'完成，用时 {time.perf_counter()-started:.1f} 秒')
        except Exception as e:
            self.update(key,status='error',message=f'{type(e).__name__}: {e}')


def scan_key(payload):
    return hashlib.sha256(json.dumps([VERSION,'scan',payload],sort_keys=True).encode()).hexdigest()

import html
from dataclasses import asdict, replace
import streamlit as st
import pandas as pd

st.set_page_config(page_title='QuantumSignal PRO 2',page_icon='⚡',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>
.stApp{background:#0b1018;color:#dbe5f2} .block-container{max-width:1200px;padding-top:1.4rem}
h1,h2,h3{letter-spacing:-.025em} .eyebrow{color:#46dfce;font-size:12px;letter-spacing:2px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
.card{background:#121e2c;border:1px solid #25364a;border-radius:12px;padding:14px}
.card small{color:#9aadc2;display:block;font-size:12px}.card b{font-size:23px;color:#52e1cc;display:block;margin-top:6px}
@media(max-width:700px){.block-container{padding:1rem .8rem}.cards{grid-template-columns:repeat(2,1fr)}.card b{font-size:20px}}
</style>''',unsafe_allow_html=True)
st.markdown('<div class="eyebrow">DAILY RESEARCH · US MARKETS</div>',unsafe_allow_html=True)
st.title('⚡ QuantumSignal PRO')
st.caption('已收盘日线分析 · 可解释评分 · 后台筛选 ｜ 评分不是胜率，参考价不代表必然成交。')

@st.cache_resource
def service(): return Service()

svc=service()
ss=st.session_state
if 'symbol' not in ss: ss.symbol='NVDA'
if 'pool_symbols' not in ss: ss.pool_symbols=CORE
if 'pool_source' not in ss: ss.pool_source='内置跨行业核心池'
if 'pool_loaded_name' not in ss: ss.pool_loaded_name=POOL_NAMES[0]
if 'config' not in ss: ss.config=asdict(Config())
if 'pending_page' in ss: ss['page']=ss.pop('pending_page')

with st.expander('⚙️ 风控与筛选设置',expanded=False):
    with st.form('settings'):
        current=Config(**ss.config)
        c1,c2=st.columns(2)
        with c1:
            rr=st.slider('目标盈亏比（实际用于回测）',1.,5.,current.rr,.5)
            risk=st.slider('每笔计划风险 / 账户资金 %',.1,5.,current.risk_pct,.1)
            maxpos=st.slider('单只持仓上限 %',5.,100.,current.max_position_pct,5.)
            score=st.slider('最低候选评分',0,100,current.min_score,5)
        with c2:
            volume=st.number_input('最低20日平均成交额（百万美元）',min_value=0.,value=current.min_dollar_volume/1e6,step=5.)
            price=st.number_input('最低股价（美元）',min_value=0.,value=current.min_price)
            volatility=st.slider('最高 ATR / 股价 %',1.,30.,current.max_atr_pct,.5)
            fee=st.number_input('单边费用（基点，10 = 0.1%）',min_value=0.,value=current.fee_bps)
            slip=st.number_input('市价/止损滑点（基点）',min_value=0.,value=current.slip_bps)
        if st.form_submit_button('保存设置'):
            ss.config=asdict(Config(rr,risk,maxpos,volume*1e6,price,volatility,score,fee,slip))
            st.rerun()
cfg=Config(**ss.config)
page=st.radio('功能',['筛选','诊断','回测','自选'],horizontal=True,key='page',label_visibility='collapsed')


def submit(kind,payload,state_key):
    try:
        ss[state_key]=svc.submit(kind,payload)
        ss.pop('terminal_seen_'+ss[state_key],None)
    except Exception as e: st.error(str(e))


def cards(items):
    body=''.join(f'<div class="card"><small>{html.escape(str(k))}</small><b>{html.escape(str(v))}</b></div>' for k,v in items)
    st.markdown('<div class="cards">'+body+'</div>',unsafe_allow_html=True)


def job_status(key):
    j=svc.status(key)
    if not j:
        st.info('后台已重启，请重新提交。已有扫描快照仍可读取。'); return None
    if j['status'] in ('done','error','cancelled') and ss.get('terminal_seen_'+key)!=j['status']:
        ss['terminal_seen_'+key]=j['status']
        st.rerun()
    if j['status'] in ('queued','running'):
        st.progress(j['progress'],text=j['message'])
        if st.button('取消任务',key='cancel_'+key): svc.cancel(key)
    elif j['status']=='error': st.error(j['message'])
    elif j['status']=='cancelled': st.info(j['message'])
    else: st.caption(j['message'])
    return j


def table_result(result,prefix='scan',partial=False):
    rows=result.get('rows',[])
    if not rows: return
    if not partial:
        st.caption(f"股票池：{result.get('label','')}")
        st.caption(f"行情：{result.get('cutoff','')} ｜ 更新：{result.get('updated','')} UTC ｜ 成功 {len(rows)} / {len(result.get('symbols',rows))} ｜ 用时 {result.get('seconds','—')} 秒")
        if result.get('config')!=ss.config:
            st.warning('这是旧设置下的结果。请重新扫描应用当前设置。')
        if result.get('cutoff') and (pd.Timestamp.now(tz='America/New_York').date()-pd.Timestamp(result['cutoff']).date()).days>3:
            st.warning('快照行情较旧，请刷新；休市日也可能造成日期间隔。')
    d=pd.DataFrame(rows).sort_values('评分',ascending=False)
    only=st.checkbox('只显示符合条件的候选',value=False,key=prefix+'_only')
    if only: d=d[d['状态'].str.startswith('候选')]
    limit=st.selectbox('手机显示条数',[20,50,100],key=prefix+'_limit')
    if d.empty: st.info('没有符合条件的候选。不强行推荐股票。')
    else:
        top=d[d['状态'].str.startswith('候选')].head(3)
        if not top.empty:
            cards([(r['代码'],f"{r['评分']} / 100") for r in top.to_dict('records')])
        st.dataframe(d[['代码','评分','状态','收盘价','买入参考','止损','目标','RSI','ATR%','行情日期','原因']].head(limit).round(2),hide_index=True,width='stretch')
        symbol=st.selectbox('选择股票进入诊断',d['代码'].tolist(),key=prefix+'_symbol')
        if st.button('查看诊断',key=prefix+'_diagnose'):
            ss.symbol=symbol; ss.pending_page='诊断'
            st.rerun()
    if not partial:
        st.download_button('下载完整筛选 CSV',pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),'screening.csv','text/csv',key=prefix+'_csv')
    errors=result.get('errors',[])
    if errors:
        with st.expander(f'未纳入结果的代码（{len(errors)}）'):
            st.dataframe(pd.DataFrame(errors),hide_index=True,width='stretch')


def chart(d,p):
    # Plotly is loaded only on diagnosis/backtest, keeping first paint lightweight.
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig=make_subplots(rows=3,cols=1,shared_xaxes=True,vertical_spacing=.035,row_heights=[.62,.18,.20])
    fig.add_trace(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name='复权日K',increasing_line_color='#45ddbc',decreasing_line_color='#ff6f91'),row=1,col=1)
    for col,color in [('EMA20','#42caff'),('MA50','#e7c56b'),('Supertrend','#a996ef')]:
        fig.add_trace(go.Scatter(x=d.index,y=d[col],name=col,line=dict(color=color,width=1)),row=1,col=1)
    for key,label,color in [('entry','买入参考','#e7c56b'),('stop','止损','#ff6f91'),('target','目标','#45ddbc')]:
        fig.add_hline(y=p[key],line_dash='dot',line_color=color,annotation_text=label,row=1,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.Hist,name='MACD柱',marker_color=['#45ddbc' if x>=0 else '#ff6f91' for x in d.Hist]),row=2,col=1)
    fig.add_trace(go.Scatter(x=d.index,y=d.RSI,name='RSI',line_color='#a996ef'),row=3,col=1)
    for y in (30,70): fig.add_hline(y=y,line_dash='dot',row=3,col=1)
    fig.update_layout(template='plotly_dark',paper_bgcolor='#0b1018',plot_bgcolor='#121e2c',height=530,showlegend=False,margin=dict(l=5,r=5,t=15,b=5))
    fig.update_xaxes(rangeslider_visible=False)
    return fig


if page=='筛选':
    st.subheader('扩大范围，后台扫描')
    selected=st.selectbox('股票池',POOL_NAMES,key='pool_choice')
    if st.button('载入股票池名单'):
        ss.requested_pool_name=selected
        submit('pool',{'name':selected},'pool_job')
    if selected=='自定义代码':
        custom=st.text_area('粘贴美国股票代码（逗号、空格或换行）',', '.join(CORE[:15]))
        if st.button('使用自定义名单'):
            try:
                parsed=parse_symbols(custom)
                if not parsed: raise ValueError('名单不能为空')
                ss.pool_symbols=parsed;ss.pool_loaded_name=selected;ss.pool_source='用户自定义'
            except ValueError as e: st.error(str(e))
    @st.fragment(run_every='2s' if ss.get('pool_job') and (svc.status(ss.pool_job) or {}).get('status') in ('queued','running') else None)
    def pool_poll():
        if not ss.get('pool_job'): return
        j=job_status(ss.pool_job)
        if j and j['status']=='done':
            ss.pool_symbols=j['result']['symbols']; ss.pool_source=j['result']['source']
            # The selected name is captured when the task is submitted, see source label below.
            ss.pool_loaded_name=ss.get('requested_pool_name',selected)
            ss.pop('pool_job',None); st.rerun()
    pool_poll()
    st.caption(f'当前实际名单：{ss.pool_source} ｜ {len(ss.pool_symbols)} 个代码。载入失败不会冒充完整指数。')
    if not ss.pool_symbols: st.info('请先填写自定义代码。'); st.stop()
    with st.form('scan_form'):
        requested_count=st.number_input('本次扫描数量上限（按名单顺序；不是全市场排名）',min_value=1,max_value=len(ss.pool_symbols),value=min(500,len(ss.pool_symbols)),step=1)
        st.caption('选全部才覆盖整个名单。首次大范围下载可能需数分钟；过程中可切换页面。')
        scan=st.form_submit_button('启动 / 刷新后台筛选',type='primary')
    payload=dict(symbols=sorted(ss.pool_symbols[:requested_count]),config=ss.config,label=ss.pool_source)
    expected=scan_key(payload)
    old,_=read_cache('scan:'+expected)
    if old is None:
        latest,_=read_cache('last_scan')
        if latest:
            old,_=read_cache('scan:'+latest['key'])
            if old: st.info('显示上次完成的快照；当前选择尚未完成扫描。')
    if scan: submit('scan',payload,'scan_job')
    @st.fragment(run_every='2s' if ss.get('scan_job') and (svc.status(ss.scan_job) or {}).get('status') in ('queued','running') else None)
    def scan_poll():
        result=old
        if ss.get('scan_job'):
            j=job_status(ss.scan_job)
            if j and j['status']=='done':
                result=j['result']
                if ss.scan_job!=expected: st.info('显示最近完成的任务；当前股票池或设置已改变。')
            elif j and j['status'] in ('queued','running') and not result and j['rows']:
                st.caption('以下是已完成批次的临时结果，排名尚未完成。')
                table_result(j,'partial',True)
        if result: table_result(result)
        elif not ss.get('scan_job'): st.info('尚无该股票池的快照。点击开始，页面无需等待整批数据。')
    scan_poll()

elif page=='诊断':
    with st.form('detail_form'):
        symbol=st.text_input('美国股票代码',value=ss.symbol)
        go=st.form_submit_button('加载分析',type='primary')
    if go:
        try:
            syms=parse_symbols(symbol)
            if len(syms)!=1: raise ValueError('请输入一个股票代码')
            ss.symbol=syms[0]
            submit('detail',dict(symbol=ss.symbol,config=ss.config),'detail_job')
        except ValueError as e: st.error(str(e))
    @st.fragment(run_every='2s' if ss.get('detail_job') and (svc.status(ss.detail_job) or {}).get('status') in ('queued','running') else None)
    def detail_poll():
        if not ss.get('detail_job'): st.info('输入代码后加载；不在打开页面时自动请求行情。'); return
        j=job_status(ss.detail_job)
        if not j or j['status']!='done': return
        result=j['result'];d=result['frame'];r=d.iloc[-1]
        # Recompute levels locally when risk settings change; never redownload prices for RR.
        summarize=summary
        s=summarize(result['summary']['代码'],d,cfg)
        p=plan(r,cfg)
        st.subheader(f"{s['代码']} · {s['状态']} · {s['评分']} 分")
        st.caption(f"数据日期：{s['行情日期']} ｜ 美元、复权已收盘日线；不是盘中实时价。")
        cards([('收盘价',f'${r.Close:.2f}'),('回踩买入参考',f'${p["entry"]:.2f}'),('初始止损',f'${p["stop"]:.2f}'),('目标价',f'${p["target"]:.2f}')])
        st.write(f"回踩观察区间：${p['entry_low']:.2f}–${p['entry']:.2f}。{s['原因']}。")
        st.caption('限价仅在下一交易日有效，之后须重算。区间下沿用于观察；回测只使用上沿限价。')
        if not p['eligible']: st.warning('当前未满足入选条件；上面的价格仅为条件式测算。')
        capital=st.number_input('用于估算仓位的账户资金（美元）',min_value=100.,value=10000.,step=1000.)
        q=quantity(capital,p['entry'],p['stop'],cfg) if p['eligible'] else 0
        st.write(f'按当前风险设置：最多 **{q} 股**；计划风险预算 **${capital*cfg.risk_pct/100:.2f}**。')
        st.caption('这是单笔仓位上限，未扣除已有持仓；跳空可能让实际亏损超过预算。')
        days=st.select_slider('图表交易日数',[45,90,180],value=90)
        st.plotly_chart(chart(d.tail(days),p),width='stretch',config={'displayModeBar':False})
        macd='当日金叉' if r.CrossUp else '当日死叉' if r.CrossDown else '多头状态' if r.Hist>0 else '空头状态'
        st.write(f'RSI {r.RSI:.1f} · MACD {macd} · Supertrend {"多头" if r.STDirection==1 else "空头"} · ATR {r.ATRpct:.1f}%')
        with st.expander('为什么得到这个分数？'):
            names={'TrendScore':'趋势 / 30','StrengthScore':'相对SPY强度 / 20','MomentumScore':'动量 / 20','LiquidityScore':'成交额 / 10','VolatilityScore':'波动率 / 10','MarketScore':'大盘环境 / 10'}
            st.dataframe(pd.DataFrame([{'项目':v,'得分':s[k]} for k,v in names.items()]),hide_index=True)
            st.caption('固定规则评分，尚未证明优于原模型；并非训练模型，也不是盈利概率。')
        if st.button('加入自选'): watch('add',s['代码']);st.success('已保存')
        if st.button('按需加载新闻（不参与打分）'):
            submit('news',dict(symbol=s['代码']),'news_job'); st.rerun()
    detail_poll()
    @st.fragment(run_every='2s' if ss.get('news_job') and (svc.status(ss.news_job) or {}).get('status') in ('queued','running') else None)
    def news_poll():
        if not ss.get('news_job'): return
        j=job_status(ss.news_job)
        if j and j['status']=='done':
            st.caption('新闻代码：'+j['result']['symbol'])
            for n in j['result']['items']:
                if n['link']: st.link_button(n['title'],n['link'])
                else: st.write(n['title'])
            if not j['result']['items']: st.info('数据源未提供新闻。')
    news_poll()

elif page=='回测':
    st.subheader('按实际时间顺序验证规则')
    st.caption('同一套筛选条件 → 次日回踩限价 → 止损/止盈 → 次日生效的移动止损。')
    with st.form('backtest_form'):
        symbol=st.text_input('回测美国股票代码',value=ss.symbol)
        capital=st.number_input('初始资金（美元）',min_value=100.,value=10000.,step=1000.)
        start=st.date_input('开始日期（此前数据只用于指标预热）',value=(pd.Timestamp.now()-pd.DateOffset(years=2)).date())
        run=st.form_submit_button('后台回测',type='primary')
    if run:
        try:
            syms=parse_symbols(symbol)
            if len(syms)!=1: raise ValueError('请输入一个代码')
            submit('backtest',dict(symbol=syms[0],capital=capital,start=str(start),config=ss.config),'backtest_job')
        except ValueError as e: st.error(str(e))
    @st.fragment(run_every='2s' if ss.get('backtest_job') and (svc.status(ss.backtest_job) or {}).get('status') in ('queued','running') else None)
    def bt_poll():
        if not ss.get('backtest_job'): return
        j=job_status(ss.backtest_job)
        if not j or j['status']!='done': return
        result=j['result']; m=result['metrics'];eq=result['equity'];ledger=result['trades']
        st.subheader(f"{result['symbol']} 回测结果")
        st.caption(f"实际区间 {eq.index[1].date()} 至 {eq.index[-1].date()} ｜ 本次盈亏比 {result['config']['rr']}")
        if result['config']!=ss.config: st.warning('设置已改变；以下仍是原参数结果，请重新回测。')
        cards([('总收益',f"{m['收益率%']:.2f}%"),('最大回撤',f"{m['最大回撤%']:.2f}%"),('平仓胜率','无平仓' if m['胜率%'] is None else f"{m['胜率%']:.1f}%"),('最终资产',f"${m['最终资产']:,.2f}")])
        import plotly.graph_objects as go
        fig=go.Figure()
        for col,label,color in [('Equity','策略（含闲置现金）','#52e1cc'),('Benchmark','同标的全仓买入持有（不计费用）','#9aadc2')]:
            fig.add_trace(go.Scatter(x=eq.index,y=eq[col],name=label,line_color=color))
        fig.update_layout(template='plotly_dark',height=330,margin=dict(l=5,r=5,t=15,b=5),legend=dict(orientation='h',y=-.2))
        st.plotly_chart(fig,width='stretch',config={'displayModeBar':False})
        st.write(f"已平仓 {m['已平仓笔数']} 笔；期末未平仓 {m['未平仓股数']} 股，以末日收盘估值。")
        st.caption('日线无法知道当日高低价先后：双触发优先止损；盘中限价入场当日不计止盈。复权历史用于近似模拟，未模拟税款、实际派息入账、停牌、退市与盘口容量。')
        if not ledger.empty:
            st.dataframe(ledger.round(3),hide_index=True,width='stretch')
            st.download_button('下载交易明细',ledger.to_csv(index=False).encode('utf-8-sig'),'trades.csv','text/csv')
        st.download_button('下载净值',eq.to_csv().encode('utf-8-sig'),'equity.csv','text/csv')
        with st.expander('全部统计与验证方法'):
            st.json(m)
            st.write('先固定规则，在未用于调参的区间测试；不要把反复挑选参数后的最高收益当作未来表现。此处为单标的回测，不是全市场选股组合回测。')
    bt_poll()

else:
    st.subheader('自选清单')
    with st.form('watch_add'):
        symbol=st.text_input('添加美国股票代码')
        if st.form_submit_button('添加'):
            try: watch('add',symbol);st.rerun()
            except ValueError as e: st.error(str(e))
    w=watch()
    if w.empty: st.info('清单为空。')
    else:
        st.dataframe(w[['symbol','added_at']],hide_index=True,width='stretch')
        remove=st.selectbox('选择要移除的代码',w.symbol)
        if st.button('移除自选'): watch('delete',remove);st.rerun()
        if st.button('后台刷新自选分析'):
            submit('scan',dict(symbols=sorted(w.symbol.tolist()),config=ss.config,label='自选清单'),'watch_job')
        @st.fragment(run_every='2s' if ss.get('watch_job') and (svc.status(ss.watch_job) or {}).get('status') in ('queued','running') else None)
        def watch_poll():
            if not ss.get('watch_job'): return
            j=job_status(ss.watch_job)
            if j and j['status']=='done': table_result(j['result'],'watch')
        watch_poll()
    st.download_button('导出自选备份',w.to_csv(index=False).encode('utf-8-sig'),'watchlist.csv','text/csv')

st.caption('个人日线研究工具 · Yahoo 行情可能延迟或限流 · 不是自动交易系统')
