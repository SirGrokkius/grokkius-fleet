#!/usr/bin/env python3
"""linkcheck.py - scheduled CI smoke test of the Sir Grokkius sites (stdlib only).

Fetches each target page, checks status + required terms, then checks every
absolute http(s) link found on those pages (each unique URL once, capped).
Writes one compact JSON file. Never stores page bodies.

  python scripts/linkcheck.py --targets targets.json --out results/linkcheck.json \
      [--prev results/linkcheck.json] [--timeout 20] [--workers 8] [--max-links 300]

Drafted by Groq gpt-oss-120b via ai-job (fleet-linkcheck-1023); reviewed and fixed by
Sir Grokkius (an AI agent): all links not just same-host, global dedupe, sha for any 2xx,
deterministic order, HEAD->GET fallback on 403/405/501, tolerant --prev, input validation.
"""
import argparse, concurrent.futures as cf, hashlib, json, re, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
RETRY_DELAY = 3.0
UA = "grokkius-fleet-linkcheck/1.0 (+https://github.com/SirGrokkius/grokkius-fleet)"
HREF = re.compile(r'<a\s[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.I)


def _req(url, method, timeout):
    r = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    return urllib.request.urlopen(r, timeout=timeout)


def fetch(url, timeout):
    """GET with one retry on network error / 5xx. Returns (code|None, body, ms)."""
    for attempt in (0, 1):
        t = time.perf_counter()
        try:
            with _req(url, "GET", timeout) as r:
                body = r.read(MAX_BYTES)
                return r.getcode(), body, int((time.perf_counter() - t) * 1000)
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt == 0:
                time.sleep(RETRY_DELAY); continue
            return e.code, b"", int((time.perf_counter() - t) * 1000)
        except Exception:
            if attempt == 0:
                time.sleep(RETRY_DELAY); continue
            return None, b"", int((time.perf_counter() - t) * 1000)


def probe(url, timeout):
    """HEAD, falling back to GET when HEAD is refused. Returns code or None."""
    try:
        with _req(url, "HEAD", timeout) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 501):
            return e.code
    except Exception:
        pass
    code, _, _ = fetch(url, timeout)
    return code


def links_in(html, base):
    out, seen = [], set()
    for m in HREF.finditer(html):
        u = urllib.parse.urljoin(base, m.group(1).strip())
        p = urllib.parse.urlparse(u)
        if p.scheme not in ("http", "https") or not p.netloc:
            continue
        u = urllib.parse.urlunparse(p._replace(fragment=""))
        if u not in seen:
            seen.add(u); out.append(u)
        if len(out) >= 200:
            break
    return out


def classify(code, missing):
    if code is None or code in (404, 410):
        return "dead"
    if 200 <= code < 300:
        return "missing_terms" if missing else "ok"
    if code in (401, 403, 429):
        return "blocked"
    return "error"


def load_targets(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        ts = data["targets"]
        assert isinstance(ts, list) and ts
        for t in ts:
            assert isinstance(t.get("name"), str) and t["name"]
            assert str(t.get("url", "")).startswith(("http://", "https://"))
            assert isinstance(t.get("terms", []), list)
        return ts
    except Exception as e:
        print(f"invalid targets file {path}: {e.__class__.__name__} {e}", file=sys.stderr)
        sys.exit(2)


def load_prev(path):
    try:
        return {r["name"]: r.get("sha256_16") for r in json.loads(Path(path).read_text())["results"]}
    except Exception:
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prev")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-links", type=int, default=300)
    a = ap.parse_args(argv)
    targets = load_targets(a.targets)
    prev = load_prev(a.prev) if a.prev else {}
    t0 = time.time()

    def do_target(t):
        code, body, ms = fetch(t["url"], a.timeout)
        text = body.decode("utf-8", "ignore") if body else ""
        low = text.lower()
        missing = [x for x in t.get("terms", []) if x.lower() not in low] if code and 200 <= code < 300 else []
        sha = hashlib.sha256(body).hexdigest()[:16] if code and 200 <= code < 300 else None
        return {"name": t["name"], "url": t["url"], "status": classify(code, missing), "code": code, "ms": ms,
                "bytes": len(body), "sha256_16": sha, "missing": missing,
                "changed": bool(sha and prev.get(t["name"]) and prev[t["name"]] != sha),
                "_links": links_in(text, t["url"]) if text else []}

    with cf.ThreadPoolExecutor(a.workers) as ex:
        results = sorted(ex.map(do_target, targets), key=lambda r: r["name"])

    # global link check: each unique URL once (target pages reuse their fetch result)
    page_codes = {r["url"]: r["code"] for r in results}  # reuse codes of fetched target pages
    page_urls = set(page_codes)
    uniq = []
    for r in results:
        for u in r["_links"]:
            if u not in page_urls and u not in uniq:
                uniq.append(u)
    skipped = max(0, len(uniq) - a.max_links)
    uniq = uniq[: a.max_links]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        codes = dict(zip(uniq, ex.map(lambda u: probe(u, a.timeout), uniq)))
    checked = len(codes)
    codes.update(page_codes)
    for r in results:
        r["broken_links"] = sorted(({"url": u, "code": codes[u]} for u in r.pop("_links")
                                    if u in codes and (codes[u] is None or codes[u] >= 400)
                                    and codes[u] not in (401, 403, 429)), key=lambda x: x["url"])
    blocked_links = sorted(u for u, c in codes.items() if c in (401, 403, 429) and u not in page_urls)
    s = {k: 0 for k in ("total", "ok", "missing_terms", "blocked", "dead", "error", "broken_links", "changed")}
    for r in results:
        s["total"] += 1; s[r["status"]] += 1; s["changed"] += r["changed"]
    broken = sorted({b["url"]: b for r in results for b in r["broken_links"]}.values(), key=lambda x: x["url"])
    s["broken_links"] = len(broken)
    s.update(links_checked=checked, links_skipped=skipped, links_blocked=len(blocked_links),
             wall_s=round(time.time() - t0, 1))
    out = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "summary": s,
           "broken": broken, "blocked_links": blocked_links, "results": results}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    print("linkcheck " + " ".join(f"{k}={v}" for k, v in s.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
