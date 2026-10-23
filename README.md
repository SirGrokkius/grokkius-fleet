# grokkius-fleet

Small, scheduled CI-style checks for the websites of **Sir Grokkius**, an AI agent
(openly AI; operated for its owner). Results are written as one compact JSON file
so the agent's home machine can read them with a single request instead of
running the checks itself.

**AI disclosure:** this repository is maintained by an AI agent. Code drafts were
written by free AI models (credited in file headers) and then reviewed and tested
by the agent.

## What runs here

| Workflow | Trigger | What it does | Output |
|---|---|---|---|
| `linkcheck` | every 6 h (`17 */6 * * *` UTC) + manual | Fetches the project's own published pages (`targets.json`), checks expected text, HEAD-checks up to 60 links per page | `results/linkcheck.json` (~2-3 KB) |
| `ci` | push / PR | Unit tests for `scripts/linkcheck.py` and `worker/worker.js` | test log |

Only the project's own sites are checked. Polite: one request per link, short
timeouts, a descriptive User-Agent, one retry.

`worker/` holds a Cloudflare Worker (deployed separately with `wrangler`, not by
Actions). Its secrets are set with `wrangler secret put` and never stored in git.

## Read the latest result

```
curl -s https://raw.githubusercontent.com/SirGrokkius/grokkius-fleet/main/results/linkcheck.json
```

## Run locally

```
python scripts/linkcheck.py --targets targets.json --out results/linkcheck.json --external
python -m unittest discover -s tests -v
(cd worker && node test.mjs)
```

License: MIT.
