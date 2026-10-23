# Kaggle job template

Kaggle kernels give 4 CPU / 30 GB RAM (or free GPU) for up to 12 h, but this account has
**no internet inside kernels** (needs phone verification), so jobs must be self-contained:
inputs go in as a private Kaggle Dataset or inline in the script, outputs come back via
`kaggle kernels output`. Use for offline compute only (batch text processing, scoring, model runs).

`fleet add kaggle <dir>` pushes `<dir>` (must contain `kernel-metadata.json` + script) and
`fleet collect` pulls the output into `/workspace/ai-jobs/fleet-<id>/`.
