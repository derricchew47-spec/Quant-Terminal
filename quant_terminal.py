"""QuantumSignal V2 — frozen-rule, long-only daily research terminal.

Deploy this file and requirements.txt. Importing it never starts the UI.
Adjusted OHLC represents synthetic investment units, not broker share records.
All orders are fixed from the previous close; no history-dependent optimization.
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
            raise ValueError("Unknown preset")
        if not 0 < self.max_exposure <= 1:
            raise ValueError("Maximum exposure must be in (0, 1]")
        if not 0 <= self.dd_start < self.dd_full < 1:
            raise ValueError("Invalid drawdown thresholds")
        for value in (self.vol_discount, self.dd_discount, self.bull_retention,
                      self.emergency_cap, self.no_trade):
            if not 0 <= value <= 1:
                raise ValueError("Invalid risk parameter")
        if min(self.risk_on, self.risk_off, self.dd_recovery) <= 0:
            raise ValueError("Transition speeds must be positive")
        if min(self.structure_scale, self.momentum_scale, self.slope_scale) <= 0:
            raise ValueError("Feature scales must be positive")
        if min(self.long_window, self.momentum_window) < 2:
            raise ValueError("Feature windows must be at least two")
        if min(self.regime_confirm, self.healthy_confirm) < 1:
            raise ValueError("Confirmations must be positive")
        if not (-1 < self.shock_day < 0 and -1 < self.shock_five < 0):
            raise ValueError("Shock thresholds must be negative returns")
        if self.shock_ratio <= 0 or self.shock_absolute <= 0:
            raise ValueError("Shock scales must be positive")
        if min(self.commission_bps, self.spread_bps, self.slippage_bps) < 0:
            raise ValueError("Costs cannot be negative")
        if max(self.commission_bps, self.spread_bps, self.slippage_bps) >= 1000:
            raise ValueError("Costs outside supported research range")


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
        raise ValueError("Unknown preset")
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
        raise ValueError("OHLCV columns required")
    d = frame[required].copy().astype(float)
    d.index = pd.DatetimeIndex(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
    d.index = d.index.normalize()
    if d.empty or not d.index.is_unique or not d.index.is_monotonic_increasing:
        raise ValueError("Dates must be nonempty, unique and sorted")
    if not np.isfinite(d.to_numpy()).all():
        raise ValueError("Missing or nonfinite OHLCV; no silent price filling")
    valid = ((d.Low > 0) & (d.Volume >= 0)
             & (d.High >= d[["Open", "Close", "Low"]].max(axis=1))
             & (d.Low <= d[["Open", "Close", "High"]].min(axis=1)))
    if not valid.all():
        raise ValueError("Invalid OHLCV relationships")
    return d


def features(frame, cfg=Config(), variant=Variant()):
    """Only trailing operations. Volatility never normalizes trend evidence."""
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
    # Deletion tests remove the component from scores AND its eligibility gates.
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
    """One call per close, including the pre-start close. No fill data enters here."""
    for s, row in rows.items():
        states[s].update_emergency(row, variant.emergency and variant.kind == "continuous")
    recovering = all(r['T'] > 0 and r.Return20 > 0 and r.NoNewLow for r in rows.values())
    any_emergency = any(s.emergency for s in states.values())
    # A conservative shared-account recovery gate: all budgeted assets must recover.
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
                      Explanation=(f"{row.Regime}: trend base {base*a:.1%}; "
                                   f"volatility penalty {pv:.1%}, drawdown penalty {penalty:.1%} "
                                   f"(maximum, not compounded); bull protection {'active' if floor else 'inactive'}; "
                                   f"{'Emergency cap' if state.emergency else 'Risk-On' if desired > old else 'Normal Risk-Off'}; "
                                   f"next target {target*a:.1%}."))
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
    """Strict common calendar, fractional adjusted units, fixed prior-close orders.

    Missing sessions reject the run rather than inventing marks or executions.
    frozen_decisions enables a paired diagnostic with risk-policy feedback frozen.
    """
    cfg.validate()
    if not data or initial <= 0 or not np.isfinite(initial):
        raise ValueError("Data and positive finite capital required")
    data = {s: validate_frame(d) for s, d in sorted(data.items())}
    symbols = list(data)
    calendar = data[symbols[0]].index
    for s in symbols[1:]:
        if not calendar.equals(data[s].index):
            raise ValueError("Asset calendars differ. Supply a complete shared calendar; no silent alignment.")
    budgets = dict(budgets) if budgets is not None else {s: 1/len(symbols) for s in symbols}
    if set(budgets) != set(symbols) or any(not np.isfinite(v) or v <= 0 for v in budgets.values()) or sum(budgets.values()) > 1+1e-12:
        raise ValueError("Positive asset budgets must sum to at most one")
    feats = {s: features(d, cfg, variant) for s, d in data.items()}
    ready = np.logical_and.reduce([f.Ready.to_numpy() for f in feats.values()])
    eligible = np.flatnonzero(np.r_[False, ready[:-1]])
    if not len(eligible):
        raise ValueError("Insufficient warmup; at least 273 daily bars required")
    first = pd.Timestamp(start) if start is not None else calendar[eligible[0]]
    last = pd.Timestamp(end) if end is not None else calendar[-1]
    ids = np.flatnonzero((calendar >= first) & (calendar <= last))
    if not len(ids) or ids[0] == 0 or not ready[ids[0]-1]:
        raise ValueError("Requested start lacks full prior-close warmup")
    if len(ids) < 2:
        raise ValueError("At least two trading days required")
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
                # Estimate purchase costs at the known close, never increase size at open.
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
            raise AssertionError("Cash or quantity conservation failed")
        cash = max(0., cash)
        values = {s: qty[s]*float(data[s].Close.iloc[k]) for s in symbols}
        equity = cash+sum(values.values())
        unrealized = sum(values[s]-cost_basis[s] for s in symbols)
        if not np.isclose(equity, initial+realized+unrealized, atol=1e-6, rtol=1e-10):
            raise AssertionError("Realized + unrealized PnL does not reconcile")
        if equity <= 0:
            raise AssertionError("Nonpositive equity")
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
            raise ValueError("Benchmark dates must match")
        pair = pd.DataFrame({"Q": h.Return.iloc[1:], "B": bh.Return.iloc[1:]})
        monthly = pair.groupby(pair.index.to_period("M")).apply(lambda z: (1+z).prod()-1)
        # Boundary months can be partial. Conservatively omit both from captures.
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
    """Contiguous prior-close regime episodes; never concatenate disjoint drawdowns."""
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
    """Descriptive ex-post V windows; replay changes only the upward speed limit.

    Trend, risk penalties, floor and Emergency paths are frozen to the original.
    This is a paired attribution experiment, not an independently investable policy.
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
    """Fixed one-at-a-time experiments, grouped by lagged volatility profiles."""
    settings = [("Frozen", cfg)]
    for threshold in (-.06, -.08, -.12, -.15):
        settings.append((f"Single-day shock {threshold:.0%}", replace(cfg, shock_day=threshold)))
    for threshold in (-.05, -.12):
        settings.append((f"Five-day shock {threshold:.0%}", replace(cfg, shock_five=threshold)))
    for threshold in (1.5, 2.1):
        settings.append((f"Shock ratio {threshold}", replace(cfg, shock_ratio=threshold)))
    for threshold in (.20, .40):
        settings.append((f"Shock absolute {threshold:.0%}", replace(cfg, shock_absolute=threshold)))
    for window in (150, 250):
        settings.append((f"Long trend {window}", replace(cfg, long_window=window)))
    for window in (84, 168):
        settings.append((f"Momentum {window}", replace(cfg, momentum_window=window)))
    for factor in (.75, 1.25):
        settings.append((f"Feature scales x{factor}", replace(cfg, structure_scale=cfg.structure_scale*factor,
                         momentum_scale=cfg.momentum_scale*factor, slope_scale=cfg.slope_scale*factor)))
    for count in (2, 5):
        settings.append((f"Regime confirmation {count}", replace(cfg, regime_confirm=count)))
    for count in (3, 10):
        settings.append((f"Healthy confirmation {count}", replace(cfg, healthy_confirm=count)))
    for factor in (.75, 1.25):
        settings.append((f"Risk-On speed x{factor}", replace(cfg, risk_on=cfg.risk_on*factor)))
        settings.append((f"Risk-Off speed x{factor}", replace(cfg, risk_off=cfg.risk_off*factor)))
        settings.append((f"Drawdown recovery x{factor}", replace(cfg, dd_recovery=cfg.dd_recovery*factor)))
    for band in (.01, .03):
        settings.append((f"No-trade band {band:.0%}", replace(cfg, no_trade=band)))
    for cost in (2, 3):
        settings.append((f"Costs x{cost}", replace(cfg, commission_bps=cfg.commission_bps*cost,
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
            # Threshold bands are descriptive, not optimized or used by the policy.
            for low, high, label in ((0, .20, "Low <20%"), (.20, .40, "Medium 20–40%"), (.40, np.inf, "High >=40%")):
                g = r.decisions.loc[(r.decisions.Sigma >= low) & (r.decisions.Sigma < high)]
                records.append(dict(Symbol=symbol, Experiment=name, VolatilityProfile=label,
                                    Days=len(g), EmergencyTriggers=int(g.Trigger.sum()),
                                    EmergencyDays=int(g.Emergency.sum()),
                                    AverageTarget=g.Target.mean()))
    return pd.DataFrame(records)


def demo_data(symbols=("DEMO",), periods=1600, seed=17):
    """Deterministic synthetic paths only. Never presented as historical prices."""
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
    """Continuous frozen-policy calendar-year evaluation; no annual parameter refit."""
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
    """60/20/20 reporting boundaries, continuous holdings and no rule fitting.

    These names do not certify that the last interval was actually unseen.
    """
    dates = result.history.index[1:]
    bounds = (0, int(.6*len(dates)), int(.8*len(dates)), len(dates))
    output = []
    for label, begin, finish in zip(("Research 60%", "Validation 20%", "Final interval 20%"), bounds[:-1], bounds[1:]):
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
        # Trade-cycle summaries can span boundaries, so leave them out of this table.
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
            raise ValueError(f"{name}: Date column required")
        rename = {lookup[k.lower()]: k for k in ("Date", "Open", "High", "Low", "Close", "Volume") if k.lower() in lookup}
        if "symbol" in lookup: rename[lookup["symbol"]] = "Symbol"
        raw = raw.rename(columns=rename)
        if "Symbol" not in raw:
            raw["Symbol"] = name.rsplit(".", 1)[0].upper()
        for symbol, group in raw.groupby("Symbol"):
            if symbol in data: raise ValueError(f"Duplicate symbol: {symbol}")
            group = group.copy()
            group["Date"] = pd.to_datetime(group.Date, errors="raise")
            data[str(symbol)] = validate_frame(group.set_index("Date"))
    if not data: raise ValueError("Upload at least one OHLCV CSV")
    return data


def download_history(symbols, start, end):
    import yfinance as yf
    data = {}
    for symbol in symbols:
        d = yf.Ticker(symbol).history(start=str(start), end=str(end), auto_adjust=True,
                                      actions=False, raise_errors=True, timeout=15)
        if d is None or d.empty:
            raise ValueError(f"No data for {symbol}; try an adjusted OHLCV CSV")
        data[symbol] = validate_frame(d)
    return data


def chart_dashboard(result, benchmark):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    h, b = result.history, benchmark.history
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=[.45, .20, .25, .10], vertical_spacing=.04,
                        subplot_titles=("Net equity", "Drawdown", "Market exposure", "Prior-close market state"))
    fig.add_trace(go.Scatter(x=h.index, y=h.Equity, name="Quantum", line=dict(color="#52d6c7", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=b.index, y=b.Equity, name="Buy & Hold", line=dict(color="#a6b3cc", width=1.5)), row=1, col=1)
    for frame, name, color in ((h, "Quantum DD", "#52d6c7"), (b, "Benchmark DD", "#a6b3cc")):
        fig.add_trace(go.Scatter(x=frame.index, y=frame.Drawdown, name=name, line=dict(color=color), showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=h.index, y=h.Exposure, name="Actual exposure", fill="tozeroy", line=dict(color="#52d6c7")), row=3, col=1)
    fig.add_trace(go.Scatter(x=h.index, y=h.Target, name="Execution target", line=dict(color="#e8bf79", dash="dot")), row=3, col=1)
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
    return table.style.format(formats, na_rep="N/A")


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
    st.caption("ADAPTIVE TREND PARTICIPATION · FROZEN RULES · LONG ONLY · NO LEVERAGE")
    with st.sidebar:
        st.header("Research configuration")
        source = st.selectbox("Data source", ["Synthetic demo", "Yahoo adjusted daily data", "Upload adjusted OHLCV CSV"])
        name = st.selectbox("Risk preset", ["Balanced", "Conservative", "Aggressive"])
        cfg = preset_config(name)
        capital = st.number_input("Initial capital", min_value=100., value=10000., step=1000.)
        symbols_text = st.text_input("Symbols / demo profiles", "DEMO" if source == "Synthetic demo" else "SPY")
        if source == "Synthetic demo":
            st.caption("Use DEMO, MEDIUM, HIGH to inspect different synthetic volatility profiles.")
        today = datetime.now(ZoneInfo("America/New_York")).date()
        default_start = pd.Timestamp("2019-03-01").date() if source == "Synthetic demo" else today-timedelta(days=365*5)
        start_date = st.date_input("Backtest start", default_start)
        end_date = st.date_input("Backtest end", pd.Timestamp("2024-02-16").date() if source == "Synthetic demo" else today-timedelta(days=1))
        uploads = st.file_uploader("Adjusted OHLCV files", type="csv", accept_multiple_files=True) if source == "Upload adjusted OHLCV CSV" else []
        with st.expander("Execution assumptions"):
            fee = st.number_input("Commission per side (bps)", 0., 100., cfg.commission_bps)
            spread = st.number_input("Full bid–ask spread (bps)", 0., 100., cfg.spread_bps)
            slip = st.number_input("Additional slippage per side (bps)", 0., 100., cfg.slippage_bps)
            cfg = replace(cfg, commission_bps=fee, spread_bps=spread, slippage_bps=slip)
            st.caption("Fixed prior-close units; next-open execution. Cash shortfalls reduce buys. Fractional adjusted research units. Zero cash yield. No forced endpoint sale.")
        st.caption("Strategy parameters are frozen. Sensitivity experiments do not change the selected strategy.")
        run = st.button("Run research", type="primary", width="stretch")
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols_text.replace(" ", ",").split(",") if s.strip()))
    signature = json.dumps(dict(source=source, cfg=asdict(cfg), capital=capital, symbols=symbols,
                                start=str(start_date), end=str(end_date),
                                uploads=[(f.name, hashlib.sha256(f.getvalue()).hexdigest()) for f in uploads]), sort_keys=True)
    cached = st.session_state.get("research")
    if run or (cached is None and source == "Synthetic demo"):
        try:
            if not symbols and source != "Upload adjusted OHLCV CSV": raise ValueError("Enter at least one symbol")
            if len(symbols) > 12: raise ValueError("Limit each interactive run to 12 assets")
            if end_date <= start_date: raise ValueError("End date must follow start date")
            with st.spinner("Validating data and running the accounting engine…"):
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
            st.error(f"Research run could not complete: {exc}")
            st.info("For CSV input use Date, Open, High, Low, Close, Volume; optional Symbol. Supply at least 280 pre-start sessions and identical complete calendars for a portfolio.")
    if cached is None:
        st.info("Choose a data source and run the research engine.")
        return
    if cached["signature"] != signature:
        st.warning("Settings changed. Results below still belong to the previous run; select Run research to apply changes.")
    result, benchmark, cfg = cached["result"], cached["benchmark"], cached["cfg"]
    data = cached["data"]
    if cached["source"] == "Synthetic demo":
        st.info("SYNTHETIC DEMO — generated paths for testing behavior. These are not historical market returns or evidence of investment performance.")
    meta = result.metadata
    st.caption(f"{meta['config']['preset']} · {meta['start']} → {meta['end']} · {', '.join(data)} · Data fingerprint {meta['data_sha256'][:12]} · {VERSION}")
    page = st.radio("Workspace", ["Overview", "Strategy", "Backtest", "Diagnostics", "Settings"], horizontal=True, label_visibility="collapsed")
    m, bm = metrics(result, benchmark), metrics(benchmark, benchmark)
    h, nxt = result.history, result.next_decision
    if page == "Overview":
        c = st.columns(4)
        regimes = " / ".join(nxt.Regime.unique())
        c[0].metric("Market state", regimes)
        c[1].metric("Next execution target", f"{nxt.Target.astype(float).sum():.1%}")
        c[2].metric("Actual exposure", f"{h.Exposure.iloc[-1]:.1%}")
        c[3].metric("Current drawdown", f"{h.Drawdown.iloc[-1]:.1%}")
        c = st.columns(4)
        c[0].metric("Net equity", f"{h.Equity.iloc[-1]:,.2f}")
        c[1].metric("Return vs Buy & Hold", f"{m['TotalReturn']-bm['TotalReturn']:+.1%}")
        c[2].metric("Cash", f"{h.Cash.iloc[-1]/h.Equity.iloc[-1]:.1%}")
        risk = "EMERGENCY" if nxt.Emergency.any() else "Drawdown protection" if nxt.DDPenalty.astype(float).max() > 0 else "Normal"
        c[3].metric("Risk state", risk)
        st.caption("Targets use the last completed close and are for the next trading session. Actual exposure is the simulated account, not a connected brokerage account.")
        st.plotly_chart(chart_dashboard(result, benchmark), width="stretch")
        last = result.decisions.groupby("Symbol", sort=False).tail(2)
        st.subheader("Recent decisions")
        st.dataframe(last[["SignalDate", "Symbol", "Regime", "Base", "Desired", "Target", "Emergency", "DDMode"]], hide_index=True, width="stretch")
        warnings = cached["participation"]
        if warnings.ConstraintViolation.any(): st.error("Participation constraint violation detected. Inspect Diagnostics before relying on this result.")
        elif warnings.groupby("Symbol").tail(1).Warning.any(): st.warning("PARTICIPATION WARNING — exposure remains below its attainable healthy-bull range.")
    elif page == "Strategy":
        st.subheader("Why this exposure?")
        symbol = st.selectbox("Asset", list(data))
        p = nxt.loc[symbol]
        budget = meta["budgets"][symbol]
        labels = ["Capital ceiling", "Trend deterioration", "Volatility", "Drawdown (incremental)", "Bull protection", "Normal transition", "Emergency", "Final target"]
        vals = [cfg.max_exposure*budget, -float(p.TrendReduction), -float(p.VolReduction),
                -float(p.DrawdownReduction), float(p.FloorCredit), float(p.TransitionEffect),
                -float(p.EmergencyReduction), float(p.Target)]
        fig = go.Figure(go.Waterfall(x=labels, y=vals, measure=["absolute"]+["relative"]*6+["total"],
                                    increasing=dict(marker=dict(color="#52d6c7")), decreasing=dict(marker=dict(color="#e17e87"))))
        fig.update_layout(template="plotly_dark", height=430, yaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption("Exact additive bridge to the target. Volatility is shown first; drawdown contributes only the excess under max(volatility, drawdown). The standalone penalties are shown below, so a binding drawdown overlay is not hidden by ordering.")
        st.dataframe(nxt, width="stretch")
        st.markdown("""**Five questions, five answers**

- **Trend:** structure, six-month momentum and trend slope determine the base allocation.
- **Volatility:** only an unusual increase relative to its own trailing norm reduces exposure, by at most 20% in Balanced.
- **Drawdown:** the shared account protects against loss expansion, with recovery before a new equity high.
- **Participation:** a qualified healthy bull retains at least 85% of base exposure before transition timing.
- **Emergency:** severe structure plus shock/loss evidence overrides the normal speed limit.

Trend components are related price evidence, not independent probabilities. Emergency conditions are different risk dimensions, not statistically independent observations.
""")
        with st.expander("Frozen equations"):
            st.latex(r"T=0.50\,clip(L/0.08)+0.25\,clip(M/0.15)+0.25\,clip(S/0.02)")
            st.latex(r"B=E_{max}(3x^2-2x^3),\quad x=clip((T+h+1)/2,0,1)")
            st.latex(r"R=B[1-\max(p_{vol},p_{dd})],\quad R\ge0.85B\;\text{only when qualified}")
            st.write("L = log(price / SMA200); M = log(price / price126); S = log(SMA100 / SMA100 twenty sessions ago). Evidence clip is [-1, 1].")
    elif page == "Backtest":
        st.plotly_chart(chart_dashboard(result, benchmark), width="stretch")
        table = pd.DataFrame({"Quantum": m, "Buy & Hold": bm}).T
        st.dataframe(formatted_metrics(table), width="stretch")
        c = st.columns(3)
        c[0].metric("Gross strategy return", f"{metrics(cached['gross'])['TotalReturn']:.1%}")
        c[1].metric("Transaction costs", f"{h.Cost.sum():,.2f}")
        c[2].metric("Net strategy return", f"{m['TotalReturn']:.1%}")
        st.caption("Gross is a separate zero-cost simulation; compounding and account feedback can differ. Open positions remain marked to market. Captures use arithmetic complete-month means, omit boundary months and require three observations per sign. Turnover is annualized two-sided notional / equity, not halved.")
        st.subheader("Risk / participation exchange")
        c = st.columns(3)
        c[0].metric("CAGR sacrificed", f"{bm['CAGR']-m['CAGR']:+.1%}")
        c[1].metric("Drawdown improvement", f"{abs(bm['MaxDrawdown'])-abs(m['MaxDrawdown']):+.1%}")
        c[2].metric("Upside capture", f"{m['UpsideCapture']:.1%}" if np.isfinite(m['UpsideCapture']) else "N/A")
        st.subheader("Continuous regime episodes")
        reg = regime_diagnostics(result, benchmark)
        if len(reg): st.dataframe(reg, hide_index=True, width="stretch")
        else: st.info("For portfolios, each asset's prior-close state is in the exposure history. Portfolio return is not assigned to a single asset's regime.")
        st.subheader("Calendar-year stability — frozen policy, no refit")
        st.dataframe(period_diagnostics(result, benchmark), hide_index=True, width="stretch")
        st.subheader("Chronological validation boundaries")
        st.dataframe(formatted_metrics(chronological_diagnostics(result, benchmark)), hide_index=True, width="stretch")
        st.caption("60/20/20 intervals with continuous holdings and frozen rules. The final interval is genuinely held out only if it was not used in prior design decisions. Viewing it now consumes that holdout; no automatic refitting occurs.")
    elif page == "Diagnostics":
        tab1, tab2, tab3, tab4 = st.tabs(["Ablation", "Participation & recovery", "Events & accounting", "Sensitivity"])
        with tab1:
            st.write("Identical data, dates, budgets, execution and costs. No automatic model selection.")
            if st.button("Run A–F and component deletion tests"):
                with st.spinner("Running the frozen comparison set…"):
                    table, delta, _ = run_ablation(data, cfg, meta["start"], meta["end"], meta["initial"])
                    cached["ablation"], cached["delta"] = table, delta
            if "ablation" in cached:
                st.dataframe(formatted_metrics(cached["ablation"]), width="stretch")
                st.subheader("Incremental differences")
                st.dataframe(formatted_metrics(cached["delta"]), width="stretch")
                st.caption("Deletion deltas are deletion minus full/reference. Removing an evidence component removes its score and its eligibility gates. No test automatically changes the deployed model.")
        with tab2:
            st.subheader("Participation contract")
            d = cached["participation"]
            st.write(f"{int(d.Warning.sum())} asset-days with a persistent shortfall; {int(d.ConstraintViolation.sum())} controller violations.")
            st.caption("Window = ceil(max exposure / Risk-On speed), 10 sessions for Balanced. Requires continuous healthy-market eligibility. Tolerance is the 2 percentage-point no-trade band; no arbitrary low-exposure threshold.")
            st.dataframe(d[["Date", "Symbol", "Healthy", "Base", "Target", "Exposure", "AttainableFloor", "Shortfall", "Warning", "VolReduction", "DrawdownReduction", "EmergencyReduction"]].tail(250), hide_index=True, width="stretch")
            st.subheader("V-shaped recovery: cost of the Risk-On speed limit")
            st.caption("Ex-post diagnostic only: at least 8% fall from the prior 20-session high, a local trough, then at least 8% recovery within 20 sessions. Event selection may use future data; orders never do. Counterfactual removes only the upward speed limit, freezing the original trend, risk, floor and Emergency paths. Positive missed return means slower entry hurt; negative means it helped. Never an optimization target.")
            if len(cached["recoveries"]): st.dataframe(cached["recoveries"], hide_index=True, width="stretch")
            else: st.info("No qualifying V-shaped recoveries in this interval. The diagnostic is N/A, not zero loss.")
            st.subheader("Healthy-bull participation by asset")
            st.dataframe(d.loc[d.Healthy].groupby("Symbol")[["Base", "Target", "Exposure", "Shortfall"]].mean(), width="stretch")
        with tab3:
            st.subheader("Emergency event log")
            st.dataframe(result.events, hide_index=True, width="stretch")
            st.subheader("Cost attribution")
            st.dataframe(h[["Commission", "SpreadCost", "SlippageCost", "Cost"]].sum().to_frame("Amount"), width="stretch")
            st.subheader("Orders and decision attribution")
            st.dataframe(result.decisions.tail(250), hide_index=True, width="stretch")
            st.subheader("Fills")
            st.dataframe(result.fills.tail(250), hide_index=True, width="stretch")
            st.subheader("Closed holding cycles")
            st.dataframe(result.cycles, hide_index=True, width="stretch")
            st.caption(f"{meta['open_cycles']} open cycles are excluded from closed-cycle win rate. Additions and partial sales belong to one zero-to-zero holding cycle.")
        with tab4:
            st.write("Fixed one-at-a-time checks. Emergency thresholds are tested at −6%, −8%, −10% (frozen), −12%, −15%, with results broken out by prior-close annualized volatility below 20%, 20–40%, and above 40%.")
            st.caption("Profile bands are descriptive labels. Empty profiles remain empty; they are not treated as successful tests. No threshold is assumed suitable for every asset.")
            if st.button("Run parameter and cost sensitivity"):
                with st.spinner("Running sensitivity across assets and volatility profiles…"):
                    cached["sensitivity"] = sensitivity(data, cfg, meta["start"], meta["end"], meta["initial"])
            if "sensitivity" in cached: st.dataframe(cached["sensitivity"], hide_index=True, width="stretch")
    else:
        st.subheader("Frozen configuration")
        st.json(meta)
        st.markdown("""**Research contract**

- Balanced is the design center. Presets express risk preferences, not optimized returns.
- Identical complete calendars are required. Missing OHLCV or unavailable warmup rejects the run.
- Yahoo data excludes New York's current date and can be revised by the provider. Export the input snapshot for reproducibility.
- Current ticker lists do not establish point-in-time historical universe membership.
- This is a daily adjusted-unit research model. No broker integration, intraday stop fills, guaranteed loss cap, or automatic universe selection.
- Held-out performance must come from data not used to select rules. Synthetic tests and calendar-year summaries are not proof of an investable edge.
""")
    tables = {"participation": cached["participation"], "v_recovery": cached["recoveries"],
              "chronological_intervals": chronological_diagnostics(result, benchmark),
              "performance": pd.DataFrame({"Quantum": m, "BuyAndHold": bm}).T,
              "benchmark_history": benchmark.history,
              "risk_on_counterfactual_history": cached["recovery_shadow"].history,
              "gross_history": cached["gross"].history}
    tables.update({k: cached[k] for k in ("ablation", "delta", "sensitivity") if k in cached})
    for s, frame in data.items(): tables["input_"+s.replace("/", "_")] = frame
    st.download_button("Download reproducible research bundle", export_bundle(result, tables),
                       file_name="quantumsignal_v2_research.zip", mime="application/zip")


if __name__ == "__main__":
    main()

