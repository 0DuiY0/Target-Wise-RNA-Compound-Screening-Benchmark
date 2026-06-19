# v9 Smoke-Test Fixture

This synthetic fixture exercises the public target-wise screening utilities
without redistributing upstream RNA-compound data.

The fixture contains three candidate pools:

```text
smoke_target_alpha: eligible, 6 candidates, 2 positives
smoke_target_beta: eligible, 6 candidates, 2 positives, top-score tie
smoke_target_gamma: below the default 5-candidate threshold
```

Run:

```bash
python scripts/run_smoke_test.py --input examples/smoke_test --output reports/smoke_test
```

Expected outputs:

```text
target_level_metrics.csv
model_summary_metrics.csv
pairwise_delta_summary.csv
smoke_figure.pdf
smoke_test_manifest.json
```

