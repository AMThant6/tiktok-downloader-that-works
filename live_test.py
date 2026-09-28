"""End-to-end live test against a real TikTok URL.

Usage:
    python live_test.py --cookies <path> --url <tiktok url> [--download]

Drives the app through its real HTTP API, exactly as the browser UI does.
Cookie values are never printed - only names and counts.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BASE = "http://127.0.0.1:5000"


def call(path, payload=None, timeout=300):
    """Return (status, parsed_json_or_raw_text)."""
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except ValueError:
                return r.status, body  # non-JSON (the HTML page, a file body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", required=True, help="path to a cookies export")
    ap.add_argument("--url", required=True, help="TikTok video or drama URL")
    ap.add_argument("--download", action="store_true", help="also download the best gear")
    ap.add_argument("--gear", type=int, default=None, help="gear index to download")
    args = ap.parse_args()

    cookie_text = Path(args.cookies).read_text(encoding="utf-8")
    print(f"cookies file : {args.cookies}  ({len(cookie_text)} chars)")
    print(f"target url   : {args.url}")

    sys.path.insert(0, str(ROOT))
    import app as appmod

    cookies, _jar = appmod.parse_cookies(cookie_text)
    print(f"cookies kept : {len(cookies)} tiktok cookies")
    domains = sorted({c["domain"] for c in cookies})
    print(f"domains      : {domains}")
    print(f"sessionid    : {'present' if any(c['name'] == 'sessionid' for c in cookies) else 'MISSING'}")
    print(f"msToken      : {sum(1 for c in cookies if c['name'] == 'msToken')} entries")
    print("")

    # Server stdout goes to a FILE, not a pipe. A pipe that nobody drains
    # fills its 4KB buffer and blocks the server mid-request.
    log_path = Path(tempfile.gettempdir()) / "ttdl_live_server.log"
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "app.py"), "--no-browser"],
        stdout=log_file, stderr=subprocess.STDOUT, cwd=str(ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    try:
        for _ in range(40):
            time.sleep(0.5)
            if call("/", timeout=5)[0] == 200:
                break
        else:
            print("server never came up")
            print(log_file.read()[:2000])
            return 1

        print("== POST /api/info (capture) ==")
        t0 = time.time()
        st, d = call("/api/info", {"url": args.url, "cookies": cookie_text})
        elapsed = time.time() - t0

        if not d.get("ok"):
            print(f"  FAILED after {elapsed:.1f}s")
            print(f"  code    : {d.get('code')}")
            print(f"  message : {d.get('error')}")
            return 1

        print(f"  ok in {elapsed:.1f}s  (cached={d.get('cached')})")
        print(f"  kind  : {d.get('kind')}")
        print(f"  title : {d.get('title')}")
        print(f"  gears : {len(d.get('gears', []))}")
        print("")
        print("  idx  resolution   kbps      codec       ~size")
        for g in d["gears"]:
            star = " <- BEST" if g["index"] == d["best_index"] else ""
            mb = f"{g['size'] / 1048576:.1f} MB" if g["size"] else "?"
            print(f"  [{g['index']}]  {g['label']:<12} {g['bitrate']:<9} {g['codec']:<11} {mb}{star}")
        print("")

        if not args.download:
            print("capture verified. re-run with --download to fetch the file.")
            return 0

        gear = args.gear if args.gear is not None else d["best_index"]
        print(f"== POST /api/download (gear {gear}) ==")
        st, j = call("/api/download", {"url": args.url, "cookies": cookie_text, "gear_index": gear})
        if not j.get("ok"):
            print(f"  could not start: {j}")
            return 1
        job_id = j["job_id"]
        print(f"  job {job_id}")

        last = ""
        deadline = time.time() + 900
        s = {}
        misses = 0
        while time.time() < deadline:
            time.sleep(1)
            st, s = call("/api/job/" + job_id)
            if not isinstance(s, dict) or "status" not in s:
                # Transient connection hiccup - tolerate a few before giving up.
                misses += 1
                print(f"  (poll {misses} failed: {str(s)[:90]})")
                if misses >= 8:
                    print("  server stopped responding")
                    break
                continue
            misses = 0
            line = f"  {s.get('status'):<12} {s.get('progress', 0):5.1f}%  " \
                   f"{s.get('done_bytes', 0) / 1048576:6.1f} MB"
            if line != last:
                print(line)
                last = line
            if s.get("status") in ("done", "error"):
                break

        print("")
        if s.get("status") == "done":
            print("  RESULT: done")
            print(f"  file   : {s.get('filename')}")
            print(f"  bytes  : {s.get('done_bytes')} (expected {s.get('expected')})")
            print(f"  note   : {s.get('message')}")
            # Confirm the attachment endpoint serves it, without pulling the
            # whole file into memory.
            req = urllib.request.Request(BASE + "/api/file/" + job_id)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    head = r.read(64)
                    disp = r.headers.get("Content-Disposition", "")
                    ctype = r.headers.get("Content-Type", "")
                    print(f"  /api/file -> HTTP {r.status}, {ctype}")
                    print(f"  disposition: {disp[:110]}")
                    print(f"  first bytes: {head[:8].hex()}  (mp4 magic = 000000..66747970)")
            except Exception as e:
                print(f"  /api/file -> FAILED: {e}")
                return 1
            return 0
        print("  RESULT: error")
        print(f"  code   : {s.get('code')}")
        print(f"  message: {s.get('message')}")
        return 1

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log_file.close()
        out = log_path.read_text(encoding="utf-8", errors="replace")
        errs = [l for l in out.splitlines() if "Error" in l or "Traceback" in l or "Exception" in l]
        if errs:
            print("\n== server errors ==")
            for l in errs[:20]:
                print("  " + l)


if __name__ == "__main__":
    sys.exit(main())
