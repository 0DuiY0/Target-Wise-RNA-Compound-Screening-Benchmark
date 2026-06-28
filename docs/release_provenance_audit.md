# Release Provenance Audit

Date: 2026-06-16
Scope: public GitHub and archive preparation for the v10 target-wise
RNA-compound screening benchmark manuscript

## Executive Decision

The development workspace was not mirrored as the public repository. It
contained benchmark/protocol code, manuscript working files, external
repository clones, downloaded model checkpoints, generated caches, local
compatibility notes, and internal planning documents.

The public GitHub repository is instead a clean accompanying-code package. It
includes repository metadata, a synthetic smoke-test fixture, final aggregate
result tables, manuscript figure previews, editable Fig. 1 source assets,
minimal environment files, path-audit scripts, and provenance
metadata. External model repositories are referenced by upstream URL and commit
rather than vendored wholesale.

Machine-readable source metadata is recorded in:

```text
third_party/sources.yml
```

## Why the Development Workspace Cannot Be Mirrored

The root directory contains nested clones of several external projects:

```text
DeepRNA-DTI/
RNAsmol/
SMRTnet/
DeepRSMA/
BEACON_RNABenchmark/
```

These directories are not homogeneous dependencies. They have different
licenses, different publication roles, local modifications, generated caches,
and downloaded model artifacts. Publishing them inside one primary repository
would make the license boundary and reproducibility boundary unclear.

The most important issue is DeepRNA-DTI. The local tree contains substantial
tracked modifications and many untracked generated files. The local status is
not consistent with a simple "changed GPU index" explanation.

## External Source Audit Summary

| Source | Upstream commit | Observed license | Local status | Release decision |
|---|---:|---|---|---|
| DeepRNA-DTI | `8389ba97015da8336d73b6483c3e71ddce4adf9a` | CC-BY-NC-SA-4.0 | 5 tracked modified files; 23086 untracked entries | Exclude full tree; use upstream URL/commit; separate fork/archive only if needed |
| RNAsmol | `0e97fd0fbce71d47212116948a8acbb1a2bbe7ae` | GPL-3.0 | 4 tracked source modifications plus deleted pycache entries; 2 untracked local files | Exclude full tree; GPL-scoped patch/fork only if full reruns are required |
| SMRTnet | `3bb10428207cafcefa860defdd8e72cd5ea47988` | MIT | No tracked modifications; 1 local environment note | Exclude full tree; cite upstream URL/commit |
| DeepRSMA | `3414ede63efb93fff0bd81029261871dec8c7124` | No local license file observed | 8 tracked source modifications plus deleted pycache entries; 2 untracked local files | Exclude; not part of current v10 evidence |
| BEACON RNABenchmark | `da7f9c7ac3f39605af27e1dfcdf879adba963d79` | Apache-2.0 top-level; mixed headers observed | No tracked modifications; untracked checkpoint files | Exclude; not part of current v10 evidence |

## Source-Specific Decisions

### DeepRNA-DTI

Role in paper: partial resource-suitability anchor. It is not the main paired
target-wise benchmark.

Observed local changes:

```text
tracked modified files:
  src/data_utils.py
  src/model.py
  src/utils.py
  test.py
  train.py

local added code-like paths:
  configs/deeprna_dti_v0/
  src/rna_adapters.py
  src/rna_encoders/

generated or downloaded local paths:
  cache/
  Model/trained_weight/
  13321_2025_1132_MOESM1_ESM.docx
```

Decision:

Do not vendor DeepRNA-DTI into the primary public repository. The observed
license is CC-BY-NC-SA-4.0, and the local changes are substantial. If a
DeepRNA-DTI-specific rerun becomes necessary for review, create a separate fork
or archive that clearly states it is modified from the upstream repository under
the observed license. Do not distribute local caches or model weights unless
their upstream redistribution terms are verified.

### RNAsmol

Role in paper: main paired target-wise resource through RNAsmol/ROBIN
perturbation artifacts.

Observed source modifications are compatibility-oriented:

```text
rnasmol/preprocessing.py
rnasmol/test.py
rnasmol/train.py
rnasmol/utils.py
```

These changes add device selection, configurable workers/batch sizes, safer
checkpoint loading through `map_location`, and a flag to avoid rewriting raw
data during preprocessing.

Decision:

Do not vendor the full RNAsmol tree. If full RNAsmol reruns are required, create
a GPL-scoped fork or patch. The main benchmark release should include aggregate
target-wise outputs and regeneration instructions, not upstream model code or
saved models.

### SMRTnet

Role in paper: split-design and resource-suitability stress test.

The local tree has no tracked modifications. The only local addition observed
is an environment note.

Decision:

Cite upstream URL and commit. Do not fork or patch for the current manuscript.
Release only aggregate resource-suitability outputs and regeneration
instructions.

### DeepRSMA

Role in current paper: historical exploratory reproduction, not part of the v10
evidence chain.

No local license file was observed. The local tree has tracked source
modifications, mainly CLI/device compatibility and debug-output formatting changes.

Decision:

Exclude from the v10 release. Do not redistribute local modifications unless the
license status is resolved and the manuscript adds DeepRSMA evidence.

### BEACON RNABenchmark

Role in current paper: historical exploratory dependency, not part of the v10
evidence chain.

The local tree has no tracked modifications, but it contains untracked BEACON-B
checkpoint files. The top-level license is Apache-2.0, while GPL-style headers
were observed in some submodules.

Decision:

Exclude from the v10 release. Do not bundle checkpoint files. Revisit only if a
released script requires BEACON artifacts.

## Public Release Boundary

The public GitHub release is a clean benchmark/protocol package, not a mirror of
the development workspace. It includes:

```text
README.md
LICENSE
CITATION.cff
DATA_PROVENANCE.md
REPRODUCIBILITY.md
environment.yml
requirements.txt
public_export_manifest.json
assets/figures/
examples/smoke_test/
results/tables/
scripts/
third_party/sources.yml
third_party/patches/README.md
```

The release excludes:

```text
DeepRNA-DTI/
RNAsmol/
SMRTnet/
DeepRSMA/
BEACON_RNABenchmark/
.git directories inside external clones
.hf_cache/
.deps/
.idea/
cache/
Model/trained_weight/
saved_model/
checkpoint/
raw upstream datasets unless redistribution is verified
large generated feature caches
internal handoff, roadmap, worklog, and review notes
manuscript development history
```

## Archive Boundary

The tagged GitHub release and corresponding archive contain the immutable public
benchmark package: aggregate CSV result tables, manuscript figure previews,
editable Fig. 1 source assets, a synthetic smoke-test fixture, manifest files,
environment files, and data provenance documentation. Upstream raw datasets,
model checkpoints, generated feature caches, and full third-party source trees
are not bundled unless redistribution rights are verified.


