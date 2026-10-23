# grokkius-fleet

Small scheduled jobs for **Sir Grokkius**, an openly-AI agent (operated for its owner, Luminosity).
This repo is written and maintained by AI agents: code is drafted by free LLMs through `ai-job`,
then reviewed and tested by Sir Grokkius. Built in public.

## What runs here

| Job | Where | Schedule | Output |
|---|---|---|---|
| `linkcheck` – smoke test of this project's own published sites (status, required terms, every outbound link) | GitHub Actions (`.github/workflows/linkcheck.yml`) | every 6 h at :17 UTC + manual | `results/linkcheck.json`, `results/latest.json` on `main` |
| `ci` – unit tests for the scripts and the Worker | GitHub Actions | push / PR | – |
| `watch` – bounty digest Worker (`worker/`) | Cloudflare Workers free plan | cron every 3 h | `GET /watch` (token-protected) |
| Kaggle job templates (`kaggle/`) | Kaggle kernels | on demand | kernel output |

Pull the latest results with one request:

    curl -s https://raw.githubusercontent.com/SirGrokkius/grokkius-fleet/main/results/latest.json

## Rules this repo follows

- Actions are used only for testing and monitoring the software/sites this project publishes
  (GitHub Additional Product Terms for Actions). No mining, no unrelated compute, small jobs, odd-minute schedules.
- **No secrets in this repo.** Worker secrets live in Cloudflare (`wrangler secret put`); Actions only use the built-in `GITHUB_TOKEN`.
- Polite HTTP: one request per unique URL per run, 8 workers max, identifying User-Agent.

## Local test

    python -m unittest discover -s tests -v
    node worker/test.mjs

MIT licensed.
