import itertools, pandas as pd, numpy as np, time, glob
from pathlib import Path
from src.price_sources import fetch_klines

# ---------- helpers ----------
def ema(s, n): return s.ewm(span=int(n), adjust=False).mean()
def atr(h,l,c,n=14):
    n=int(n)
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def dyn_bb(c, p, base_k, ratio_min, ratio_max):
    p=int(p)
    ma=c.rolling(p).mean(); sd=c.rolling(p).std(ddof=0)
    rv=c.pct_change().rolling(p).std(ddof=0); rvb=rv.ewm(span=max(3*p//2,1), adjust=False).mean()
    ratio=(rv/rvb).clip(lower=ratio_min, upper=ratio_max).fillna(1.0)
    k=base_k*ratio
    return ma, ma+k*sd, ma-k*sd, k

def fetch_df(symbol, interval, limit):
    df=pd.DataFrame(fetch_klines(symbol, interval, limit))
    df["time"]=pd.to_datetime(df["close_time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    for col in ("open","high","low","close","volume"): df[col]=df[col].astype(float)
    return df

# ---------- load last sweep winner ----------
paths=sorted(glob.glob("data/backtests/regime_switch_v2_sweep_*.csv"))
assert paths, "No regime_switch_v2_sweep CSVs found."
best=(pd.read_csv(paths[-1])
        .sort_values(["equity_multiple","win_rate_pct","trades"], ascending=[False,False,False])
        .iloc[0].to_dict())

SYM="SOLUSDT"
d15=fetch_df(SYM,"15m",5000)
d1h=fetch_df(SYM,"1h",2000)

def run_once(tp_TR, tp_RG, profit_lock_mult, fee_bps=5, slp_bps=5):
    ema_fast=float(best["ema_fast"]); ema_slow=float(best["ema_slow"])
    bb_p=20; base_k=float(best["base_k"]); ratio_min=0.80; ratio_max=float(best["ratio_max"])
    vol_x=float(best["vol_x"]); atr_n=14; adx_thr=float(best["adx_thr"])
    stop_mult=float(best["stop_mult"]); trail_TR=float(best["trail_TR"]); trail_RG=1.5; cooldown=1
    cost_side=(fee_bps+slp_bps)/1e4

    df=d15.copy()
    c,h,l,v=df["close"],df["high"],df["low"],df["volume"]
    df["ema_fast"],df["ema_slow"]=ema(c,ema_fast),ema(c,ema_slow)
    df["bb_mid"],df["bb_up"],df["bb_lo"],df["k_dyn"]=dyn_bb(c,bb_p,base_k,ratio_min,ratio_max)
    df["vol_sma20"]=v.rolling(20).mean()
    df["atr"]=atr(h,l,c,atr_n)

    H=d1h.copy()
    H["ema_fast_1h"],H["ema_slow_1h"]=ema(H["close"],ema_fast),ema(H["close"],ema_slow)
    trend_up=(H["ema_fast_1h"]>H["ema_slow_1h"]).astype(int)
    df["trend_up"]=trend_up.reindex(df.index, method="ffill").fillna(0).astype(int)

    start=int(max(ema_slow, bb_p, 20, atr_n)+5)
    equity, pos, cdn = 1.0, None, 0
    trades=[]

    for i in range(start, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        vol_ok = row.volume >= vol_x * row.vol_sma20
        cross_mid_up = (prev.close <= prev.bb_mid) and (row.close > row.bb_mid)
        touch_lo  = row.close <= row.bb_lo
        touch_up  = row.close >= row.bb_up
        in_trend  = (row.trend_up==1)

        if cdn>0: cdn -= 1

        # entries
        if (pos is None) and (cdn==0) and vol_ok:
            if in_trend and cross_mid_up:
                a=float(row.atr); e=float(row.close)
                pos={"side":"long","mode":"TR","entry":e,"peak":e,"stop":e-stop_mult*a,"tp":e+tp_TR*a,"locked":False}
                cdn=cooldown; continue
            if (not in_trend) and touch_lo:
                a=float(row.atr); e=float(row.close)
                pos={"side":"long","mode":"RG","entry":e,"peak":e,"stop":e-stop_mult*a,"tp":e+tp_RG*a}
                cdn=cooldown; continue
            if (not in_trend) and touch_up:
                a=float(row.atr); e=float(row.close)
                pos={"side":"short","mode":"RG","entry":e,"trough":e,"stop":e+stop_mult*a,"tp":e-tp_RG*a}
                cdn=cooldown; continue

        if pos is None:
            continue

        px=float(row.close); a=float(row.atr)

        # exits + profit lock
        if pos["side"]=="long":
            if px > pos["peak"]: pos["peak"]=px
            if (pos.get("mode")=="TR") and (px>=float(row.bb_up)) and (not pos.get("locked",False)):
                pos["stop"] = max(pos["stop"], pos["entry"] + profit_lock_mult * a)  # lock some gains
                pos["locked"] = True
            trail = pos["peak"] - (trail_TR if pos.get("mode")=="TR" else trail_RG)*a
            exit_now = (px<=pos["stop"]) or (px>=pos["tp"]) or (px<=trail)
            if exit_now:
                gross=(px/pos["entry"])-1.0
                net=gross - 2*cost_side
                equity *= (1.0 + net)
                trades.append(net)
                pos=None; cdn=cooldown
        else:
            if px < pos.get("trough", px): pos["trough"]=px
            trail = pos["trough"] + trail_RG*a
            exit_now = (px>=pos["stop"]) or (px<=pos["tp"]) or (px>=trail)
            if exit_now:
                gross=(pos["entry"]/px)-1.0
                net=gross - 2*cost_side
                equity *= (1.0 + net)
                trades.append(net)
                pos=None; cdn=cooldown

    return equity, len(trades)

# grid: widen trend TP, test lock levels
grid_tp_TR=[3.0, 3.5]
grid_tp_RG=[1.2, 1.5]
grid_lock=[0.3, 0.5, 0.7]

rows=[]
for tpTR in grid_tp_TR:
    for tpRG in grid_tp_RG:
        for lk in grid_lock:
            eq, n = run_once(tpTR, tpRG, lk)
            rows.append({"tp_TR":tpTR, "tp_RG":tpRG, "lock_mult":lk, "trades":n, "equity_multiple":round(eq,6)})

df=pd.DataFrame(rows).sort_values(["equity_multiple","trades"], ascending=[False,False])
print(df.head(15).to_string(index=False))

out=Path("data/backtests")/("regime_v2_profitlock_"+time.strftime("%Y%m%d_%H%M%S")+".csv")
df.to_csv(out, index=False)
print("WROTE:", str(out))
