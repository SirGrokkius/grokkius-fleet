#!/usr/bin/env python3
# Draft by openai/gpt-oss-120b (via Groq, ai-job fleet-linkcheck-1023); reviewed, fixed (retry bug, hashing, external links) and tested by Sir Grokkius (AI agent).
"""
linkcheck.py – CI smoke‑test for published sites.

Usage:
    python linkcheck.py --targets targets.json --out results/linkcheck.json \
        [--timeout 20] [--workers 6] [--prev results/linkcheck.json]
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------

MAX_BYTES = 2 * 1024 * 1024          # 2 MiB
MAX_LINKS_EXTRACT = 200
MAX_LINKS_CHECK = 60
RETRY_DELAY = 3.0                    # seconds
USER_AGENT = (
    "grokkius-fleet-linkcheck/1.0 (+https://github.com/SirGrokkius/grokkius-fleet)"
)

# ---------------------------------------------------------------------------

def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read JSON from {path}: {e}", file=sys.stderr)
        sys.exit(2)


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)


def fetch_url(url: str, timeout: int):
    """Return (code, body_bytes, elapsed_ms) or raise."""
    headers = {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, headers=headers, method="GET")
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        body = resp.read(MAX_BYTES + 1)  # read a bit more to know if we exceed
        if len(body) > MAX_BYTES:
            body = body[:MAX_BYTES]
        elapsed = (time.perf_counter() - start) * 1000
        return code, body, elapsed
    # unreachable


def head_or_get(url: str, timeout: int):
    """Return (code, error_flag). 405 on HEAD falls back to GET."""
    headers = {"User-Agent": USER_AGENT}
    # HEAD
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), None
    except urllib.error.HTTPError as e:
        if e.code == 405:  # Method Not Allowed – try GET
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.getcode(), None
            except urllib.error.HTTPError as e2:
                return e2.code, None
            except Exception as exc:
                return None, exc
        return e.code, None
    except Exception as exc:
        return None, exc


def extract_links(html: str, base_url: str, external: bool = False):
    """Return up to MAX_LINKS_EXTRACT absolute same‑host URLs (deduped)."""
    base = urllib.parse.urlparse(base_url)
    pattern = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
    found = set()
    for match in pattern.finditer(html):
        href = match.group(1).strip()
        if not href:
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(abs_url)
        # drop fragment
        parsed = parsed._replace(fragment="")
        abs_url = urllib.parse.urlunparse(parsed)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != base.netloc and not external:
            continue
        if abs_url not in found:
            found.add(abs_url)
        if len(found) >= MAX_LINKS_EXTRACT:
            break
    return list(found)


def process_target(target, timeout, workers, external=False):
    name = target["name"]
    url = target["url"]
    terms = target.get("terms", [])
    result = {
        "name": name,
        "url": url,
        "status": None,
        "code": None,
        "ms": None,
        "bytes": 0,
        "sha256_16": None,
        "missing": [],
        "broken_links": [],
        "changed": False,
    }

    # ---- fetch with one retry on network error / 5xx ----
    attempt = 0
    code, body, elapsed = None, b"", 0
    while attempt < 2:
        try:
            code, body, elapsed = fetch_url(url, timeout)
            break
        except urllib.error.HTTPError as e:
            # HTTPError provides a code; treat 5xx as retryable
            if 500 <= e.code <= 599 and attempt == 0:
                attempt += 1
                time.sleep(RETRY_DELAY)
                continue
            # other HTTP errors are final
            code, body, elapsed = e.code, b"", 0
            break
        except Exception:
            attempt += 1
            if attempt < 2:
                time.sleep(RETRY_DELAY)
                continue
            # after retry give up
            code, body, elapsed = None, b"", 0
            break

    # Record generic fields
    result["code"] = code
    result["ms"] = int(elapsed) if elapsed is not None else None
    result["bytes"] = len(body)

    # ---- classify status ----
    if code is None:
        result["status"] = "dead"
        return result

    if 200 <= code <= 299:
        result["sha256_16"] = hashlib.sha256(body).hexdigest()[:16]
        # ok – inspect terms
        text = body.decode("utf-8", errors="ignore")
        missing = [t for t in terms if t.lower() not in text.lower()]
        if missing:
            result["status"] = "missing_terms"
            result["missing"] = missing
        else:
            result["status"] = "ok"

            # ---- extract & check links (limited to MAX_LINKS_CHECK) ----
            links = sorted(extract_links(text, url, external or target.get("external", False)))[:MAX_LINKS_CHECK]
            result["links_checked"] = len(links)

            if links:
                broken = []

                def check_one(link):
                    c, err = head_or_get(link, timeout)
                    if err is not None or (c is not None and c >= 500):
                        time.sleep(RETRY_DELAY)
                        c, err = head_or_get(link, timeout)
                    if err is not None or (c is not None and c >= 400):
                        out = {"url": link, "code": c}
                        if err is not None:
                            out["err"] = type(err).__name__
                        return out
                    return None

                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {ex.submit(check_one, l): l for l in links}
                    for fut in concurrent.futures.as_completed(futures):
                        br = fut.result()
                        if br:
                            broken.append(br)

                result["broken_links"] = sorted(broken, key=lambda b: b["url"])
    elif code in (401, 403, 429):
        result["status"] = "blocked"
    elif code in (404, 410):
        result["status"] = "dead"
    else:
        result["status"] = "error"

    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--targets", required=True, type=Path, help="JSON file with targets")
    p.add_argument("--out", required=True, type=Path, help="Result JSON file")
    p.add_argument("--timeout", type=int, default=20, help="Request timeout seconds")
    p.add_argument("--workers", type=int, default=6, help="Thread pool size")
    p.add_argument("--prev", type=Path, help="Previous results for change detection")
    p.add_argument("--external", action="store_true", help="also check off-site links")
    args = p.parse_args()

    # load targets
    data = load_json(args.targets)
    if not isinstance(data, dict) or "targets" not in data:
        print("Invalid targets file: missing 'targets' key", file=sys.stderr)
        sys.exit(2)
    targets = data["targets"]
    if not isinstance(targets, list):
        print("Invalid targets file: 'targets' must be a list", file=sys.stderr)
        sys.exit(2)

    # load previous results if any
    prev_map = {}
    if args.prev and args.prev.is_file():
        try:
            prev = json.loads(args.prev.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        for entry in prev.get("results", []):
            prev_map[entry["name"]] = entry.get("sha256_16")

    results = []
    summary = {
        "total": 0,
        "ok": 0,
        "missing_terms": 0,
        "blocked": 0,
        "dead": 0,
        "error": 0,
        "broken_links": 0,
        "changed": 0,
    }

    # process targets concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_target, tgt, args.timeout, max(2, args.workers // 2), args.external): tgt
            for tgt in targets
        }
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            # change detection
            prev_hash = prev_map.get(res["name"])
            if res["sha256_16"] and prev_hash and res["sha256_16"] != prev_hash:
                res["changed"] = True
                summary["changed"] += 1
            else:
                res["changed"] = False

            # update summary counters
            summary["total"] += 1
            status = res["status"]
            if status in summary:
                summary[status] += 1
            if status == "ok":
                broken = len(res.get("broken_links", []))
                summary["broken_links"] += broken

            results.append(res)

    # sort results
    results.sort(key=lambda x: x["name"])

    out_obj = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": summary,
        "results": results,
    }

    save_json(out_obj, args.out)

    # one‑line summary to stdout
    print(
        f"Generated {summary['total']} results: ok={summary['ok']} "
        f"missing_terms={summary['missing_terms']} blocked={summary['blocked']} "
        f"dead={summary['dead']} error={summary['error']} broken_links={summary['broken_links']} "
        f"changed={summary['changed']}"
    )


if __name__ == "__main__":
    main()
