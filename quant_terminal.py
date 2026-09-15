"""QuantumSignal V2 — 规则固定、仅做多的日线研究终端。

部署本文件及 requirements.txt。导入本文件不会启动用户界面。
复权 OHLC 表示合成投资单位，并非券商实际股份记录。
所有订单均根据前一收盘时点确定；不进行依赖历史数据的优化。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import math
import zipfile

import numpy as np
import pandas as pd

VERSION = "2.0.0-frozen"
WARMUP = 280


@dataclass(frozen=True)
class Config:
    preset: str = "Balanced"
    max_exposure: float = 1.0
    vol_discount: float = .20
    bull_retention: float = .85
    dd_start: float = .08
    dd_full: float = .20
    dd_discount: float = .40
    risk_on: float = .10
    risk_off: float = .15
    emergency_cap: float = .20
    dd_recovery: float = .02
    long_window: int = 200
    momentum_window: int = 126
    structure_scale: float = .08
    momentum_scale: float = .15
    slope_scale: float = .02
    regime_confirm: int = 3
    healthy_confirm: int = 5
    shock_day: float = -.10
    shock_five: float = -.08
    shock_ratio: float = 1.80
    shock_absolute: float = .30
    no_trade: float = .02
    commission_bps: float = 5.0
    spread_bps: float = 4.0
    slippage_bps: float = 3.0

    def validate(self):
        if self.preset not in ("Balanced", "Conservative", "Aggressive"):
            raise ValueError("未知预设")
        if not 0 < self.max_exposure <= 1:
            raise ValueError("最大仓位必须在 (0, 1] 范围内")
        if not 0 <= self.dd_start < self.dd_full < 1:
            raise ValueError("回撤阈值无效")
        for value in (self.vol_discount, self.dd_discount, self.bull_retention,
                      self.emergency_cap, self.no_trade):
            if not 0 <= value <= 1:
                raise ValueError("风险参数无效")
        if min(self.risk_on, self.risk_off, self.dd_recovery) <= 0:
            raise ValueError("仓位调整速度必须为正数")
        if min(self.structure_scale, self.momentum_scale, self.slope_scale) <= 0:
            raise ValueError("特征缩放参数必须为正数")
        if min(self.long_window, self.momentum_window) < 2:
            raise ValueError("特征窗口必须至少为 2")
        if min(self.regime_confirm, self.healthy_confirm) < 1:
            raise ValueError("确认次数必须为正数")
        if not (-1 < self.shock_day < 0 and -1 < self.shock_five < 0):
            raise ValueError("冲击阈值必须为负收益率")
        if self.shock_ratio <= 0 or self.shock_absolute <= 0:
            raise ValueError("冲击尺度必须为正数")
        if min(self.commission_bps, self.spread_bps, self.slippage_bps) < 0:
            raise ValueError("交易成本不能为负数")
        if max(self.commission_bps, self.spread_bps, self.slippage_bps) >= 1000:
            raise ValueError("交易成本超出支持的研究范围")


def preset_config(name="Balanced"):
    if name == "Conservative":
        return Config(preset=name, max_exposure=.90, vol_discount=.25,
                      bull_retention=.80, dd_start=.06, dd_full=.16,
                      dd_discount=.50, risk_on=.075, risk_off=.20,
                      emergency_cap=.10, dd_recovery=.015)
    if name == "Aggressive":
        return Config(preset=name, vol_discount=.15, bull_retention=.90,
                      dd_start=.10, dd_full=.25, dd_discount=.30,
                      risk_on=.15, risk_off=.10, emergency_cap=.25,
                      dd_recovery=.03)
    if name != "Balanced":
        raise ValueError("未知预设")
    return Config()


@dataclass(frozen=True)
class Variant:
    name: str = "F Full V2"
    kind: str = "continuous"
    volatility: bool = True
    drawdown: bool = True
    floor: bool = True
    emergency: bool = True
    memory: bool = True
    momentum: bool = True
    slope: bool = True


def variants():
    c = Variant("C Continuous", volatility=False, drawdown=False,
                floor=False, emergency=False)
    f = Variant()
    return {
        "A Buy & Hold": Variant("A Buy & Hold", kind="hold"),
        "B SMA200": Variant("B SMA200", kind="simple"),
        c.name: c,
        "D C + Volatility": replace(c, name="D C + Volatility", volatility=True),
        "E C + Drawdown": replace(c, name="E C + Drawdown", drawdown=True),
        f.name: f,
        "F − Volatility": replace(f, name="F − Volatility", volatility=False),
        "F − Drawdown": replace(f, name="F − Drawdown", drawdown=False),
        "F − Participation floor": replace(f, name="F − Participation floor", floor=False),
        "F − Emergency": replace(f, name="F − Emergency", emergency=False),
        "F − Regime memory": replace(f, name="F − Regime memory", memory=False),
        "C − Momentum": replace(c, name="C − Momentum", momentum=False),
        "C − Slope": replace(c, name="C − Slope", slope=False),
    }


def validate_frame(frame):
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(frame.columns):
        raise ValueError("必须包含 OHLCV 列")
    d = frame[required].copy().astype(float)
    d.index = pd.DatetimeIndex(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
    d.index = d.index.normalize()
    if d.empty or not d.index.is_unique or not d.index.is_monotonic_increasing:
        raise ValueError("日期不能为空，且必须唯一并按顺序排列")
    if not np.isfinite(d.to_numpy()).all():
        raise ValueError("OHLCV 存在缺失值或非有限值；不会自动填补价格")
    valid = ((d.Low > 0) & (d.Volume >= 0)
             & (d.High >= d[["Open", "Close", "Low"]].max(axis=1))
             & (d.Low <= d[["Open", "Close", "High"]].min(axis=1)))
    if not valid.all():
        raise ValueError("OHLCV 数据关系无效")
    return d


def features(frame, cfg=Config(), variant=Variant()):
    """仅使用向后看的历史运算。波动率绝不用于归一化趋势证据。"""
    d = validate_frame(frame)
    p = d.Close
    d["MA200"] = p.rolling(cfg.long_window).mean()
    ma100 = p.rolling(100).mean()
    d["L"] = np.log(p / d.MA200)
    d["M"] = np.log(p / p.shift(cfg.momentum_window))
    d["S"] = np.log(ma100 / ma100.shift(20))
    d["uL"] = (d.L / cfg.structure_scale).clip(-1, 1)
    d["uM"] = (d.M / cfg.momentum_scale).clip(-1, 1)
    d["uS"] = (d.S / cfg.slope_scale).clip(-1, 1)
    # 删除测试同时移除该组件的评分贡献及其资格判定条件。
    wm, ws = (.25 if variant.momentum else 0), (.25 if variant.slope else 0)
    d["T"] = (.5*d.uL + wm*d.uM + ws*d.uS) / (.5+wm+ws)
    r = np.log(p / p.shift(1))
    d["Sigma"] = r.rolling(20).std(ddof=1)*np.sqrt(252)
    d["SigmaRef"] = d.Sigma.shift(1).rolling(252).median().clip(lower=.10)
    d["VolRatio"] = d.Sigma / d.SigmaRef
    d["Return1"] = p.pct_change(fill_method=None)
    d["Return5"] = p.pct_change(5, fill_method=None)
    d["Return20"] = p.pct_change(20, fill_method=None)
    d["NoNewLow"] = p >= p.shift(1).rolling(20).min()
    d["StructureBreak"] = (p < .97*d.MA200).rolling(2).sum().eq(2)
    d["Shock"] = (d.VolRatio >= cfg.shock_ratio) & (d.Sigma >= cfg.shock_absolute)
    d["Trigger"] = ((d.StructureBreak & (d.Shock | (d.Return5 <= cfg.shock_five)))
                    | ((d.Return1 <= cfg.shock_day) & d.Shock))
    mp, mn = ((d.M > 0), (d.M < 0)) if variant.momentum else (True, True)
    sp, sn = ((d.S > 0), (d.S < 0)) if variant.slope else (True, True)
    bull = (p > 1.01*d.MA200) & mp & sp
    bear = (p < .99*d.MA200) & mn & sn
    count = cfg.regime_confirm
    bc = bull.rolling(count).sum().eq(count)
    br = bear.rolling(count).sum().eq(count)
    exit_bull = ((p < .99*d.MA200).rolling(count).sum().eq(count)
                 | (d['T'] < -.25).rolling(count).sum().eq(count))
    exit_bear = ((p > 1.01*d.MA200).rolling(count).sum().eq(count)
                 | (d['T'] > .25).rolling(count).sum().eq(count))
    states, state = [], "Neutral"
    for i in range(len(d)):
        if variant.memory:
            if bc.iloc[i]: state = "Bull"
            elif br.iloc[i]: state = "Bear"
            elif state == "Bull" and exit_bull.iloc[i]: state = "Neutral"
            elif state == "Bear" and exit_bear.iloc[i]: state = "Neutral"
        else:
            state = "Bull" if bull.iloc[i] else "Bear" if bear.iloc[i] else "Neutral"
        states.append(state)
    d["Regime"] = states
    health = d.Regime.eq("Bull") & bull & (d['T'] >= .5)
    d["HealthyMarket"] = health.rolling(cfg.healthy_confirm).sum().eq(cfg.healthy_confirm)
    d["Ready"] = np.isfinite(d[["T", "SigmaRef", "Return20", "MA200"]]).all(axis=1)
    return d


@dataclass
class DrawdownState:
    peak: float
    mode: str = "Normal"
    penalty: float = 0.
    low: float = math.inf
    recovery_low: float = math.inf
    confirmed: int = 0

    def update(self, equity, market_recovering, emergency, cfg):
        if equity >= self.peak:
            self.peak = equity
            self.mode, self.penalty, self.confirmed = "Normal", 0., 0
            self.low, self.recovery_low = equity, equity
            return 0.
        dd = 1-equity/self.peak
        raw = cfg.dd_discount*np.clip((dd-cfg.dd_start)/(cfg.dd_full-cfg.dd_start), 0, 1)
        if self.mode == "Normal" and dd > cfg.dd_start:
            self.mode, self.low = "Defensive", equity
        if self.mode == "Recovering":
            if equity <= .98*self.recovery_low or emergency:
                self.mode, self.confirmed = "Defensive", 0
                self.low = min(equity, self.recovery_low)
                self.penalty = max(self.penalty, raw)
            else:
                self.penalty = max(0., self.penalty-cfg.dd_recovery)
        elif self.mode == "Defensive":
            new_low = equity < self.low
            self.low = min(self.low, equity)
            self.penalty = max(self.penalty, raw)
            self.confirmed = self.confirmed+1 if market_recovering and not new_low and not emergency else 0
            if self.confirmed >= 5:
                self.mode, self.recovery_low = "Recovering", self.low
        return float(self.penalty)


@dataclass
class AssetState:
    target: float = 0.
    emergency: bool = False
    age: int = 0
    calm: int = 0
    attainable_floor: float = 0.

    def update_emergency(self, row, enabled):
        previous = self.emergency
        if not enabled:
            self.emergency, self.age, self.calm = False, 0, 0
        elif bool(row.Trigger):
            self.emergency, self.calm = True, 0
            self.age = self.age+1 if previous else 1
        elif self.emergency:
            self.age += 1
            quiet = not row.Shock and row.Return20 > 0 and row.NoNewLow
            self.calm = self.calm+1 if quiet else 0
            if self.age >= 5 and self.calm >= 5:
                self.emergency, self.age, self.calm = False, 0, 0
        return previous != self.emergency


def make_decisions(rows, states, dd_state, equity, budgets, cfg, variant):
    """每次收盘调用一次，包括开始日期前的收盘时点。此处不接收成交数据。"""
    for s, row in rows.items():
        states[s].update_emergency(row, variant.emergency and variant.kind == "continuous")
    recovering = all(r['T'] > 0 and r.Return20 > 0 and r.NoNewLow for r in rows.values())
    any_emergency = any(s.emergency for s in states.values())
    # 保守的共享账户恢复条件：所有分配了预算的资产都必须恢复。
    penalty = dd_state.update(equity, recovering, any_emergency, cfg) if variant.drawdown and variant.kind == "continuous" else 0.
    severe = dd_state.mode == "Defensive" and 1-equity/dd_state.peak >= cfg.dd_full
    out = {}
    for s, row in rows.items():
        state, a = states[s], budgets[s]
        old = state.target
        if variant.kind in ("hold", "simple"):
            base = 1. if variant.kind == "hold" else float(row.Close > row.MA200)
            state.target = base
            out[s] = dict(Base=base*a, TrendReduction=(1-base)*a,
                          VolReduction=0., DrawdownReduction=0., FloorCredit=0.,
                          TransitionEffect=0., EmergencyReduction=0., Target=base*a,
                          Desired=base*a, Healthy=False, Emergency=False,
                          AttainableFloor=0., DDMode="Normal", DDPenalty=0.)
            continue
        h = {"Bull": .1, "Neutral": 0., "Bear": -.1}[row.Regime] if variant.memory else 0.
        x = np.clip((row['T']+h+1)/2, 0, 1)
        base = cfg.max_exposure*(3*x*x-2*x*x*x)
        negative_m = row.M < 0 if variant.momentum else row['T'] < 0
        if row.StructureBreak and negative_m:
            base = min(base, .25*cfg.max_exposure)
        pv = cfg.vol_discount*np.clip((row.VolRatio-1.25)/.75, 0, 1) if variant.volatility else 0.
        combined = max(pv, penalty)
        after_risk = base*(1-combined)
        healthy = bool(row.HealthyMarket and not state.emergency and not row.StructureBreak
                       and not row.Shock and penalty <= .15 and not severe)
        floor = cfg.bull_retention*base if healthy and variant.floor else 0.
        desired = max(after_risk, floor)
        normal = min(desired, old+cfg.risk_on) if desired > old else max(desired, old-cfg.risk_off)
        target = min(desired, old, cfg.emergency_cap*cfg.max_exposure) if state.emergency else normal
        if floor:
            state.attainable_floor = min(floor, max(state.attainable_floor, old)+cfg.risk_on)
        else:
            state.attainable_floor = 0.
        state.target = float(target)
        out[s] = dict(Base=base*a, TrendReduction=(cfg.max_exposure-base)*a,
                      VolReduction=base*pv*a,
                      DrawdownReduction=base*(combined-pv)*a,
                      FloorCredit=(desired-after_risk)*a,
                      TransitionEffect=(normal-desired)*a,
                      EmergencyReduction=(normal-target)*a,
                      Target=target*a, Desired=desired*a, Healthy=healthy,
                      Emergency=state.emergency, AttainableFloor=state.attainable_floor*a,
                      DDMode=dd_state.mode, DDPenalty=penalty,
                      VolPenalty=pv, DrawdownStandalone=base*penalty*a,
                      FloorActive=bool(floor), EmergencyAge=state.age,
                      EmergencyCalmDays=state.calm,
                      Explanation=(f"{row.Regime}：趋势基础仓位 {base*a:.1%}; "
                                   f"波动率惩罚 {pv:.1%}，回撤惩罚 {penalty:.1%} "
                                   f"（取最大值，不连乘）；牛市参与保护{'已启用' if floor else '未启用'}; "
                                   f"{'紧急防守上限' if state.emergency else '加仓' if desired > old else '常规减仓'}; "
                                   f"下次目标仓位 {target*a:.1%}."))
    return out


@dataclass
class Result:
    history: pd.DataFrame
    exposure: pd.DataFrame
    fills: pd.DataFrame
    events: pd.DataFrame
    decisions: pd.DataFrame
    cycles: pd.DataFrame
    next_decision: pd.DataFrame
    metadata: dict


def _fingerprint(data):
    h = hashlib.sha256()
    for s, d in sorted(data.items()):
        h.update(s.encode())
        h.update(pd.util.hash_pandas_object(d, index=True).to_numpy().tobytes())
    return h.hexdigest()


def backtest(data, cfg=Config(), variant=Variant(), start=None, end=None,
             initial=10000., budgets=None, frozen_decisions=None, unlimited_on=False):
    """严格使用共同交易日历、可分割复权单位及前一收盘时点确定的订单。

    缺少交易日时拒绝运行，不虚构估值或成交。
    frozen_decisions 用于配对诊断，并固定风险策略反馈。
    """
    cfg.validate()
    if not data or initial <= 0 or not np.isfinite(initial):
        raise ValueError("必须提供数据及正的有限初始资金")
    data = {s: validate_frame(d) for s, d in sorted(data.items())}
    symbols = list(data)
    calendar = data[symbols[0]].index
    for s in symbols[1:]:
        if not calendar.equals(data[s].index):
            raise ValueError("资产交易日历不一致。请提供完整且一致的交易日历；不会自动对齐。")
    budgets = dict(budgets) if budgets is not None else {s: 1/len(symbols) for s in symbols}
    if set(budgets) != set(symbols) or any(not np.isfinite(v) or v <= 0 for v in budgets.values()) or sum(budgets.values()) > 1+1e-12:
        raise ValueError("各资产预算必须为正数，且总和不得超过 1")
    feats = {s: features(d, cfg, variant) for s, d in data.items()}
    ready = np.logical_and.reduce([f.Ready.to_numpy() for f in feats.values()])
    eligible = np.flatnonzero(np.r_[False, ready[:-1]])
    if not len(eligible):
        raise ValueError("预热数据不足；至少需要 273 根日线")
    first = pd.Timestamp(start) if start is not None else calendar[eligible[0]]
    last = pd.Timestamp(end) if end is not None else calendar[-1]
    ids = np.flatnonzero((calendar >= first) & (calendar <= last))
    if not len(ids) or ids[0] == 0 or not ready[ids[0]-1]:
        raise ValueError("指定开始日期之前的收盘数据不足以完成预热")
    if len(ids) < 2:
        raise ValueError("至少需要两个交易日")
    states = {s: AssetState() for s in symbols}
    dd = DrawdownState(initial)
    qty = {s: 0. for s in symbols}
    cost_basis = {s: 0. for s in symbols}
    cycle = {}
    cycle_rows, fills, events, dec_rows, exp_rows = [], [], [], [], []
    cash, equity = float(initial), float(initial)
    hist = [dict(Date=calendar[ids[0]-1], Equity=equity, Cash=cash, PositionValue=0.,
                 Exposure=0., Commission=0., SpreadCost=0., SlippageCost=0.,
                 Turnover=0., RealizedPnL=0., UnrealizedPnL=0., Target=0.)]
    realized = 0.
    fee = cfg.commission_bps/1e4
    halfspread = cfg.spread_bps/2e4
    slip = cfg.slippage_bps/1e4
    impact = halfspread+slip
    frozen = None
    if frozen_decisions is not None:
        frozen = frozen_decisions.set_index(["Date", "Symbol"])
    for k in ids:
        date, previous = calendar[k], calendar[k-1]
        rows = {s: feats[s].iloc[k-1] for s in symbols}
        was_emergency = {s: states[s].emergency for s in symbols}
        if frozen is None:
            decisions = make_decisions(rows, states, dd, equity, budgets, cfg, variant)
        else:
            decisions = {}
            for s in symbols:
                plan = frozen.loc[(date, s)].to_dict()
                desired, old = plan["Desired"], states[s].target*budgets[s]
                normal = desired if desired >= old and unlimited_on else (
                    min(desired, old+cfg.risk_on*budgets[s]) if desired > old else
                    max(desired, old-cfg.risk_off*budgets[s]))
                target = min(desired, old, cfg.emergency_cap*cfg.max_exposure*budgets[s]) if plan["Emergency"] else normal
                plan["Target"] = target
                states[s].target = target/budgets[s]
                decisions[s] = plan
        orders = {}
        for s in symbols:
            row, plan = rows[s], decisions[s]
            actual = qty[s]*float(row.Close)/equity
            if variant.kind == "hold" and k != ids[0]:
                delta = 0.
            elif abs(plan["Target"]-actual) <= cfg.no_trade and variant.kind == "continuous" and not plan["Emergency"]:
                delta = 0.
            else:
                wanted = plan["Target"]*equity/float(row.Close)
                # 根据已知收盘价估算买入成本，绝不在开盘时增加交易数量。
                if wanted > qty[s]:
                    wanted = qty[s]+(wanted-qty[s])/((1+impact)*(1+fee))
                delta = max(-qty[s], wanted-qty[s])
            orders[s] = delta
            record = {"Date": date, "SignalDate": previous, "Symbol": s, **plan,
                      "Regime": row.Regime, "Trend": row['T'], "Structure": row.uL,
                      "Momentum": row.uM, "Slope": row.uS, "Sigma": row.Sigma,
                      "VolRatio": row.VolRatio, "StructureBreak": bool(row.StructureBreak),
                      "Shock": bool(row.Shock), "Trigger": bool(row.Trigger),
                      "Return1": row.Return1, "Return5": row.Return5,
                      "PriorExposure": actual, "OrderUnits": delta,
                      "ClosePrice": row.Close, "Budget": budgets[s],
                      "ConstraintViolation": bool(plan.get("FloorActive", False) and plan["Target"]+1e-10 < plan["AttainableFloor"])}
            dec_rows.append(record)
            if bool(plan["Emergency"]) != was_emergency[s] or (row.Trigger and variant.emergency and variant.kind == "continuous"):
                events.append(dict(Date=date, SignalDate=previous, Symbol=s,
                                   Event="TRIGGER" if row.Trigger else "RELEASE",
                                   StructureBreak=bool(row.StructureBreak), Shock=bool(row.Shock),
                                   Return1=row.Return1, Return5=row.Return5,
                                   Target=plan["Target"]))
        daily_fee = daily_spread = daily_slip = daily_turnover = 0.

        def execute(s, delta, cash_scale=1.):
            nonlocal cash, daily_fee, daily_spread, daily_slip, daily_turnover, realized
            if abs(delta) <= 1e-12:
                return
            op = float(data[s].Open.iloc[k])
            fill = op*(1+np.sign(delta)*impact)
            commission = abs(delta)*fill*fee
            spread_cost = abs(delta)*op*halfspread
            slip_cost = abs(delta)*op*slip
            cash -= delta*fill+commission
            if delta > 0:
                if qty[s] <= 1e-12:
                    cycle[s] = dict(Symbol=s, EntryDate=date, PnL=0.)
                cost_basis[s] += delta*fill+commission
            else:
                allocated = cost_basis[s]*(-delta/qty[s])
                pnl = -delta*fill-commission-allocated
                cost_basis[s] -= allocated
                realized += pnl
                cycle[s]["PnL"] += pnl
            qty[s] += delta
            if qty[s] < 1e-10:
                qty[s], cost_basis[s] = 0., 0.
                if s in cycle:
                    cycle_rows.append({**cycle.pop(s), "ExitDate": date,
                                       "HoldingDays": (date-cycle_start[s]).days})
            daily_fee += commission
            daily_spread += spread_cost
            daily_slip += slip_cost
            daily_turnover += abs(delta)*op/equity
            fills.append(dict(Date=date, SignalDate=previous, Symbol=s,
                              Side="BUY" if delta > 0 else "SELL", Units=abs(delta),
                              ReferencePrice=op, FillPrice=fill, Commission=commission,
                              SpreadCost=spread_cost, SlippageCost=slip_cost,
                              CashAfter=cash, CashScale=cash_scale,
                              Reason="Emergency" if decisions[s]["Emergency"] else "Target rebalance"))
        cycle_start = {s: c["EntryDate"] for s, c in cycle.items()}
        for s in symbols:
            if orders[s] < 0:
                execute(s, orders[s])
        needed = sum(max(0, orders[s])*float(data[s].Open.iloc[k])*(1+impact)*(1+fee) for s in symbols)
        scale = min(1., max(0., cash)/needed) if needed > 0 else 1.
        for s in symbols:
            if orders[s] > 0:
                execute(s, orders[s]*scale, scale)
        if cash < -1e-7 or any(q < -1e-10 for q in qty.values()):
            raise AssertionError("现金或持仓数量守恒校验失败")
        cash = max(0., cash)
        values = {s: qty[s]*float(data[s].Close.iloc[k]) for s in symbols}
        equity = cash+sum(values.values())
        unrealized = sum(values[s]-cost_basis[s] for s in symbols)
        if not np.isclose(equity, initial+realized+unrealized, atol=1e-6, rtol=1e-10):
            raise AssertionError("已实现盈亏与未实现盈亏之和无法对账")
        if equity <= 0:
            raise AssertionError("账户净值非正")
        hist.append(dict(Date=date, Equity=equity, Cash=cash,
                         PositionValue=sum(values.values()), Exposure=sum(values.values())/equity,
                         Commission=daily_fee, SpreadCost=daily_spread, SlippageCost=daily_slip,
                         Turnover=daily_turnover, RealizedPnL=realized, UnrealizedPnL=unrealized,
                         Target=sum(d["Target"] for d in decisions.values())))
        for s in symbols:
            exp_rows.append(dict(Date=date, Symbol=s, Units=qty[s], PositionValue=values[s],
                                 Exposure=values[s]/equity, CostBasis=cost_basis[s]))
    history = pd.DataFrame(hist).set_index("Date")
    history["Return"] = history.Equity.pct_change(fill_method=None).fillna(0.)
    history["Drawdown"] = history.Equity/history.Equity.cummax()-1
    history["Cost"] = history.Commission+history.SpreadCost+history.SlippageCost
    preview_states, preview_dd = deepcopy(states), deepcopy(dd)
    preview_rows = {s: feats[s].loc[calendar[ids[-1]]] for s in symbols}
    nxt = make_decisions(preview_rows, preview_states, preview_dd, equity, budgets, cfg, variant)
    next_decision = pd.DataFrame(nxt).T
    next_decision.index.name = "Symbol"
    next_decision["SignalDate"] = calendar[ids[-1]]
    next_decision["Regime"] = [preview_rows[s].Regime for s in next_decision.index]
    next_decision["Trend"] = [preview_rows[s]["T"] for s in next_decision.index]
    next_decision["Sigma"] = [preview_rows[s].Sigma for s in next_decision.index]
    meta = dict(version=VERSION, config=asdict(cfg), variant=asdict(variant),
                data_sha256=_fingerprint(data), budgets=budgets, initial=initial,
                start=str(calendar[ids[0]].date()), end=str(calendar[ids[-1]].date()),
                unit_model="fractional adjusted synthetic units", cash_rate=0.,
                open_cycles=len(cycle), end_policy="mark to market; no forced liquidation")
    return Result(history, pd.DataFrame(exp_rows), pd.DataFrame(fills), pd.DataFrame(events),
                  pd.DataFrame(dec_rows), pd.DataFrame(cycle_rows), next_decision, meta)


def metrics(result, benchmark=None):
    h = result.history
    r = h.Return.iloc[1:]
    years = (h.index[-1]-h.index[0]).days/365.25
    total = h.Equity.iloc[-1]/h.Equity.iloc[0]-1
    cagr = (1+total)**(1/years)-1 if years > 0 else np.nan
    vol = r.std(ddof=1)*np.sqrt(252)
    downside = np.sqrt(np.mean(np.minimum(r, 0)**2))*np.sqrt(252)
    dd = abs(h.Drawdown.min())
    cycles = result.cycles
    pnl = cycles.PnL if len(cycles) else pd.Series(dtype=float)
    losses = -pnl[pnl < 0].sum()
    out = dict(TotalReturn=total, CAGR=cagr, MaxDrawdown=-dd, Volatility=vol,
               Sharpe=r.mean()*252/vol if vol > 1e-12 else np.nan,
               Sortino=r.mean()*252/downside if downside > 1e-12 else np.nan,
               Calmar=cagr/dd if dd > 1e-12 else np.nan,
               AverageExposure=h.Exposure.iloc[1:].mean(),
               TimeInMarket=(h.Exposure.iloc[1:] > 1e-12).mean(),
               Turnover=h.Turnover.sum()/years,
               TransactionCosts=h.Cost.sum(), Fills=len(result.fills),
               ClosedCycles=len(cycles), OpenCycles=result.metadata["open_cycles"],
               WinRate=(pnl > 0).mean() if len(pnl) else np.nan,
               ProfitFactor=pnl[pnl > 0].sum()/losses if losses > 0 else np.nan,
               AverageHoldingDays=cycles.HoldingDays.mean() if len(cycles) else np.nan,
               UpsideCapture=np.nan, DownsideCapture=np.nan,
               UpMonths=0, DownMonths=0, DrawdownReduction=np.nan)
    if benchmark is not None:
        bh = benchmark.history.reindex(h.index)
        if bh.Equity.isna().any():
            raise ValueError("基准日期必须一致")
        pair = pd.DataFrame({"Q": h.Return.iloc[1:], "B": bh.Return.iloc[1:]})
        monthly = pair.groupby(pair.index.to_period("M")).apply(lambda z: (1+z).prod()-1)
        # 首尾月份可能不完整。为保守起见，计算捕获率时将两者均剔除。
        monthly = monthly.iloc[1:-1]
        for label, mask in (("Upside", monthly.B > 0), ("Downside", monthly.B < 0)):
            subset = monthly.loc[mask]
            out["UpMonths" if label == "Upside" else "DownMonths"] = len(subset)
            if len(subset) >= 3 and abs(subset.B.mean()) > 1e-12:
                out[label+"Capture"] = subset.Q.mean()/subset.B.mean()
        bdd = abs(bh.Drawdown.min())
        out["DrawdownReduction"] = 1-dd/bdd if bdd > 1e-12 else np.nan
    return out


def run_ablation(data, cfg=Config(), start=None, end=None, initial=10000., include_deletions=True):
    models = variants()
    if not include_deletions:
        models = dict(list(models.items())[:6])
    results = {name: backtest(data, cfg, v, start, end, initial) for name, v in models.items()}
    benchmark = results["A Buy & Hold"]
    table = pd.DataFrame({name: metrics(r, benchmark) for name, r in results.items()}).T
    parent = {"D C + Volatility": "C Continuous", "E C + Drawdown": "C Continuous",
              "F Full V2": "C Continuous"}
    for name in table.index:
        if name.startswith("F −"): parent[name] = "F Full V2"
        if name.startswith("C −"): parent[name] = "C Continuous"
    delta = pd.DataFrame({name: table.loc[name]-table.loc[base] for name, base in parent.items() if name in table.index}).T
    delta["ComparedWith"] = pd.Series(parent)
    return table, delta, results


def participation_diagnostics(result, cfg=Config()):
    d = result.decisions.merge(result.exposure[["Date", "Symbol", "Exposure"]], on=["Date", "Symbol"])
    d["Tolerance"] = cfg.no_trade
    d["Shortfall"] = (d.AttainableFloor-d.Exposure-d.Tolerance).clip(lower=0)
    d["RollingGap"] = 0.
    d["Warning"] = False
    window = math.ceil(cfg.max_exposure/cfg.risk_on)
    for _, group in d.groupby("Symbol", sort=False):
        ok = group.Healthy.astype(bool)
        gaps = group.Shortfall.rolling(window).mean()
        full = ok.rolling(window).sum().eq(window)
        d.loc[group.index, "RollingGap"] = gaps.to_numpy()
        d.loc[group.index, "Warning"] = (full & (gaps > 1e-8)).to_numpy()
    return d


def regime_diagnostics(result, benchmark):
    """基于前一收盘时点划分连续市场状态区间；绝不拼接不相连区间的回撤。"""
    if result.decisions.Symbol.nunique() != 1:
        return pd.DataFrame()
    labels = result.decisions.set_index("Date").Regime
    groups = labels.ne(labels.shift()).cumsum()
    rows = []
    for _, g in labels.groupby(groups):
        dates = g.index
        q = result.history.loc[dates, "Return"]
        b = benchmark.history.loc[dates, "Return"]
        def dd(r):
            v = np.r_[1., (1+r).cumprod().to_numpy()]
            return np.min(v/np.maximum.accumulate(v)-1)
        rows.append(dict(Start=dates[0], End=dates[-1], Regime=g.iloc[0], Days=len(dates),
                         QuantumReturn=(1+q).prod()-1, BenchmarkReturn=(1+b).prod()-1,
                         QuantumDD=dd(q), BenchmarkDD=dd(b),
                         AverageExposure=result.history.loc[dates, "Exposure"].mean()))
    return pd.DataFrame(rows)


def recovery_diagnostic(data, full, benchmark, cfg=Config()):
    """用于描述的事后 V 型窗口；重放仅改变加仓速度限制。

    趋势、风险惩罚、参与下限及紧急防守路径均固定为原始路径。
    这是配对归因实验，并非可独立用于投资的策略。
    """
    shadow = backtest(data, cfg, start=full.metadata["start"], end=full.metadata["end"],
                      initial=full.metadata["initial"], budgets=full.metadata["budgets"],
                      frozen_decisions=full.decisions, unlimited_on=True)
    b = benchmark.history.Equity
    records, used_until = [], -1
    for i in range(20, len(b)-20):
        if i <= used_until:
            continue
        prior = b.iloc[i-20:i]
        decline = b.iloc[i]/prior.max()-1
        future = b.iloc[i+1:i+21]
        trough = b.iloc[i] <= min(prior.min(), future.min())
        recovery = future/b.iloc[i]-1
        crossings = np.flatnonzero(recovery.to_numpy() >= .08)
        if decline <= -.08 and trough and len(crossings):
            j = i+1+int(crossings[0])
            qret = full.history.Equity.iloc[j]/full.history.Equity.iloc[i]-1
            sret = shadow.history.Equity.iloc[j]/shadow.history.Equity.iloc[i]-1
            records.append(dict(Trough=b.index[i], RecoveryEnd=b.index[j],
                                Days=j-i, PrecedingDecline=decline,
                                BenchmarkRecovery=b.iloc[j]/b.iloc[i]-1,
                                QuantumRecovery=qret, UnlimitedOnReplay=sret,
                                RiskOnMissedReturn=sret-qret))
            used_until = i+20
    return pd.DataFrame(records), shadow


def sensitivity(data, cfg=Config(), start=None, end=None, initial=10000.):
    """固定的单因素实验，按滞后波动率分组。"""
    settings = [("固定规则", cfg)]
    for threshold in (-.06, -.08, -.12, -.15):
        settings.append((f"单日冲击 {threshold:.0%}", replace(cfg, shock_day=threshold)))
    for threshold in (-.05, -.12):
        settings.append((f"五日冲击 {threshold:.0%}", replace(cfg, shock_five=threshold)))
    for threshold in (1.5, 2.1):
        settings.append((f"波动冲击比率 {threshold}", replace(cfg, shock_ratio=threshold)))
    for threshold in (.20, .40):
        settings.append((f"波动冲击绝对值 {threshold:.0%}", replace(cfg, shock_absolute=threshold)))
    for window in (150, 250):
        settings.append((f"长期趋势窗口 {window}", replace(cfg, long_window=window)))
    for window in (84, 168):
        settings.append((f"动量窗口 {window}", replace(cfg, momentum_window=window)))
    for factor in (.75, 1.25):
        settings.append((f"特征尺度 x{factor}", replace(cfg, structure_scale=cfg.structure_scale*factor,
                         momentum_scale=cfg.momentum_scale*factor, slope_scale=cfg.slope_scale*factor)))
    for count in (2, 5):
        settings.append((f"市场状态确认次数 {count}", replace(cfg, regime_confirm=count)))
    for count in (3, 10):
        settings.append((f"健康市场确认次数 {count}", replace(cfg, healthy_confirm=count)))
    for factor in (.75, 1.25):
        settings.append((f"加仓速度 x{factor}", replace(cfg, risk_on=cfg.risk_on*factor)))
        settings.append((f"减仓速度 x{factor}", replace(cfg, risk_off=cfg.risk_off*factor)))
        settings.append((f"回撤保护解除速度 x{factor}", replace(cfg, dd_recovery=cfg.dd_recovery*factor)))
    for band in (.01, .03):
        settings.append((f"不交易区间 {band:.0%}", replace(cfg, no_trade=band)))
    for cost in (2, 3):
        settings.append((f"成本 x{cost}", replace(cfg, commission_bps=cfg.commission_bps*cost,
                        spread_bps=cfg.spread_bps*cost, slippage_bps=cfg.slippage_bps*cost)))
    records = []
    for symbol, frame in data.items():
        benchmark = backtest({symbol: frame}, cfg, variants()["A Buy & Hold"], start, end, initial)
        for name, config in settings:
            r = backtest({symbol: frame}, config, start=start, end=end, initial=initial)
            record = dict(Symbol=symbol, Experiment=name, **metrics(r, benchmark))
            record["EmergencyTriggers"] = int(r.decisions.Trigger.sum())
            record["EmergencyDays"] = int(r.decisions.Emergency.sum())
            records.append(record)
            # 阈值分组仅用于描述，不进行优化，也不用于策略决策。
            for low, high, label in ((0, .20, "低波动 <20%"), (.20, .40, "中波动 20–40%"), (.40, np.inf, "高波动 >=40%")):
                g = r.decisions.loc[(r.decisions.Sigma >= low) & (r.decisions.Sigma < high)]
                records.append(dict(Symbol=symbol, Experiment=name, VolatilityProfile=label,
                                    Days=len(g), EmergencyTriggers=int(g.Trigger.sum()),
                                    EmergencyDays=int(g.Emergency.sum()),
                                    AverageTarget=g.Target.mean()))
    return pd.DataFrame(records)


def demo_data(symbols=("DEMO",), periods=1600, seed=17):
    """仅生成确定性的合成路径。绝不将其展示为历史价格。"""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-02", periods=periods)
    data = {}
    for j, symbol in enumerate(symbols):
        means = np.full(periods, .0006)
        means[650:790] = -.002
        means[790:900] = .003
        means[1100:1250] = -.001
        noise = rng.normal(0, .009+j*.004, periods)
        if periods > 751: noise[750] -= .12
        close = 100*np.exp(np.cumsum(means+noise))
        op = np.r_[close[0], close[:-1]]*np.exp(rng.normal(0, .002, periods))
        data[symbol] = pd.DataFrame(dict(Open=op, High=np.maximum(op, close)*1.004,
                                        Low=np.minimum(op, close)*.996, Close=close,
                                        Volume=np.full(periods, 2e6)), index=index)
    return data


def export_bundle(result, tables=None):
    buff = BytesIO()
    with zipfile.ZipFile(buff, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(result.metadata, indent=2, ensure_ascii=False))
        for name in ("history", "exposure", "fills", "events", "decisions", "cycles", "next_decision"):
            z.writestr(name+".csv", getattr(result, name).to_csv(index=name in ("history", "next_decision")))
        for name, table in (tables or {}).items():
            z.writestr(name+".csv", table.to_csv())
    return buff.getvalue()


def period_diagnostics(result, benchmark):
    """固定策略下按自然年连续评估；不逐年重新拟合参数。"""
    rows = []
    dates = result.history.index[1:]
    for year in sorted(set(dates.year)):
        ix = dates[dates.year == year]
        q, b = result.history.loc[ix], benchmark.history.loc[ix]
        def local_dd(returns):
            path = np.r_[1., (1+returns).cumprod().to_numpy()]
            return (path/np.maximum.accumulate(path)-1).min()
        rows.append(dict(Year=year, Days=len(ix), QuantumReturn=(1+q.Return).prod()-1,
                         BenchmarkReturn=(1+b.Return).prod()-1,
                         QuantumDD=local_dd(q.Return), BenchmarkDD=local_dd(b.Return),
                         AverageExposure=q.Exposure.mean(), Turnover=q.Turnover.sum(),
                         TransactionCosts=q.Cost.sum()))
    return pd.DataFrame(rows)


def chronological_diagnostics(result, benchmark):
    """按 60/20/20 划分报告区间，持仓连续，不拟合规则。

    这些名称并不证明最后一个区间此前确实未被查看。
    """
    dates = result.history.index[1:]
    bounds = (0, int(.6*len(dates)), int(.8*len(dates)), len(dates))
    output = []
    for label, begin, finish in zip(("研究区间 60%", "验证区间 20%", "最终区间 20%"), bounds[:-1], bounds[1:]):
        if finish-begin < 2: continue
        ix = result.history.index[begin:finish+1]
        def cut(r):
            h = r.history.loc[ix].copy()
            h.iloc[0, h.columns.get_loc("Return")] = 0.
            for col in ("Commission", "SpreadCost", "SlippageCost", "Cost", "Turnover"):
                h.iloc[0, h.columns.get_loc(col)] = 0.
            h["Drawdown"] = h.Equity/h.Equity.cummax()-1
            fills = r.fills.loc[(r.fills.Date >= ix[1]) & (r.fills.Date <= ix[-1])] if len(r.fills) else r.fills
            cycles = r.cycles.loc[(r.cycles.ExitDate >= ix[1]) & (r.cycles.ExitDate <= ix[-1])] if len(r.cycles) else r.cycles
            return replace(r, history=h, fills=fills, cycles=cycles)
        stats = metrics(cut(result), cut(benchmark))
        # 交易周期汇总可能跨越区间边界，因此不纳入此表。
        keep = ("TotalReturn", "CAGR", "MaxDrawdown", "Volatility", "Sharpe", "Sortino", "Calmar",
                "UpsideCapture", "DownsideCapture", "AverageExposure", "Turnover", "TransactionCosts")
        output.append(dict(Interval=label, Start=ix[1], End=ix[-1], **{k: stats[k] for k in keep}))
    return pd.DataFrame(output)


def load_csv_files(files):
    data = {}
    for name, content in files:
        raw = pd.read_csv(BytesIO(content))
        lookup = {str(c).lower(): c for c in raw.columns}
        if "date" not in lookup:
            raise ValueError(f"{name}：必须包含 Date 列")
        rename = {lookup[k.lower()]: k for k in ("Date", "Open", "High", "Low", "Close", "Volume") if k.lower() in lookup}
        if "symbol" in lookup: rename[lookup["symbol"]] = "Symbol"
        raw = raw.rename(columns=rename)
        if "Symbol" not in raw:
            raw["Symbol"] = name.rsplit(".", 1)[0].upper()
        for symbol, group in raw.groupby("Symbol"):
            if symbol in data: raise ValueError(f"标的代码重复：{symbol}")
            group = group.copy()
            group["Date"] = pd.to_datetime(group.Date, errors="raise")
            data[str(symbol)] = validate_frame(group.set_index("Date"))
    if not data: raise ValueError("请至少上传一个 OHLCV CSV 文件")
    return data


def download_history(symbols, start, end):
    import yfinance as yf
    data = {}
    for symbol in symbols:
        d = yf.Ticker(symbol).history(start=str(start), end=str(end), auto_adjust=True,
                                      actions=False, raise_errors=True, timeout=15)
        if d is None or d.empty:
            raise ValueError(f"没有 {symbol} 的数据；请尝试上传复权 OHLCV CSV 文件")
        data[symbol] = validate_frame(d)
    return data


def chart_dashboard(result, benchmark):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    h, b = result.history, benchmark.history
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=[.45, .20, .25, .10], vertical_spacing=.04,
                        subplot_titles=("账户净值", "回撤", "市场仓位", "前一收盘时点的市场状态"))
    fig.add_trace(go.Scatter(x=h.index, y=h.Equity, name="Quantum", line=dict(color="#52d6c7", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=b.index, y=b.Equity, name="买入并持有", line=dict(color="#a6b3cc", width=1.5)), row=1, col=1)
    for frame, name, color in ((h, "Quantum 回撤", "#52d6c7"), (b, "基准回撤", "#a6b3cc")):
        fig.add_trace(go.Scatter(x=frame.index, y=frame.Drawdown, name=name, line=dict(color=color), showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=h.index, y=h.Exposure, name="实际仓位", fill="tozeroy", line=dict(color="#52d6c7")), row=3, col=1)
    fig.add_trace(go.Scatter(x=h.index, y=h.Target, name="执行目标仓位", line=dict(color="#e8bf79", dash="dot")), row=3, col=1)
    states = result.decisions.pivot(index="Symbol", columns="Date", values="Regime")
    code = states.replace({"Bear": -1, "Neutral": 0, "Bull": 1})
    fig.add_trace(go.Heatmap(x=code.columns, y=code.index, z=code.to_numpy(dtype=float),
                            text=states.to_numpy(), hovertemplate="%{y}: %{text}<extra></extra>",
                            colorscale=[[0, "#773f48"], [.5, "#333d50"], [1, "#276a60"]],
                            zmin=-1, zmax=1, showscale=False), row=4, col=1)
    fig.update_yaxes(tickformat=".0%", row=2, col=1)
    fig.update_yaxes(tickformat=".0%", range=[0, 1.04], row=3, col=1)
    fig.update_layout(height=780, template="plotly_dark", paper_bgcolor="#0c1320",
                      plot_bgcolor="#0c1320", margin=dict(l=20, r=20, t=40, b=20),
                      legend=dict(orientation="h", y=1.09), hovermode="x unified")
    return fig


def formatted_metrics(table):
    pct = ["TotalReturn", "CAGR", "MaxDrawdown", "Volatility", "AverageExposure",
           "TimeInMarket", "WinRate", "UpsideCapture", "DownsideCapture", "DrawdownReduction"]
    formats = {c: "{:.1%}" for c in pct if c in table.columns}
    formats.update({c: "{:.2f}" for c in ("Sharpe", "Sortino", "Calmar", "ProfitFactor", "Turnover") if c in table.columns})
    if "TransactionCosts" in table: formats["TransactionCosts"] = "{:,.2f}"
    return table.style.format(formats, na_rep="不适用").format_index(lambda label: {"A Buy & Hold": "A 买入并持有", "B SMA200": "B SMA200 趋势", "C Continuous": "C 连续仓位", "D C + Volatility": "D C + 波动率修正", "E C + Drawdown": "E C + 回撤保护", "F Full V2": "F 完整 V2", "F − Volatility": "F − 波动率修正", "F − Drawdown": "F − 回撤保护", "F − Participation floor": "F − 参与下限", "F − Emergency": "F − 紧急防守", "F − Regime memory": "F − 市场状态记忆", "C − Momentum": "C − 动量", "C − Slope": "C − 斜率", "Quantum": "Quantum", "Buy & Hold": "买入并持有"}.get(label, label), axis=0)


def main():
    import streamlit as st
    import plotly.graph_objects as go
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    st.set_page_config(page_title="QuantumSignal V2", page_icon="◈", layout="wide")
    st.markdown("""<style>
    .stApp {background:#0c1320;color:#e0e6f0}
    .block-container {max-width:1500px;padding-top:2rem}
    [data-testid="stMetric"] {background:#131e30;padding:16px;border:1px solid #25334b;border-radius:8px}
    [data-testid="stSidebar"] {background:#101a2b}
    h1,h2,h3 {letter-spacing:-.025em}
    </style>""", unsafe_allow_html=True)
    st.title("QuantumSignal V2")
    st.caption("自适应趋势参与 · 固定规则 · 仅做多 · 无杠杆")
    with st.sidebar:
        st.header("研究配置")
        source = st.selectbox("数据来源", ["Synthetic demo", "Yahoo adjusted daily data", "Upload adjusted OHLCV CSV"], format_func={"Synthetic demo": "合成数据演示", "Yahoo adjusted daily data": "Yahoo 复权日线数据", "Upload adjusted OHLCV CSV": "上传复权 OHLCV CSV"}.get)
        name = st.selectbox("风险预设", ["Balanced", "Conservative", "Aggressive"], format_func={"Balanced": "均衡", "Conservative": "保守", "Aggressive": "积极"}.get)
        cfg = preset_config(name)
        capital = st.number_input("初始资金", min_value=100., value=10000., step=1000.)
        symbols_text = st.text_input("标的代码 / 演示配置", "DEMO" if source == "Synthetic demo" else "SPY")
        if source == "Synthetic demo":
            st.caption("使用 DEMO、MEDIUM、HIGH 查看不同的合成波动率情景。")
        today = datetime.now(ZoneInfo("America/New_York")).date()
        default_start = pd.Timestamp("2019-03-01").date() if source == "Synthetic demo" else today-timedelta(days=365*5)
        start_date = st.date_input("回测开始日期", default_start)
        end_date = st.date_input("回测结束日期", pd.Timestamp("2024-02-16").date() if source == "Synthetic demo" else today-timedelta(days=1))
        uploads = st.file_uploader("复权 OHLCV 文件", type="csv", accept_multiple_files=True) if source == "Upload adjusted OHLCV CSV" else []
        with st.expander("执行假设"):
            fee = st.number_input("单边佣金（基点）", 0., 100., cfg.commission_bps)
            spread = st.number_input("完整买卖价差（基点）", 0., 100., cfg.spread_bps)
            slip = st.number_input("单边额外滑点（基点）", 0., 100., cfg.slippage_bps)
            cfg = replace(cfg, commission_bps=fee, spread_bps=spread, slippage_bps=slip)
            st.caption("根据前一收盘价确定交易单位数，在下一开盘时执行。现金不足时缩减买入量。使用可分割的复权研究单位。现金收益率为零。回测结束时不强制卖出。")
        st.caption("策略参数固定。敏感性实验不会改变所选策略。")
        run = st.button("运行研究", type="primary", width="stretch")
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols_text.replace(" ", ",").split(",") if s.strip()))
    signature = json.dumps(dict(source=source, cfg=asdict(cfg), capital=capital, symbols=symbols,
                                start=str(start_date), end=str(end_date),
                                uploads=[(f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in uploads]), sort_keys=True)
    cached = st.session_state.get("research")
    if run or (cached is None and source == "Synthetic demo"):
        try:
            if not symbols and source != "Upload adjusted OHLCV CSV": raise ValueError("请至少输入一个标的代码")
            if len(symbols) > 12: raise ValueError("每次交互运行最多支持 12 个资产")
            if end_date <= start_date: raise ValueError("结束日期必须晚于开始日期")
            with st.spinner("正在校验数据并运行记账引擎…"):
                if source == "Synthetic demo":
                    data = demo_data(tuple(symbols))
                elif source == "Upload adjusted OHLCV CSV":
                    data = load_csv_files([(f.name, f.getvalue()) for f in uploads])
                else:
                    cached_download = st.cache_data(ttl=3600, show_spinner=False)(download_history)
                    data = cached_download(tuple(symbols), start_date-timedelta(days=650), min(end_date+timedelta(days=1), today))
                result = backtest(data, cfg, start=start_date, end=end_date, initial=capital)
                benchmark = backtest(data, cfg, variants()["A Buy & Hold"], start_date, end_date, capital)
                zero = replace(cfg, commission_bps=0., spread_bps=0., slippage_bps=0.)
                gross = backtest(data, zero, start=start_date, end=end_date, initial=capital)
                participation = participation_diagnostics(result, cfg)
                recoveries, recovery_shadow = recovery_diagnostic(data, result, benchmark, cfg)
                cached = dict(signature=signature, data=data, result=result, benchmark=benchmark, gross=gross,
                              participation=participation, recoveries=recoveries, recovery_shadow=recovery_shadow,
                              cfg=cfg, source=source)
                st.session_state.research = cached
        except Exception as exc:
            st.error(f"研究运行未能完成：{exc}")
            st.info("CSV 输入请使用 Date、Open、High、Low、Close、Volume 列；Symbol 列可选。请提供开始日期之前至少 280 个交易日的数据；投资组合中各资产的交易日历必须完整且一致。")
    if cached is None:
        st.info("请选择数据来源并运行研究引擎。")
        return
    if cached["signature"] != signature:
        st.warning("设置已更改。下方仍显示上一次运行的结果；请点击“运行研究”应用更改。")
    result, benchmark, cfg = cached["result"], cached["benchmark"], cached["cfg"]
    data = cached["data"]
    if cached["source"] == "Synthetic demo":
        st.info("合成数据演示——使用生成的价格路径测试系统行为。这些结果不是历史市场收益，也不是投资表现的证据。")
    meta = result.metadata
    st.caption(f"{meta['config']['preset']} · {meta['start']} → {meta['end']} · {', '.join(data)} · 数据指纹 {meta['data_sha256'][:12]} · {VERSION}")
    page = st.radio("工作区", ["Overview", "Strategy", "Backtest", "Diagnostics", "Settings"], horizontal=True, label_visibility="collapsed", format_func={"Overview": "总览", "Strategy": "策略", "Backtest": "回测", "Diagnostics": "诊断", "Settings": "设置"}.get)
    m, bm = metrics(result, benchmark), metrics(benchmark, benchmark)
    h, nxt = result.history, result.next_decision
    if page == "Overview":
        c = st.columns(4)
        regimes = " / ".join(nxt.Regime.unique())
        c[0].metric("市场状态", regimes)
        c[1].metric("下次执行目标仓位", f"{nxt.Target.astype(float).sum():.1%}")
        c[2].metric("实际仓位", f"{h.Exposure.iloc[-1]:.1%}")
        c[3].metric("当前回撤", f"{h.Drawdown.iloc[-1]:.1%}")
        c = st.columns(4)
        c[0].metric("账户净值", f"{h.Equity.iloc[-1]:,.2f}")
        c[1].metric("相对买入并持有的收益差", f"{m['TotalReturn']-bm['TotalReturn']:+.1%}")
        c[2].metric("现金", f"{h.Cash.iloc[-1]/h.Equity.iloc[-1]:.1%}")
        risk = "紧急防守" if nxt.Emergency.any() else "回撤保护" if nxt.DDPenalty.astype(float).max() > 0 else "正常"
        c[3].metric("风险状态", risk)
        st.caption("目标仓位基于最近一个已完成交易日的收盘数据，用于下一交易日。实际仓位来自模拟账户，并非已连接的券商账户。")
        st.plotly_chart(chart_dashboard(result, benchmark), width="stretch")
        last = result.decisions.groupby("Symbol", sort=False).tail(2)
        st.subheader("近期决策")
        st.dataframe(last[["SignalDate", "Symbol", "Regime", "Base", "Desired", "Target", "Emergency", "DDMode"]], hide_index=True, width="stretch", column_config={"SignalDate": "信号日期", "Symbol": "标的", "Regime": "市场状态", "Base": "基础仓位", "Desired": "期望仓位", "Target": "目标仓位", "Emergency": "紧急防守", "DDMode": "回撤保护状态"})
        warnings = cached["participation"]
        if warnings.ConstraintViolation.any(): st.error("检测到违反参与约束的情况。使用此结果前请查看“诊断”。")
        elif warnings.groupby("Symbol").tail(1).Warning.any(): st.warning("参与度警告——仓位持续低于健康牛市中可达到的仓位范围。")
    elif page == "Strategy":
        st.subheader("为什么是这个仓位？")
        symbol = st.selectbox("资产", list(data))
        p = nxt.loc[symbol]
        budget = meta["budgets"][symbol]
        labels = ["资金仓位上限", "趋势转弱", "波动率", "回撤保护（增量）", "牛市参与保护", "常规仓位过渡", "紧急防守", "最终目标仓位"]
        vals = [cfg.max_exposure*budget, -float(p.TrendReduction), -float(p.VolReduction),
                -float(p.DrawdownReduction), float(p.FloorCredit), float(p.TransitionEffect),
                -float(p.EmergencyReduction), float(p.Target)]
        fig = go.Figure(go.Waterfall(x=labels, y=vals, measure=["absolute"]+["relative"]*6+["total"],
                                    increasing=dict(marker=dict(color="#52d6c7")), decreasing=dict(marker=dict(color="#e17e87"))))
        fig.update_layout(template="plotly_dark", height=430, yaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption("通过精确的加减分解展示目标仓位的形成过程。先展示波动率影响；在 max(波动率惩罚, 回撤惩罚) 规则下，回撤仅贡献超出波动率惩罚的部分。下方列出各自独立的惩罚幅度，避免实际起约束作用的回撤保护因展示顺序而被掩盖。")
        st.dataframe(nxt, width="stretch", column_config={"Date": "日期", "SignalDate": "信号日期", "Symbol": "标的", "Regime": "市场状态", "Base": "基础仓位", "Desired": "期望仓位", "Target": "目标仓位", "Emergency": "紧急防守", "DDMode": "回撤保护状态", "TrendReduction": "趋势减仓", "VolReduction": "波动率减仓", "DrawdownReduction": "回撤削减幅度", "FloorCredit": "参与下限补回仓位", "TransitionEffect": "仓位过渡影响", "EmergencyReduction": "紧急防守减仓", "Healthy": "健康牛市资格", "AttainableFloor": "可达到的参与下限", "DDPenalty": "回撤惩罚", "VolPenalty": "波动率惩罚", "DrawdownStandalone": "独立回撤减仓幅度", "FloorActive": "参与下限已启用", "EmergencyAge": "紧急防守持续天数", "EmergencyCalmDays": "紧急防守平静天数", "Explanation": "决策说明", "Trend": "趋势分数", "Sigma": "年化波动率", "Days": "交易日数", "QuantumReturn": "Quantum 收益率", "BenchmarkReturn": "基准收益率", "QuantumDD": "Quantum 回撤", "BenchmarkDD": "基准回撤", "Year": "年份", "Exposure": "实际仓位", "Shortfall": "仓位缺口", "Warning": "参与度警告", "Trough": "低点日期", "RecoveryEnd": "恢复结束日期", "PrecedingDecline": "此前跌幅", "BenchmarkRecovery": "基准恢复收益率", "QuantumRecovery": "Quantum 恢复收益率", "UnlimitedOnReplay": "取消加仓限速的重放收益率", "RiskOnMissedReturn": "加仓限速错失收益率", "Event": "事件", "StructureBreak": "结构破坏", "Shock": "波动冲击", "Return1": "单日收益率", "Return5": "五日收益率", "Commission": "佣金", "SpreadCost": "价差成本", "SlippageCost": "滑点成本", "Cost": "总成本", "Structure": "结构证据", "Momentum": "动量证据", "Slope": "斜率证据", "VolRatio": "波动率比值", "Trigger": "紧急防守触发", "PriorExposure": "前一收盘仓位", "OrderUnits": "订单单位数", "ClosePrice": "收盘价", "Budget": "资金预算占比", "ConstraintViolation": "参与约束违规", "Side": "交易方向", "Units": "单位数", "ReferencePrice": "参考价格", "FillPrice": "成交价格", "CashAfter": "成交后现金", "CashScale": "现金缩放系数", "Reason": "成交原因", "EntryDate": "入场日期", "ExitDate": "退出日期", "PnL": "盈亏", "HoldingDays": "持仓天数", "Experiment": "实验", "EmergencyTriggers": "紧急防守触发次数", "EmergencyDays": "紧急防守天数", "VolatilityProfile": "波动率分组", "AverageTarget": "平均目标仓位"})
        st.markdown("""**五个问题，五个答案**

- **趋势：**结构、六个月动量及趋势斜率决定基础仓位。
- **波动率：**仅在相对自身历史正常水平异常上升时降低仓位；Balanced 下最多削减基础仓位的 20%。
- **回撤：**共享账户防止亏损扩大，无需净值创新高即可开始恢复。
- **参与度：**符合条件的健康牛市中，在考虑仓位过渡速度前，至少保留基础仓位的 85%。
- **紧急防守：**严重结构破坏叠加冲击或亏损证据时，绕过常规速度限制。

趋势组件是相互关联的价格证据，并非独立概率。紧急防守条件代表不同风险维度，并非统计上独立的观测。
""")
        with st.expander("固定公式"):
            st.latex(r"T=0.50\,clip(L/0.08)+0.25\,clip(M/0.15)+0.25\,clip(S/0.02)")
            st.latex(r"B=E_{max}(3x^2-2x^3),\quad x=clip((T+h+1)/2,0,1)")
            st.latex(r"R=B[1-\max(p_{vol},p_{dd})],\quad R\ge0.85B\;\text{仅在符合条件时}")
            st.write("L = log(价格 / SMA200)；M = log(价格 / 126 个交易日前的价格)；S = log(SMA100 / 20 个交易日前的 SMA100)。趋势证据的截断范围为 [-1, 1]。")
    elif page == "Backtest":
        st.plotly_chart(chart_dashboard(result, benchmark), width="stretch")
        table = pd.DataFrame({"Quantum": m, "Buy & Hold": bm}).T
        st.dataframe(formatted_metrics(table), width="stretch", column_config={"TotalReturn": "总收益率", "CAGR": "年化复合增长率", "MaxDrawdown": "最大回撤", "Volatility": "波动率", "Sharpe": "夏普比率", "Sortino": "索提诺比率", "Calmar": "卡玛比率", "AverageExposure": "平均仓位", "TimeInMarket": "持仓时间占比", "Turnover": "换手率", "TransactionCosts": "交易成本", "Fills": "成交笔数", "ClosedCycles": "已结束周期数", "OpenCycles": "未结束周期数", "WinRate": "胜率", "ProfitFactor": "盈利因子", "AverageHoldingDays": "平均持仓天数", "UpsideCapture": "上涨捕获率", "DownsideCapture": "下跌捕获率", "UpMonths": "上涨月份数", "DownMonths": "下跌月份数", "DrawdownReduction": "回撤削减幅度", "ComparedWith": "对照模型", "Interval": "区间", "Start": "开始日期", "End": "结束日期"})
        c = st.columns(3)
        c[0].metric("策略毛收益率", f"{metrics(cached['gross'])['TotalReturn']:.1%}")
        c[1].metric("交易成本", f"{h.Cost.sum():,.2f}")
        c[2].metric("策略净收益率", f"{m['TotalReturn']:.1%}")
        st.caption("毛收益来自单独的零成本模拟；复利与账户反馈可能不同。未平仓持仓继续按市价计值。捕获率使用完整月份收益的算术平均值，剔除首尾月份，上涨和下跌月份各需至少三个观测值。换手率为年化双边名义交易额 / 净值，不除以二。")
        st.subheader("风险与市场参与的权衡")
        c = st.columns(3)
        c[0].metric("牺牲的年化复合增长率", f"{bm['CAGR']-m['CAGR']:+.1%}")
        c[1].metric("回撤改善", f"{abs(bm['MaxDrawdown'])-abs(m['MaxDrawdown']):+.1%}")
        c[2].metric("上涨捕获率", f"{m['UpsideCapture']:.1%}" if np.isfinite(m['UpsideCapture']) else "不适用")
        st.subheader("连续市场状态区间")
        reg = regime_diagnostics(result, benchmark)
        if len(reg): st.dataframe(reg, hide_index=True, width="stretch", column_config={"Year": "年份", "Start": "开始日期", "End": "结束日期", "Regime": "市场状态", "Days": "交易日数", "QuantumReturn": "Quantum 收益率", "BenchmarkReturn": "基准收益率", "QuantumDD": "Quantum 回撤", "BenchmarkDD": "基准回撤", "AverageExposure": "平均仓位", "Turnover": "换手率", "TransactionCosts": "交易成本"})
        else: st.info("对于投资组合，各资产前一收盘时点的市场状态记录在仓位历史中。组合收益不归属于某个单一资产的市场状态。")
        st.subheader("年度稳定性——策略固定，不重新拟合")
        st.dataframe(period_diagnostics(result, benchmark), hide_index=True, width="stretch", column_config={"Year": "年份", "Start": "开始日期", "End": "结束日期", "Regime": "市场状态", "Days": "交易日数", "QuantumReturn": "Quantum 收益率", "BenchmarkReturn": "基准收益率", "QuantumDD": "Quantum 回撤", "BenchmarkDD": "基准回撤", "AverageExposure": "平均仓位", "Turnover": "换手率", "TransactionCosts": "交易成本"})
        st.subheader("按时间顺序划分的验证区间")
        st.dataframe(formatted_metrics(chronological_diagnostics(result, benchmark)), hide_index=True, width="stretch", column_config={"TotalReturn": "总收益率", "CAGR": "年化复合增长率", "MaxDrawdown": "最大回撤", "Volatility": "波动率", "Sharpe": "夏普比率", "Sortino": "索提诺比率", "Calmar": "卡玛比率", "AverageExposure": "平均仓位", "TimeInMarket": "持仓时间占比", "Turnover": "换手率", "TransactionCosts": "交易成本", "Fills": "成交笔数", "ClosedCycles": "已结束周期数", "OpenCycles": "未结束周期数", "WinRate": "胜率", "ProfitFactor": "盈利因子", "AverageHoldingDays": "平均持仓天数", "UpsideCapture": "上涨捕获率", "DownsideCapture": "下跌捕获率", "UpMonths": "上涨月份数", "DownMonths": "下跌月份数", "DrawdownReduction": "回撤削减幅度", "ComparedWith": "对照模型", "Interval": "区间", "Start": "开始日期", "End": "结束日期"})
        st.caption("按 60/20/20 划分区间，持仓连续且规则固定。只有最后一个区间未用于先前的设计决策时，它才是真正的留出区间。现在查看它将消耗这次留出验证机会；系统不会自动重新拟合。")
    elif page == "Diagnostics":
        tab1, tab2, tab3, tab4 = st.tabs(["消融测试", "参与度与恢复", "事件与记账", "敏感性分析"])
        with tab1:
            st.write("使用相同的数据、日期、预算、执行方式和成本。不会自动选择模型。")
            if st.button("运行 A–F 对照与组件删除测试"):
                with st.spinner("正在运行固定对照组…"):
                    table, delta, _ = run_ablation(data, cfg, meta["start"], meta["end"], meta["initial"])
                    cached["ablation"], cached["delta"] = table, delta
            if "ablation" in cached:
                st.dataframe(formatted_metrics(cached["ablation"]), width="stretch", column_config={"TotalReturn": "总收益率", "CAGR": "年化复合增长率", "MaxDrawdown": "最大回撤", "Volatility": "波动率", "Sharpe": "夏普比率", "Sortino": "索提诺比率", "Calmar": "卡玛比率", "AverageExposure": "平均仓位", "TimeInMarket": "持仓时间占比", "Turnover": "换手率", "TransactionCosts": "交易成本", "Fills": "成交笔数", "ClosedCycles": "已结束周期数", "OpenCycles": "未结束周期数", "WinRate": "胜率", "ProfitFactor": "盈利因子", "AverageHoldingDays": "平均持仓天数", "UpsideCapture": "上涨捕获率", "DownsideCapture": "下跌捕获率", "UpMonths": "上涨月份数", "DownMonths": "下跌月份数", "DrawdownReduction": "回撤削减幅度", "ComparedWith": "对照模型", "Interval": "区间", "Start": "开始日期", "End": "结束日期"})
                st.subheader("增量差异")
                st.dataframe(formatted_metrics(cached["delta"]), width="stretch", column_config={"TotalReturn": "总收益率", "CAGR": "年化复合增长率", "MaxDrawdown": "最大回撤", "Volatility": "波动率", "Sharpe": "夏普比率", "Sortino": "索提诺比率", "Calmar": "卡玛比率", "AverageExposure": "平均仓位", "TimeInMarket": "持仓时间占比", "Turnover": "换手率", "TransactionCosts": "交易成本", "Fills": "成交笔数", "ClosedCycles": "已结束周期数", "OpenCycles": "未结束周期数", "WinRate": "胜率", "ProfitFactor": "盈利因子", "AverageHoldingDays": "平均持仓天数", "UpsideCapture": "上涨捕获率", "DownsideCapture": "下跌捕获率", "UpMonths": "上涨月份数", "DownMonths": "下跌月份数", "DrawdownReduction": "回撤削减幅度", "ComparedWith": "对照模型", "Interval": "区间", "Start": "开始日期", "End": "结束日期"})
                st.caption("删除测试的差异等于删除组件后的结果减去完整模型或参考模型的结果。删除趋势证据组件时，同时移除其评分贡献及资格判定条件。任何测试都不会自动更改已部署的模型。")
        with tab2:
            st.subheader("参与度约束")
            d = cached["participation"]
            st.write(f"{int(d.Warning.sum())} 个资产交易日存在持续的仓位缺口；{int(d.ConstraintViolation.sum())} 次仓位控制约束违规。")
            st.caption("窗口 = ceil(最大仓位 / 加仓速度)，Balanced 为 10 个交易日。要求持续满足健康市场资格条件。容差为 2 个百分点的不交易区间；不设置任意的低仓位阈值。")
            st.dataframe(d[["Date", "Symbol", "Healthy", "Base", "Target", "Exposure", "AttainableFloor", "Shortfall", "Warning", "VolReduction", "DrawdownReduction", "EmergencyReduction"]].tail(250), hide_index=True, width="stretch", column_config={"Date": "日期", "Symbol": "标的", "Healthy": "健康牛市资格", "Base": "基础仓位", "Target": "目标仓位", "Exposure": "实际仓位", "AttainableFloor": "可达到的参与下限", "Shortfall": "仓位缺口", "Warning": "参与度警告", "VolReduction": "波动率减仓", "DrawdownReduction": "回撤削减幅度", "EmergencyReduction": "紧急防守减仓"})
            st.subheader("V 型恢复：加仓速度限制的代价")
            st.caption("仅用于事后诊断：相对前 20 个交易日高点下跌至少 8%，形成局部低点，随后在 20 个交易日内回升至少 8%。事件筛选可能使用未来数据；交易指令绝不使用。反事实模拟仅取消加仓速度限制，原有趋势、风险、参与下限及紧急防守路径均固定。错失收益为正表示较慢入场造成损失，为负表示较慢入场有利。此诊断绝不作为优化目标。")
            if len(cached["recoveries"]): st.dataframe(cached["recoveries"], hide_index=True, width="stretch", column_config={"Trough": "低点日期", "RecoveryEnd": "恢复结束日期", "Days": "交易日数", "PrecedingDecline": "此前跌幅", "BenchmarkRecovery": "基准恢复收益率", "QuantumRecovery": "Quantum 恢复收益率", "UnlimitedOnReplay": "取消加仓限速的重放收益率", "RiskOnMissedReturn": "加仓限速错失收益率"})
            else: st.info("此区间内没有符合条件的 V 型恢复。该诊断为不适用，不代表损失为零。")
            st.subheader("各资产的健康牛市参与度")
            st.dataframe(d.loc[d.Healthy].groupby("Symbol")[["Base", "Target", "Exposure", "Shortfall"]].mean(), width="stretch", column_config={"Symbol": "标的", "Base": "基础仓位", "Target": "目标仓位", "Exposure": "实际仓位", "Shortfall": "仓位缺口"})
        with tab3:
            st.subheader("紧急防守事件日志")
            st.dataframe(result.events, hide_index=True, width="stretch", column_config={"Date": "日期", "SignalDate": "信号日期", "Symbol": "标的", "Event": "事件", "StructureBreak": "结构破坏", "Shock": "波动冲击", "Return1": "单日收益率", "Return5": "五日收益率", "Target": "目标仓位"})
            st.subheader("成本归因")
            st.dataframe(h[["Commission", "SpreadCost", "SlippageCost", "Cost"]].sum().to_frame("金额"), width="stretch", column_config={"Commission": "佣金", "SpreadCost": "价差成本", "SlippageCost": "滑点成本", "Cost": "总成本", "Symbol": "标的"})
            st.subheader("订单与决策归因")
            st.dataframe(result.decisions.tail(250), hide_index=True, width="stretch", column_config={"Date": "日期", "SignalDate": "信号日期", "Symbol": "标的", "Regime": "市场状态", "Base": "基础仓位", "Desired": "期望仓位", "Target": "目标仓位", "Emergency": "紧急防守", "DDMode": "回撤保护状态", "TrendReduction": "趋势减仓", "VolReduction": "波动率减仓", "DrawdownReduction": "回撤削减幅度", "FloorCredit": "参与下限补回仓位", "TransitionEffect": "仓位过渡影响", "EmergencyReduction": "紧急防守减仓", "Healthy": "健康牛市资格", "AttainableFloor": "可达到的参与下限", "DDPenalty": "回撤惩罚", "VolPenalty": "波动率惩罚", "DrawdownStandalone": "独立回撤减仓幅度", "FloorActive": "参与下限已启用", "EmergencyAge": "紧急防守持续天数", "EmergencyCalmDays": "紧急防守平静天数", "Explanation": "决策说明", "Trend": "趋势分数", "Sigma": "年化波动率", "Days": "交易日数", "QuantumReturn": "Quantum 收益率", "BenchmarkReturn": "基准收益率", "QuantumDD": "Quantum 回撤", "BenchmarkDD": "基准回撤", "Year": "年份", "Exposure": "实际仓位", "Shortfall": "仓位缺口", "Warning": "参与度警告", "Trough": "低点日期", "RecoveryEnd": "恢复结束日期", "PrecedingDecline": "此前跌幅", "BenchmarkRecovery": "基准恢复收益率", "QuantumRecovery": "Quantum 恢复收益率", "UnlimitedOnReplay": "取消加仓限速的重放收益率", "RiskOnMissedReturn": "加仓限速错失收益率", "Event": "事件", "StructureBreak": "结构破坏", "Shock": "波动冲击", "Return1": "单日收益率", "Return5": "五日收益率", "Commission": "佣金", "SpreadCost": "价差成本", "SlippageCost": "滑点成本", "Cost": "总成本", "Structure": "结构证据", "Momentum": "动量证据", "Slope": "斜率证据", "VolRatio": "波动率比值", "Trigger": "紧急防守触发", "PriorExposure": "前一收盘仓位", "OrderUnits": "订单单位数", "ClosePrice": "收盘价", "Budget": "资金预算占比", "ConstraintViolation": "参与约束违规", "Side": "交易方向", "Units": "单位数", "ReferencePrice": "参考价格", "FillPrice": "成交价格", "CashAfter": "成交后现金", "CashScale": "现金缩放系数", "Reason": "成交原因", "EntryDate": "入场日期", "ExitDate": "退出日期", "PnL": "盈亏", "HoldingDays": "持仓天数", "Experiment": "实验", "EmergencyTriggers": "紧急防守触发次数", "EmergencyDays": "紧急防守天数", "VolatilityProfile": "波动率分组", "AverageTarget": "平均目标仓位"})
            st.subheader("成交记录")
            st.dataframe(result.fills.tail(250), hide_index=True, width="stretch", column_config={"Date": "日期", "SignalDate": "信号日期", "Symbol": "标的", "Side": "交易方向", "Units": "单位数", "ReferencePrice": "参考价格", "FillPrice": "成交价格", "Commission": "佣金", "SpreadCost": "价差成本", "SlippageCost": "滑点成本", "CashAfter": "成交后现金", "CashScale": "现金缩放系数", "Reason": "成交原因"})
            st.subheader("已结束的持仓周期")
            st.dataframe(result.cycles, hide_index=True, width="stretch", column_config={"Symbol": "标的", "EntryDate": "入场日期", "PnL": "盈亏", "ExitDate": "退出日期", "HoldingDays": "持仓天数"})
            st.caption(f"{meta['open_cycles']} 个未结束周期不计入已结束周期的胜率。加仓与部分卖出均归属于同一个从空仓开始到再次空仓结束的持仓周期。")
        with tab4:
            st.write("使用固定的单因素测试。紧急防守阈值测试为 −6%、−8%、−10%（固定值）、−12%、−15%；结果按前一收盘时点的年化波动率分组：低于 20%、20–40% 和高于 40%。")
            st.caption("波动率分组仅为描述性标签。空分组保持为空，不视为测试成功。不假定任何阈值适用于所有资产。")
            if st.button("运行参数与成本敏感性分析"):
                with st.spinner("正在对各资产与波动率分组运行敏感性分析…"):
                    cached["sensitivity"] = sensitivity(data, cfg, meta["start"], meta["end"], meta["initial"])
            if "sensitivity" in cached: st.dataframe(cached["sensitivity"], hide_index=True, width="stretch", column_config={"TotalReturn": "总收益率", "CAGR": "年化复合增长率", "MaxDrawdown": "最大回撤", "Volatility": "波动率", "Sharpe": "夏普比率", "Sortino": "索提诺比率", "Calmar": "卡玛比率", "AverageExposure": "平均仓位", "TimeInMarket": "持仓时间占比", "Turnover": "换手率", "TransactionCosts": "交易成本", "Fills": "成交笔数", "ClosedCycles": "已结束周期数", "OpenCycles": "未结束周期数", "WinRate": "胜率", "ProfitFactor": "盈利因子", "AverageHoldingDays": "平均持仓天数", "UpsideCapture": "上涨捕获率", "DownsideCapture": "下跌捕获率", "UpMonths": "上涨月份数", "DownMonths": "下跌月份数", "DrawdownReduction": "回撤削减幅度", "ComparedWith": "对照模型", "Interval": "区间", "Start": "开始日期", "End": "结束日期", "Symbol": "标的", "Experiment": "实验", "EmergencyTriggers": "紧急防守触发次数", "EmergencyDays": "紧急防守天数", "VolatilityProfile": "波动率分组", "Days": "交易日数", "AverageTarget": "平均目标仓位"})
    else:
        st.subheader("固定配置")
        st.json(meta)
        st.markdown("""**研究约定**

- 以 Balanced 为设计中心。预设表达风险偏好，并非优化后的收益。
- 必须使用完整且一致的交易日历。OHLCV 缺失或预热数据不足时拒绝运行。
- Yahoo 数据不包含纽约当前日期，且数据提供方可能修订数据。请导出输入快照，以便复现。
- 当前标的列表不能证明这些标的在历史各时点均属于当时的投资范围。
- 这是基于日线复权单位的研究模型。不包含券商集成、日内止损成交、损失上限保证或自动选取投资范围。
- 留出表现必须来自未用于选择规则的数据。合成测试和年度汇总不能证明存在可用于实盘投资的优势。
""")
    tables = {"participation": cached["participation"], "v_recovery": cached["recoveries"],
              "chronological_intervals": chronological_diagnostics(result, benchmark),
              "performance": pd.DataFrame({"Quantum": m, "BuyAndHold": bm}).T,
              "benchmark_history": benchmark.history,
              "risk_on_counterfactual_history": cached["recovery_shadow"].history,
              "gross_history": cached["gross"].history}
    tables.update({k: cached[k] for k in ("ablation", "delta", "sensitivity") if k in cached})
    for s, frame in data.items(): tables["input_"+s.replace("/", "_")] = frame
    st.download_button("下载可复现的研究数据包", export_bundle(result, tables),
                       file_name="quantumsignal_v2_research.zip", mime="application/zip")


if __name__ == "__main__":
    main()

