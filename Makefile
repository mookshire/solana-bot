PY := python3
PP := PYTHONPATH=.

# Run the locked walk-forward (saves v5 CSVs and prints summary)
wf:
	$(PP) $(PY) src/walkforward_offline.py

# Get regime pick for a given month: make pick MONTH=YYYY-MM
pick:
	@(([ -n "$$MONTH" ])) || (echo "Usage: make pick MONTH=YYYY-MM" && exit 1)
	$(PP) $(PY) src/regime_pick.py $$MONTH

# Quick: show last-12 months table
last12:
	@tail -n +1 data/backtests/walk_bb_ema_regime_v5_last12.csv | column -s, -t

# Silence warnings for a clean run
wf_quiet:
	PYTHONWARNINGS=ignore $(PP) $(PY) src/walkforward_offline.py
