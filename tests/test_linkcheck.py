import json, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = {
    "/": b'<html>Sir Grokkius <a href="/a">a</a> <a href="/gone">g</a> <a href="#x">x</a></html>',
    "/a": b"<html>fine</html>",
    "/plain": b"<html>no name here</html>",
}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body=True):
        if self.path in PAGES:
            self.send_response(200); self.end_headers()
            if body: self.wfile.write(PAGES[self.path])
        elif self.path == "/forbidden":
            self.send_response(403); self.end_headers()
        else:
            self.send_response(404); self.end_headers()
    def do_GET(self): self._send()
    def do_HEAD(self): self._send(False)

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def run_lc(self, targets, extra=()):
        d = Path(tempfile.mkdtemp())
        (d / "t.json").write_text(json.dumps(targets))
        p = subprocess.run([sys.executable, str(ROOT / "scripts/linkcheck.py"), "--targets", str(d / "t.json"),
                            "--out", str(d / "out/r.json"), "--timeout", "5", *extra], capture_output=True, text=True)
        return p, (json.loads((d / "out/r.json").read_text()) if p.returncode == 0 else None)

    def test_statuses(self):
        b = self.base
        p, r = self.run_lc({"targets": [
            {"name": "home", "url": b + "/", "terms": ["sir grokkius"]},
            {"name": "plain", "url": b + "/plain", "terms": ["Sir Grokkius"]},
            {"name": "forb", "url": b + "/forbidden"},
            {"name": "dead", "url": b + "/nope"}]})
        self.assertEqual(p.returncode, 0, p.stderr)
        by = {x["name"]: x for x in r["results"]}
        self.assertEqual([x["name"] for x in r["results"]], sorted(by))
        self.assertEqual(by["home"]["status"], "ok")
        self.assertEqual(by["home"]["broken_links"], [{"url": b + "/gone", "code": 404}])
        self.assertEqual(by["plain"]["status"], "missing_terms")
        self.assertEqual(by["plain"]["missing"], ["Sir Grokkius"])
        self.assertEqual(by["forb"]["status"], "blocked")
        self.assertEqual(by["dead"]["status"], "dead")
        self.assertEqual(r["summary"]["total"], 4)
        self.assertEqual(r["summary"]["broken_links"], 1)

    def test_invalid_targets(self):
        p, _ = self.run_lc({"nope": 1})
        self.assertEqual(p.returncode, 2)

if __name__ == "__main__":
    unittest.main()
