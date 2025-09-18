import os, sys, json
import pandas as pd
import numpy as np
from pathlib import Path

# Locked config
W_TRAIN=9; MIN_BARS=850
VOL_Q_MIN=0.35; TREND_Q_MR=0.30; TREND_Q_MOM=0.65

DATA_JSON=Path("data/SOLUSDT_15m_all.json")

def load_data():
    raw=json.loads(DATA_JSON.read_text())
    df=pd.DataFrame(raw,columns=["time","open","high","low","close","volume"])
    t=pd.to_numeric(df["time"],errors="coerce")
    df["timestamp"]=pd.to_datetime(t,unit="ms" if t.max()>1e12 else "s")
    for c in ["open","high","low","close","volume"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.dropna(subset=["close"]).sort_values("timestamp").reset_index(drop=True)
    df["ym"]=df["timestamp"].dt.strftime("%Y-%m")
    df["ret"]=df["close"].pct_change()
    return df

def month_stats(df):
    def _stats(g):
        g=g.sort_values("timestamp"); bars=len(g)
        vol=g["ret"].dropna().std(ddof=0) if bars>1 else 0
        trend=g["close"].iat[-1]/g["close"].iat[0]-1 if bars>0 else 0
        return pd.Series({"vol":vol,"trend":trend,"bars":bars})
    return df.groupby("ym",sort=True).apply(_stats).reset_index().sort_values("ym").reset_index(drop=True)

def pick_regime(df, mstats, ym):
    # need prev month stats + W_TRAIN
    months=mstats["ym"].tolist()
    if ym not in months: return None
    idx=months.index(ym)
    if idx==0: return None
    prev=months[idx-1]
    train=mstats.iloc[max(0,idx-1-W_TRAIN):idx-1]
    if len(train)<W_TRAIN: return None
    prev_row=mstats[mstats["ym"]==prev]
    if prev_row.empty or int(prev_row["bars"].iat[0])<MIN_BARS: return None

    vol_q=float(train["vol"].quantile(VOL_Q_MIN))
    q_mr=float(train["trend"].abs().quantile(TREND_Q_MR))
    q_mom=float(train["trend"].abs().quantile(TREND_Q_MOM))
    vprev=float(prev_row["vol"].iat[0])
    aprev=abs(float(prev_row["trend"].iat[0]))

    if vprev>=vol_q:
        if aprev<=q_mr: return "BB"
        elif aprev>=q_mom: return "EMA"
    return "BH"

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: python regime_pick.py YYYY-MM")
        sys.exit(1)
    ym=sys.argv[1]
    df=load_data()
    mstats=month_stats(df)
    pick=pick_regime(df,mstats,ym)
    if pick is None:
        print(f"No pick available for {ym} (insufficient history).")
    else:
        print(f"Regime pick for {ym}: {pick}")
