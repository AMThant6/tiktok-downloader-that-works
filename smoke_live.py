"""Live HTTP checks against a running instance of app.py."""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BASE = "http://127.0.0.1:5000"
FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ((" :: " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def call(path, payload=None, method=None):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:
        return 0, str(e), {}


print("\n== boot ==")
proc = subprocess.Popen(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "app.py"), "--no-browser"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(ROOT),
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)

up = False
for _ in range(40):
    time.sleep(0.5)
    st, _, _ = call("/")
    if st == 200:
        up = True
        break
check("server came up on 127.0.0.1:5000", up)

if not up:
    proc.kill()
    print(proc.stdout.read().decode("utf-8", "replace")[:3000])
    sys.exit(1)

print("\n== GET / ==")
st, body, hdrs = call("/")
check("status 200", st == 200, st)
check("content-type html", "text/html" in hdrs.get("Content-Type", ""), hdrs.get("Content-Type"))
check("page has title", "<title>TikTok Downloader</title>" in body)
check("page has all 4 sections", body.count('class="card"') >= 4, body.count('class="card"'))

print("\n== POST /api/info error paths ==")
st, body, _ = call("/api/info", {})
d = json.loads(body)
check("empty payload -> bad_url", d.get("code") == "bad_url", d)

st, body, _ = call("/api/info", {"url": "https://example.com/video/1", "cookies": "x"})
d = json.loads(body)
check("non-tiktok url -> bad_url", d.get("code") == "bad_url", d)

st, body, _ = call("/api/info", {"url": "https://www.tiktok.com/@a/video/1", "cookies": ""})
d = json.loads(body)
check("missing cookies -> no_cookies", d.get("code") == "no_cookies", d)

st, body, _ = call("/api/info", {"url": "https://www.tiktok.com/@a/video/1",
                                 "cookies": ".example.com\tTRUE\t/\tTRUE\t0\tx\ty"})
d = json.loads(body)
check("non-tiktok cookies -> no_cookies", d.get("code") == "no_cookies", d)

print("\n== POST /api/download error paths ==")
st, body, _ = call("/api/download", {"url": "", "cookies": "x"})
d = json.loads(body)
check("empty url -> bad_url", d.get("code") == "bad_url", d)

st, body, _ = call("/api/download", {"url": "https://www.tiktok.com/@a/video/1", "cookies": "  "})
d = json.loads(body)
check("blank cookies -> no_cookies", d.get("code") == "no_cookies", d)

st, body, _ = call("/api/download", {"url": "https://www.tiktok.com/@a/video/1",
                                     "cookies": ".tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tx"})
d = json.loads(body)
check("valid shape -> returns job_id", d.get("ok") is True and d.get("job_id"), d)
job_id = d.get("job_id")

print("\n== GET /api/job/{id} ==")
st, body, _ = call("/api/job/" + job_id)
d = json.loads(body)
check("job reachable", st == 200 and d.get("ok") is True, d)
check("job exposes status", d.get("status") in
      ("queued", "capturing", "downloading", "done", "error"), d.get("status"))
check("job never echoes cookies", "cookies" not in json.dumps(d), d)

st, body, _ = call("/api/job/does-not-exist")
d = json.loads(body)
check("unknown job -> 404 + no_job", st == 404 and d.get("code") == "no_job", (st, d))

print("\n== GET /api/file/{id} ==")
st, body, _ = call("/api/file/does-not-exist")
check("unknown file -> 404", st == 404, st)
st, body, _ = call("/api/file/" + job_id)
check("unfinished job file -> 404", st == 404, st)

print("\n== the bad-cookie job should fail cleanly, not hang ==")
deadline = time.time() + 150
final = None
while time.time() < deadline:
    time.sleep(2)
    st, body, _ = call("/api/job/" + job_id)
    final = json.loads(body)
    if final.get("status") in ("done", "error"):
        break
check("job reached a terminal state", final and final.get("status") in ("done", "error"),
      final and final.get("status"))
check("failure is friendly (no traceback)", "Traceback" not in (final or {}).get("message", ""),
      (final or {}).get("message"))
print("        status :", (final or {}).get("status"))
print("        code   :", (final or {}).get("code"))
print("        message:", ((final or {}).get("message") or "")[:180])

print("\n== binding ==")
netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
listeners = [l.strip() for l in netstat.splitlines() if ":5000" in l and "LISTENING" in l]
check("listening on port 5000", bool(listeners), listeners)
check("bound to 127.0.0.1 only, not 0.0.0.0",
      all("127.0.0.1:5000" in l for l in listeners), listeners)
for l in listeners:
    print("        " + l)

print("\n== server log ==")
proc.terminate()
try:
    out = proc.stdout.read().decode("utf-8", "replace")
except Exception:
    out = ""
lines = [l for l in out.splitlines() if l.strip()]
for l in lines[:14]:
    print("        " + l)
check("no traceback in server log", "Traceback" not in out)
check("printed local URL", "127.0.0.1:5000" in out)

print("\n" + ("ALL LIVE CHECKS PASSED" if not FAIL else "FAILURES: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
