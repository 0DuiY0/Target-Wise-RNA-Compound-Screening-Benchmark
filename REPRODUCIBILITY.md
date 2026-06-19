# Reproducibility

This document describes checks for the lightweight public GitHub release.

## Environment

Minimal conda environment:

```bash
conda env create -f environment.yml
conda activate targetwise-rna-screening
```

Minimal pip installation:

```bash
python -m pip install -r requirements.txt
```

The minimal environment is sufficient for public-path auditing and the synthetic
smoke test. Full upstream reruns require the original resources and package versions used by the upstream projects.

## Smoke Test

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

## Public Path Audit

Run:

```bash
python scripts/audit_public_paths.py --root . --fail-on-local-paths
```

This checks text-like files for local drive-qualified paths, home-directory
paths, repository-root paths, and conda `prefix:` entries.

## Full Rerun Boundary

The public repository does not vendor third-party model repositories, upstream
raw datasets, checkpoints, generated feature caches, or manuscript
development history. Full reruns from upstream resources require following
`DATA_PROVENANCE.md` and `third_party/sources.yml`.




