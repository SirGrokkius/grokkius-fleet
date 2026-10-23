"""Offline tests for scripts/linkcheck.py using a local http.server."""
import json, os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import linkcheck  # noqa: E402

PAGES = {
    "/a": (200, '<a href="/b">b</a> <a href="/gone">x</a> <a href="/nohead">n</a> <a href="mailto:x@y">m</a> hello world'),
    "/b": (200, "plain"),
    "/gone": (404, ""),
    "/nohead": (200, "ok"),
    "/forbidden": (403, ""),
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, head):
        code, body = PAGES.get(self.path, (404, ""))
        if head and self.path == "/nohead":
            code = 405
        self.send_response(code); self.send_header("Content-Type", "text/html"); self.end_headers()
        if not head: self.wfile.write(body.encode())
    def do_GET(self): self._send(False)
    def do_HEAD(self): self._send(True)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        linkcheck.RETRY_DELAY = 0

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def run_lc(self, targets, prev=None):
        d = tempfile.mkdtemp()
        tf, of = os.path.join(d, "t.json"), os.path.join(d, "o.json")
        json.dump({"targets": targets}, open(tf, "w"))
        args = ["--targets", tf, "--out", of, "--timeout", "5"] + (["--prev", prev] if prev else [])
        self.assertEqual(linkcheck.main(args), 0)
        return json.load(open(of)), of

    def test_statuses_and_links(self):
        b = self.base
        out, of = self.run_lc([
            {"name": "a", "url": b + "/a", "terms": ["hello"]},
            {"name": "a-miss", "url": b + "/a", "terms": ["absent"]},
            {"name": "gone", "url": b + "/gone"},
            {"name": "forb", "url": b + "/forbidden"},
        ])
        st = {r["name"]: r["status"] for r in out["results"]}
        self.assertEqual(st, {"a": "ok", "a-miss": "missing_terms", "gone": "dead", "forb": "blocked"})
        self.assertEqual([x["url"] for x in out["broken"]], [b + "/gone"])  # /nohead falls back to GET
        self.assertEqual(out["summary"]["links_checked"], 2)  # /b + /nohead probed; /gone reused; mailto ignored
        self.assertFalse(any(r["changed"] for r in out["results"]))
        PAGES["/a"] = (200, PAGES["/a"][1] + " v2")
        out2, _ = self.run_lc([{"name": "a", "url": b + "/a", "terms": []}], prev=of)
        self.assertTrue(out2["results"][0]["changed"])

    def test_invalid_targets_exit_2(self):
        d = tempfile.mkdtemp(); tf = os.path.join(d, "t.json")
        open(tf, "w").write('{"targets": [{"name": "x"}]}')
        with self.assertRaises(SystemExit) as c:
            linkcheck.main(["--targets", tf, "--out", os.path.join(d, "o.json")])
        self.assertEqual(c.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
