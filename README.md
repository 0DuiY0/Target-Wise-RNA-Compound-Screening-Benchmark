# Target-Wise RNA-Compound Screening Benchmark

Official code and result summaries for a low-cost, target-wise
RNA-compound screening evaluation protocol.

Public repository: https://github.com/0DuiY0/Target-Wise-RNA-Compound-Screening-Benchmark

This repository is an accompanying-code repository in the style of common
Bioinformatics releases: it provides lightweight reproduction checks, final
summary tables, figure previews, editable Fig. 1 source, environment files, and provenance notes. It is
not a full research workbench and does not vendor upstream model repositories,
raw datasets, checkpoints, or generated feature caches.

## Scope

The study treats RNA-compound scoring as a first-pass screening problem: for a
given RNA target and candidate compound pool, are active compounds ranked early?
The protocol fixes candidate-pool reconstruction, information boundaries,
ligand-only controls, tie-aware target-wise metrics, paired target-level
uncertainty, and diagnostic checks.

This release is a benchmark/protocol package, not a new RNA-compound model
architecture. The main evaluation does not require RNA-ligand tertiary
structures, docking poses, or RNA-ligand complex features.

## Repository Layout

```text
assets/figures/        manuscript figure previews and editable Fig. 1 SVG source
examples/smoke_test/   synthetic fixture for clean-clone checks
results/tables/        final aggregate CSV summary tables
scripts/               smoke test, checksum verification, and path audit
third_party/           upstream source provenance and patch policy
```

## Installation

Create the minimal conda environment:

```bash
conda env create -f environment.yml
conda activate targetwise-rna-screening
```

or install the minimal Python requirements:

```bash
python -m pip install -r requirements.txt
```

## Quick Start

Run the self-contained synthetic smoke test:

```bash
python scripts/run_smoke_test.py --input examples/smoke_test --output reports/smoke_test
```

Verify public checksums after release packaging:

```bash
python scripts/verify_checksums.py --root . --checksums checksums_sha256.csv
```

Audit the public tree for local machine paths:

```bash
python scripts/audit_public_paths.py --root . --fail-on-local-paths
```

## Data And Artifacts

This GitHub repository includes only lightweight public artifacts:

```text
examples/smoke_test/
results/tables/
assets/figures/
```

Full reruns from upstream resources require obtaining the original resources
from their upstream projects. Source provenance and redistribution boundaries
are documented in:

```text
third_party/sources.yml
DATA_PROVENANCE.md
```

The GitHub release is the primary public package for code, smoke tests,
aggregate tables, figure previews, editable Fig. 1 source, environment files, checksums, and
provenance metadata. Separate archival bundles, if deposited, should be cited
from the corresponding GitHub release notes.

## Citation

Please cite the associated manuscript and repository release. Machine-readable
citation metadata are provided in `CITATION.cff`.



