import os, json
import numpy as np, pandas as pd
from pathlib import Path
import importlib

# ==== LOCKED CONFIG (from best sweep) ====
FEE_BPS=5; SLIP_BPS=5
BB_PERIOD=16; BB_K=2.4
EMA_FAST_N=10; EMA_SLOW_N=40
W_TRAIN=9; MIN_BARS=850
VOL_Q_MIN=0.35; TREND_Q_MR=0.30; TREND_Q_MOM=0.65

DATA_JSON=Path("data/SOLUSDT_15m_all.json")
OUT_DIR=Path("data/backtests"); OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_CSV = OUT_DIR/"walk_bb_ema_regime_v5.csv"
OUT_EQU = OUT_DIR/"walk_bb_ema_regime_v5_equity.csv"
OUT_L12 = OUT_DIR/"walk_bb_ema_regime_v5_last12.csv"

# ==== Load (offline) ====
raw=json.loads(DATA_JSON.read_text())
df=pd.DataFrame(raw,columns=["time","open","high","low","close","volume"])
t=pd.to_numeric(df["time"],errors="coerce")
df["timestamp"]=pd.to_datetime(t,unit="ms" if t.max()>1_000_000_000_000 else "s")
for c in ["open","high","low","close","volume"]:
    df[c]=pd.to_numeric(df[c],errors="coerce")
df=df.dropna(subset=["close"]).sort_values("timestamp").reset_index(drop=True)
df["ym"]=df["timestamp"].dt.strftime("%Y-%m")
df["ret"]=df["close"].pct_change()

# ==== Per-month stats (no deprecated warnings) ====
# Only keep needed cols before groupby
gdf = df[["ym","timestamp","close","ret"]].copy()
def _mstat(g):
    g=g.sort_values("timestamp")
    bars=len(g)
    vol = g["ret"].dropna().std(ddof=0) if bars>1 else 0.0
    trend = (g["close"].iat[-1]/g["close"].iat[0]-1.0) if bars>0 else 0.0
    return pd.Series({"vol":vol,"trend":trend,"bars":bars})
mstats = gdf.groupby("ym", sort=True, group_keys=False).apply(_mstat).reset_index()

# ==== Module + runners ====
bh=importlib.import_module("src.backtest_hybrid")
RUN_EMA_FN=next((n for n in ("run_backtest_ema","run_backtest") if hasattr(bh,n)),None)

SAFE = {"equity_multiple":1.0,"win_rate_pct":0.0,"trades":0,"max_drawdown_pct":0.0,"avg_trade_ret_pct":0.0}
def _extract(d):
    out=SAFE.copy()
    if isinstance(d,dict):
        for k in out:
            if k in d:
                try: out[k]=float(d[k])
                except: pass
        for alt in ("equity_mult","equity"):
            if alt in d:
                try: out["equity_multiple"]=float(d[alt])
                except: pass
        if out["win_rate_pct"]<=1.0: out["win_rate_pct"]*=100.0
    return out

def month_slice(ym):
    return df.loc[df["ym"]==ym].copy().reset_index(drop=True)

def bh_mult(d):
    return float(d["close"].iat[-1]/d["close"].iat[0]) if len(d)>1 else 1.0

def run_bb(dfm):
    os.environ.update({"FEE_BPS":str(FEE_BPS),"SLP_BPS":str(SLIP_BPS),"SLIP_BPS":str(SLIP_BPS),
                       "BB_PERIOD":str(BB_PERIOD),"BB_K":str(BB_K)})
    try:
        out=bh.run_bb_tv(dfm)
        return out if isinstance(out,dict) else {}
    except: return {}

def run_ema(dfm):
    k=[]; ts=(dfm["timestamp"].astype("int64")//1_000_000).tolist()
    for i,row in dfm.iterrows():
        k.append([int(ts[i]),float(row["open"]),float(row["high"]),
                  float(row["low"]),float(row["close"]),float(row["volume"])])
    def _fetch(*a,**kw): return k
    os.environ.update({"FEE_BPS":str(FEE_BPS),"SLP_BPS":str(SLIP_BPS),"SLIP_BPS":str(SLIP_BPS),
                       "EMA_FAST_N":str(EMA_FAST_N),"EMA_SLOW_N":str(EMA_SLOW_N)})
    backup=getattr(bh,"fetch_klines",None)
    try:
        if RUN_EMA_FN is None: return {}
        bh.fetch_klines=_fetch
        out=getattr(bh,RUN_EMA_FN)()
        return out if isinstance(out,dict) else {}
    except: return {}
    finally:
        if backup is not None:
            try: bh.fetch_klines=backup
            except: pass

# ==== Walk-forward (no look-ahead) ====
rows=[]; months=mstats["ym"].tolist()
for i in range(1,len(months)):
    cur, prev = months[i], months[i-1]
    train=mstats.iloc[max(0,i-1-W_TRAIN):i-1]
    if len(train)<W_TRAIN: continue
    prev_row=mstats.loc[mstats["ym"]==prev]
    if prev_row.empty or int(prev_row["bars"].iat[0])<MIN_BARS: continue

    vol_q = float(train["vol"].quantile(VOL_Q_MIN))
    tr_abs = train["trend"].abs()
    q_mr  = float(tr_abs.quantile(TREND_Q_MR))
    q_mom = float(tr_abs.quantile(TREND_Q_MOM))
    vprev = float(prev_row["vol"].iat[0])
    aprev = abs(float(prev_row["trend"].iat[0]))

    pick="BH"
    if vprev>=vol_q:
        if aprev<=q_mr: pick="BB"
        elif aprev>=q_mom: pick="EMA"

    cur_df=month_slice(cur); bhm=bh_mult(cur_df)
    if cur_df.empty: continue

    if pick=="BB": r=_extract(run_bb(cur_df))
    elif pick=="EMA": r=_extract(run_ema(cur_df))
    else: r=SAFE.copy(); r["equity_multiple"]=bhm

    rows.append({"ym":cur,"pick":pick, **r, "bh_month_mult":bhm})

res=pd.DataFrame(rows).sort_values("ym").reset_index(drop=True)
res.to_csv(OUT_CSV,index=False)

# Equity curve + last-12
res["strat_cum"]=res["equity_multiple"].replace([np.nan,None],1.0).cumprod()
res["bh_cum"]=res["bh_month_mult"].replace([np.nan,None],1.0).cumprod()
res[["ym","pick","equity_multiple","bh_month_mult","strat_cum","bh_cum"]].to_csv(OUT_EQU,index=False)
res.tail(12).to_csv(OUT_L12,index=False)

print(f"[OK] Saved {OUT_CSV}")
print(f"[OK] Saved {OUT_EQU}")
print(f"[OK] Saved {OUT_L12}")
print("\n=== SUMMARY ===")
sm=float(res["strat_cum"].iat[-1]); bm=float(res["bh_cum"].iat[-1])
print(f"Months={len(res)}  Strategy={sm:.4f}  Buy&Hold={bm:.4f}  Ratio={sm/bm:.3f}")
print("Pick counts:", res["pick"].value_counts().to_dict())
