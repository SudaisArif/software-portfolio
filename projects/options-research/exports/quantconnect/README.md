# QuantConnect LEAN Export Notes

The local research system writes broker-neutral target weights to:

```text
reports/latest_allocations.csv
reports/latest_weights.csv
```

For live use, do not send these directly to a real account first. Use a paper account and check:

- whether your broker supports fractional shares,
- whether margin is enabled if gross exposure can exceed 100%,
- whether short options or multi-leg options are approved,
- actual spreads, commissions, and rejected orders,
- whether the daily rebalance time matches the data used by the model.

`MLFactorRotationAlgorithm.py` is a LEAN template for replaying target weights. To use it in QuantConnect, upload the latest target-weight CSV as custom data/Object Store data or replace the `target_weights` dictionary with weights generated inside LEAN.

