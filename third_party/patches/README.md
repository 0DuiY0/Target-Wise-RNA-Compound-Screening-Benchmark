# Third-party Patch Policy

This directory is reserved for small, license-scoped compatibility patches
against upstream repositories.

No raw external-code patch is included in this release. The release policy is:

1. Keep the primary public repository focused on benchmark protocol code,
   aggregate outputs, paper figures, and smoke-test fixtures.
2. Record upstream source URLs, commits, observed licenses, and local
   modification status in `../sources.yml`.
3. Generate compatibility patches only for documented upstream rerun workflows
   that are needed to reproduce a specific manuscript claim.
4. Store each patch under a license-aware name and header, for example
   `rnasmol/gpl3_compatibility.patch`, instead of mixing external-code diffs
   into the main project license.

Recommended patch-generation command, from a local clone of the upstream
repository:

```bash
git diff -- rnasmol/preprocessing.py rnasmol/test.py \
  rnasmol/train.py rnasmol/utils.py
```

For DeepRNA-DTI, compatibility changes are kept outside the primary repository
because the local adaptation is broad and the observed upstream license is
CC-BY-NC-SA-4.0.
