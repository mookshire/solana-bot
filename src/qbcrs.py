# QBCRS.py — Quantum‑Bio Cycle Resonance System (compact, runnable)
# Includes graceful fallbacks so it runs even if some heavy deps are missing.

import math, os
import numpy as np
import pandas as pd
from scipy.fft import fft, fftfreq

# ---- Optional deps (fallbacks if missing) -----------------------------------
try:
    import qutip as qt
except Exception:
    class _DummyState:
        def __init__(self, theta): self.a0, self.a1 = math.cos(theta/2), math.sin(theta/2)
        def __getitem__(self, i): return complex(self.a0 if i==0 else self.a1, 0)
    class qt:
        @staticmethod
        def basis_rotate(theta): return _DummyState(theta)

try:
    from dendropy import Tree, TaxonNamespace
except Exception:
    Tree = TaxonNamespace = None

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except Exception:
    class SentimentIntensityAnalyzer:
        def polarity_scores(self, t): return {"compound": 0.0}

try:
    import ccxt
except Exception:
    ccxt = None
# -----------------------------------------------------------------------------

class QBCRS:
    def __init__(self, historical_data: pd.DataFrame | None = None):
        """
        historical_data: DataFrame with ['date','close'].
        If None and ccxt available, fetches SOL/USDT (1d) from Binance.
        """
        if historical_data is not None:
            self.df = historical_data.copy()
        elif ccxt is not None:
            self.df = self.fetch_solana_data()
        else:
            # minimal dummy series so module still runs
            dates = pd.date_range(end=pd.Timestamp.utcnow(), periods=300, freq='D')
            prices = pd.Series(np.linspace(20, 200, len(dates)))
            self.df = pd.DataFrame({'date':dates, 'close':prices})
        self.df['log_price'] = np.log(self.df['close'].astype(float))
        self.analyzer = SentimentIntensityAnalyzer()

    def fetch_solana_data(self, timeframe='1d', limit=1000) -> pd.DataFrame:
        if ccxt is None:
            raise RuntimeError("ccxt not installed; pass historical_data instead.")
        ex = ccxt.binance()
        ohlcv = ex.fetch_ohlcv('SOL/USDT', timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df[['date','close']]

    def cycle_resonance(self):
        """Fourier-based cycle reconstruction; label last point."""
        prices = self.df['log_price'].to_numpy()
        N = len(prices)
        if N < 64:
            return prices, 'neutral'
        yf = fft(prices)
        xf = fftfreq(N, 1)[:N//2]
        dom = np.argsort(np.abs(yf[:N//2]))[-3:]
        recon = np.zeros(N)
        for f in dom:
            recon += np.real(yf[f] * np.exp(2j*np.pi*xf[f]*np.arange(N)/N) / N)
        window = recon[-50:] if N >= 50 else recon
        if recon[-1] <= window.min() * 1.05:
            flag = 'trough'
        elif recon[-1] >= window.max() * 0.95:
            flag = 'peak'
        else:
            flag = 'neutral'
        return recon, flag

    def quantum_state_probability(self, rsi=50):
        """Map RSI to qubit rotation; return (buy_prob, sell_prob)."""
        theta = math.pi * (rsi / 100.0)
        try:
            st = qt.basis_rotate(theta)  # real qutip or fallback
            p0 = (st[0].real**2 + st[0].imag**2)
            p1 = (st[1].real**2 + st[1].imag**2)
        except Exception:
            p0 = math.cos(theta/2)**2
            p1 = math.sin(theta/2)**2
        return p0, p1

    def biological_adaptation(self):
        """If dendropy present use toy tree; else slope heuristic."""
        if Tree is None:
            tail = self.df['close'].astype(float).tail(100)
            return 'upward' if tail.iloc[-1] >= tail.iloc[0] else 'downward'
        taxa = TaxonNamespace(['2020_low','2021_high','2022_low','2023_recover','2024_bull','2025_peak','2025_current'])
        tree_str = "((2020_low:1,(2021_high:260,(2022_low:9,(2023_recover:100,(2024_bull:200,(2025_peak:293,2025_current:188):1):1):1):1):1));"
        tree = Tree.from_string(tree_str, taxon_namespace=taxa)
        node = tree.find_node_with_taxon_label('2025_current')
        return 'upward' if node.distance_from_root() > 150 else 'downward'

    def get_sentiment_score(self, tweets):
        scores = [self.analyzer.polarity_scores(t)['compound'] for t in (tweets or [])]
        return float(np.mean(scores)) if scores else 0.0

    def generate_signal(self, rsi=58, tweets=None):
        _, cycle_flag = self.cycle_resonance()
        p_buy, p_sell = self.quantum_state_probability(rsi)
        bio = self.biological_adaptation()
        sent = self.get_sentiment_score(tweets)

        # nudge probabilities with sentiment
        if sent > 0.5:  p_buy = min(1.0, p_buy + 0.2)
        if sent < -0.5: p_sell = min(1.0, p_sell + 0.2)

        buy_score  = (1 if cycle_flag=='trough' else 0) + p_buy  + (1 if bio=='upward' else 0) + sent
        sell_score = (1 if cycle_flag=='peak'   else 0) + p_sell + (1 if bio=='downward' else 0) - sent

        if buy_score > 2.5:  return 'BUY'
        if sell_score > 2.5: return 'SELL'
        return 'HOLD'

# ---------------------------- CLI test ---------------------------------------
def main():
    qb = QBCRS()
    tweets = ["Solana is mooning!", "Bearish on SOL"]  # placeholder
    signal = qb.generate_signal(rsi=58, tweets=tweets)
    print(f"Trading Signal: {signal}")

if __name__ == "__main__":
    main()
