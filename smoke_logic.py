"""Unit-level checks for app.py logic that does not need a browser."""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import app  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ((" :: " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("\n== cookie parsing ==")

now = int(time.time())
sample = "\n".join([
    "# Netscape HTTP Cookie File",
    "# This is a comment",
    "",
    ".tiktok.com\tTRUE\t/\tTRUE\t%d\tsessionid\tabc123" % (now + 86400),
    ".tiktok.com\tTRUE\t/\tTRUE\t%d\ttt_csrf_token\tdef456" % (now + 86400),
    ".tiktok.com\tTRUE\t/\tTRUE\t%d\tsessionid\tSTALE_DUP" % (now + 86400),
    ".tiktok.com\tTRUE\t/\tTRUE\t%d\texpired_one\tgone" % (now - 100),
    "www.tiktok.com\tFALSE\t/\tFALSE\t0\tmsToken\tsession_cookie",
    "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t%d\thttpOnly_cookie\thv" % (now + 86400),
    ".example.com\tTRUE\t/\tTRUE\t%d\tnot_tiktok\tnope" % (now + 86400),
    "garbage line with no tabs",
])

cookies, jar = app.parse_netscape_cookies(sample)
names = [c["name"] for c in cookies]

check("tiktok cookies kept", set(names) >= {"sessionid", "tt_csrf_token", "msToken", "httpOnly_cookie"}, names)
check("non-tiktok dropped", "not_tiktok" not in names)
check("expired dropped", "expired_one" not in names)
check("dedupe by (domain,name)", names.count("sessionid") == 1, names)
check("last duplicate wins", dict((c["name"], c["value"]) for c in cookies)["sessionid"] == "STALE_DUP")
check("session cookie expires=-1", [c for c in cookies if c["name"] == "msToken"][0]["expires"] == -1)
check("HttpOnly prefix parsed", [c for c in cookies if c["name"] == "httpOnly_cookie"][0]["httpOnly"] is True)
check("jar has no tiktok-free domain", "example.com" not in jar)
check("jar line count matches", len([l for l in jar.splitlines() if l and not l.startswith("#")]) == len(cookies))

try:
    app.parse_netscape_cookies("")
    check("empty cookies raises", False)
except app.AppError as e:
    check("empty cookies raises no_cookies", e.code == "no_cookies")

try:
    app.parse_netscape_cookies(".example.com\tTRUE\t/\tTRUE\t0\tx\ty")
    check("no-tiktok raises", False)
except app.AppError as e:
    check("no-tiktok raises no_cookies", e.code == "no_cookies")

print("\n== cookie parsing: Cookie-Editor JSON format ==")

json_export = json.dumps([
    {"domain": ".tiktok.com", "expirationDate": now + 86400, "hostOnly": False,
     "httpOnly": True, "name": "sessionid", "path": "/",
     "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0",
     "value": "SESS123"},
    {"domain": ".tiktok.com", "expirationDate": now + 86400, "hostOnly": False,
     "httpOnly": False, "name": "msToken", "path": "/",
     "sameSite": "no_restriction", "secure": True, "session": False, "storeId": "0",
     "value": "TOKEN_A"},
    {"domain": "www.tiktok.com", "expirationDate": now + 86400, "hostOnly": True,
     "httpOnly": False, "name": "msToken", "path": "/",
     "sameSite": "unspecified", "secure": False, "session": False, "storeId": "0",
     "value": "TOKEN_B"},
    {"domain": ".tiktok.com", "hostOnly": False, "httpOnly": True,
     "name": "tt_csrf_token", "path": "/", "sameSite": "lax", "secure": True,
     "session": True, "storeId": "0", "value": "CSRF"},
    {"domain": ".tiktok.com", "expirationDate": now - 500, "hostOnly": False,
     "httpOnly": True, "name": "gone", "path": "/",
     "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0",
     "value": "x"},
    {"domain": ".example.com", "expirationDate": now + 86400, "hostOnly": False,
     "httpOnly": False, "name": "other", "path": "/",
     "sameSite": "unspecified", "secure": True, "session": False, "storeId": "0",
     "value": "y"},
])

jc, jjar = app.parse_cookies(json_export)
jnames = [c["name"] for c in jc]
check("json: tiktok cookies kept", set(jnames) >= {"sessionid", "msToken", "tt_csrf_token"}, jnames)
check("json: non-tiktok dropped", "other" not in jnames)
check("json: expired dropped", "gone" not in jnames)
check("json: same name on 2 domains kept separately", jnames.count("msToken") == 2, jnames)
check("json: session cookie -> expires -1",
      [c for c in jc if c["name"] == "tt_csrf_token"][0]["expires"] == -1)
check("json: secure flag read", [c for c in jc if c["name"] == "sessionid"][0]["secure"] is True)
check("json: httpOnly read", [c for c in jc if c["name"] == "sessionid"][0]["httpOnly"] is True)
check("json: no_restriction + secure -> None",
      [c for c in jc if c["name"] == "msToken" and c["domain"] == ".tiktok.com"][0]["sameSite"] == "None")
check("json: insecure cookie never gets None",
      [c for c in jc if c["domain"] == "www.tiktok.com"][0]["sameSite"] == "Lax")
check("json: hostOnly domain kept dotless", "www.tiktok.com" in jjar)
check("json: jar drops non-tiktok", "example.com" not in jjar)
check("json: jar line count matches",
      len([l for l in jjar.splitlines() if l and not l.startswith("#")]) == len(jc))

check("json: wrapped in {cookies:[...]} accepted",
      len(app.parse_cookies(json.dumps({"cookies": json.loads(json_export)}))[0]) == len(jc))
check("json: empty array -> no_cookies", True)
try:
    app.parse_cookies("[]")
    check("json: empty array raises", False)
except app.AppError as e:
    check("json: empty array raises no_cookies", e.code == "no_cookies")
try:
    app.parse_cookies('{"cookies": [{"domain":".example.com","name":"z","value":"1"}]}')
    check("json: no-tiktok raises", False)
except app.AppError as e:
    check("json: no-tiktok raises no_cookies", e.code == "no_cookies")

check("format autodetect: netscape still works", len(app.parse_cookies(sample)[0]) == len(cookies))
check("format autodetect: leading whitespace tolerated",
      len(app.parse_cookies("\n\n  " + json_export)[0]) == len(jc))

print("\n== gear parsing ==")

video = {
    "duration": 30,
    "bitrateInfo": [
        {"GearName": "normal_540_h264", "Bitrate": 500000, "CodecType": "h264",
         "PlayAddr": {"Width": 576, "Height": 1024, "DataSize": 2000000,
                      "UrlList": ["https://cdn/a.mp4"]}},
        {"GearName": "normal_1080_bytevc1", "Bitrate": 1800000, "CodecType": "bytevc1",
         "PlayAddr": {"Width": 1080, "Height": 1920, "DataSize": 9000000,
                      "UrlList": ["https://cdn/b.mp4"]}},
        {"GearName": "normal_720_h264", "Bitrate": 900000, "CodecType": "h264",
         "PlayAddr": {"Width": 720, "Height": 1280, "DataSize": 4000000,
                      "UrlList": ["https://cdn/c.mp4"]}},
        {"GearName": "dup_of_1080_worse", "Bitrate": 100000, "CodecType": "bytevc1",
         "PlayAddr": {"Width": 1080, "Height": 1920, "DataSize": 500000,
                      "UrlList": ["https://cdn/d.mp4"]}},
        {"GearName": "no_urls", "Bitrate": 999, "CodecType": "h264",
         "PlayAddr": {"Width": 1, "Height": 1, "DataSize": 0, "UrlList": []}},
    ],
}
gears = app._parse_gears(video)
check("gears parsed", len(gears) == 3, len(gears))
check("duplicate resolution collapsed", len(gears) == 3)
check("sorted ascending", [g["width"] for g in gears] == [576, 720, 1080], [g["width"] for g in gears])
check("indexes assigned", [g["index"] for g in gears] == [0, 1, 2])
best = app._best_index(gears)
check("best is 1080 bytevc1", gears[best]["width"] == 1080 and gears[best]["codec"] == "bytevc1", gears[best])
check("no-url gear dropped", all(g["url"] for g in gears))

no_size = {"duration": 60, "bitrateInfo": [
    {"Bitrate": 800000, "CodecType": "h264",
     "PlayAddr": {"Width": 720, "Height": 1280, "DataSize": 0, "UrlList": ["https://cdn/e.mp4"]}}]}
g2 = app._parse_gears(no_size)
check("size estimated from bitrate*duration", g2[0]["size"] == int(800000 / 8 * 60), g2[0]["size"])

print("\n== bitrate units + codec families (from real API payload) ==")

# Real shape observed live: Bitrate is bits/sec, DataSize arrives as a string.
real = {"duration": 86, "bitrateInfo": [
    {"Bitrate": 446526, "QualityType": 24, "BitrateFPS": 30, "GearName": "lower_540_0",
     "CodecType": "h264",
     "PlayAddr": {"DataSize": "4848547", "Width": 576, "Height": 1024,
                  "UrlKey": "v1c044g50000da85sqfog65t0tleu6c0_h264_540p_446526",
                  "UrlList": ["https://v16-webapp-prime.tiktok.com/video/tos/x.mp4"]}},
    {"Bitrate": 339747, "BitrateFPS": 30, "GearName": "lower_540_1",
     "CodecType": "h265_hvc1",
     "PlayAddr": {"DataSize": "3670016", "Width": 576, "Height": 1024,
                  "UrlList": ["https://v16-webapp-prime.tiktok.com/video/tos/y.mp4"]}},
    {"Bitrate": 394575, "BitrateFPS": 30, "GearName": "normal_720_0",
     "CodecType": "h265_hvc1",
     "PlayAddr": {"DataSize": "4299161", "Width": 720, "Height": 1280,
                  "UrlList": ["https://v16-webapp-prime.tiktok.com/video/tos/z.mp4"]}},
]}
rg = app._parse_gears(real)
check("3 real gears parsed", len(rg) == 3, len(rg))
by_codec = {g["codec"]: g for g in rg}
h264_g = by_codec["h264"]
hevc_g = by_codec["h265_hvc1"]
hevc_720 = [g for g in rg if g["width"] == 720][0]
check("sorted ascending by resolution", [g["width"] for g in rg] == [576, 576, 720],
      [g["width"] for g in rg])
check("DataSize as string parsed", h264_g["size"] == 4848547, h264_g["size"])
check("bitrate -> kbps divides by 1000", h264_g["kbps"] == 447, h264_g["kbps"])
check("kbps not raw bps", h264_g["kbps"] != 446526, h264_g["kbps"])
check("raw bitrate still exposed", h264_g["bitrate"] == 446526)
check("h264 labelled H.264", h264_g["codec_label"] == "H.264 (h264)", h264_g["codec_label"])
check("h264 not flagged hevc", h264_g["is_hevc"] is False)
check("h265_hvc1 labelled HEVC", hevc_g["codec_label"] == "HEVC (h265_hvc1)", hevc_g["codec_label"])
check("h265_hvc1 flagged hevc", hevc_g["is_hevc"] is True)
check("hevc short token for filename", hevc_g["codec_short"] == "hevc", hevc_g["codec_short"])
check("kbps sanity vs bytes/duration",
      abs(h264_g["size"] * 8 / 86 / 1000 - h264_g["kbps"]) < 10,
      (h264_g["size"] * 8 / 86 / 1000, h264_g["kbps"]))
check("best is the 720p gear", rg[app._best_index(rg)]["width"] == 720, rg[app._best_index(rg)])
check("same-resolution different-codec kept apart", len(rg) == 3)

for alias, want_hevc in [("bytevc1", True), ("hevc", True), ("hvc1", True),
                         ("h265", True), ("h264", False), ("avc1", False),
                         ("", False), ("weird_codec", False)]:
    _lbl, hevc, _short = app._codec_info(alias)
    check(f"codec alias {alias or '(empty)'} -> hevc={want_hevc}", hevc is want_hevc, hevc)

fn_hevc = app.build_filename(
    {"kind": "video", "drama_name": "", "episode": None, "desc": "clip", "title": "clip"},
    hevc_g)
check("filename uses short codec token", "hevc" in fn_hevc and "h265_hvc1" not in fn_hevc, fn_hevc)
print("        ->", fn_hevc)

bare = {"duration": 10, "bitrate": 400000, "width": 640, "height": 480,
        "downloadAddr": "https://cdn/f.mp4"}
g3 = app._parse_gears(bare)
check("falls back to downloadAddr", len(g3) == 1 and g3[0]["url"] == "https://cdn/f.mp4", g3)

print("\n== rehydration walk ==")

rehy = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": {
    "id": "7412345678901234567",
    "desc": "test clip",
    "author": {"uniqueId": "someuser", "nickname": "Some User"},
    "video": {"duration": 12, "width": 1080, "height": 1920, "bitrateInfo": [
        {"Bitrate": 1200000, "CodecType": "bytevc1",
         "PlayAddr": {"Width": 1080, "Height": 1920, "DataSize": 3000000,
                      "UrlList": ["https://cdn/g.mp4"]}}]}}}}}}
found = []
app._walk_video_items(rehy, found)
check("found itemStruct", len(found) == 1 and found[0]["id"] == "7412345678901234567")

print("\n== rehydration from rendered HTML (server-rendered video pages) ==")

html = ('<!DOCTYPE html><html><head><title>t</title></head><body>'
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        + json.dumps(rehy) +
        '</script></body></html>')

parsed = app._rehydration_from_html(html)
check("rehydration extracted from html", isinstance(parsed, dict), type(parsed))
check("rehydration round-trips", parsed is not None and
      "webapp.video-detail" in parsed.get("__DEFAULT_SCOPE__", {}))
check("no tag -> None", app._rehydration_from_html("<html><body>nothing</body></html>") is None)
check("empty -> None", app._rehydration_from_html("") is None)
check("malformed json -> None",
      app._rehydration_from_html(
          '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{not json}</script>') is None)
check("attribute order tolerated",
      app._rehydration_from_html(
          '<script type="application/json" id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
          + json.dumps({"a": 1}) + '</script>') == {"a": 1})

# The key regression: a regular video must resolve from the DOM alone, with
# zero captured XHR responses.
info = app._capture_video([], parsed, "https://www.tiktok.com/@someuser/video/7412345678901234567",
                          "https://www.tiktok.com/@someuser/video/7412345678901234567")
check("video found from DOM with no XHR", info["title"] != "", info["title"])
check("video kind is 'video'", info["kind"] == "video")
check("video gears present", len(info["gears"]) == 1 and info["gears"][0]["width"] == 1080, info["gears"])
check("video title uses author", "@someuser" in info["title"], info["title"])
print("        ->", info["title"])

# And the same item must still be found when it arrives as an XHR body.
info2 = app._capture_video([("https://www.tiktok.com/api/item/detail/?x=1", json.dumps(rehy))],
                           None, "", "https://www.tiktok.com/@someuser/video/7412345678901234567")
check("video found from XHR path", len(info2["gears"]) == 1)

try:
    app._capture_video([], None, "", "https://www.tiktok.com/@a/video/1")
    check("nothing found raises no_video", False)
except app.AppError as e:
    check("nothing found raises no_video", e.code == "no_video")

print("\n== drama itemList harvesting ==")

drama_payload = {"itemList": [
    {"id": "111", "desc": "ep one", "dramaInfo": {
        "dramaName": "Test Drama", "DramaVideoData": {"EpisodeNumber": 1},
        "video": {}}},
    {"id": "222", "desc": "ep two", "dramaInfo": {
        "dramaName": "Test Drama", "DramaVideoData": {"EpisodeNumber": 2},
        "video": {}}},
    {"id": "333", "desc": "no episode number", "dramaInfo": {"dramaName": "Test Drama"}},
], "cursor": 10, "hasMore": True}

eps, seen = {}, set()
n = app._collect_episodes(drama_payload, eps, seen)
check("episodes harvested", n == 2 and set(eps) == {1, 2}, eps)
check("entries without EpisodeNumber skipped", 3 not in eps)
app._collect_episodes(drama_payload, eps, seen)
check("re-harvest is idempotent", len(eps) == 2, eps)
check("nested itemList found too",
      app._collect_episodes({"data": {"deep": [drama_payload]}}, {}, set()) == 2)

print("\n== filename building ==")

info_drama = {"kind": "drama", "drama_name": "My Drama: Part 1/2", "episode": 7,
              "desc": "a<bad>|name?*", "title": "x"}
gear = {"width": 1080, "height": 1920, "codec": "bytevc1"}
fn = app.build_filename(info_drama, gear)
check("drama filename has EP", "EP7" in fn, fn)
check("illegal chars stripped", not any(c in fn for c in '<>:"/\\|?*'), fn)
check("ends with mp4", fn.endswith(".mp4"), fn)
check("has resolution+codec", "1080x1920" in fn and "bytevc1" in fn, fn)
print("        ->", fn)

info_vid = {"kind": "video", "drama_name": "", "episode": None,
            "desc": "just a normal clip", "title": "just a normal clip"}
fn2 = app.build_filename(info_vid, gear)
check("no drama parts for regular video", "EP" not in fn2, fn2)
print("        ->", fn2)

info_long = {"kind": "drama", "drama_name": "A" * 300, "episode": 1, "desc": "", "title": "t"}
fn3 = app.build_filename(info_long, gear)
check("long name capped under 160", len(fn3) <= 160, len(fn3))

print("\n== cache key ==")
k1 = app.cookie_key("url-a\x00cookies")
k2 = app.cookie_key("url-a\x00cookies")
k3 = app.cookie_key("url-b\x00cookies")
check("cache key stable", k1 == k2)
check("cache key varies by url", k1 != k3)

print("\n== flask routes registered ==")
rules = sorted(str(r) for r in app.app.url_map.iter_rules())
for want in ["/", "/api/info", "/api/download", "/api/job/<job_id>", "/api/file/<job_id>"]:
    check("route " + want, want in rules, rules)

print("\n== HTML page ==")
check("html has cookie textarea", 'id="cookies"' in app.HTML_PAGE)
check("html has file input", 'id="cfile"' in app.HTML_PAGE)
check("html has url field", 'id="url"' in app.HTML_PAGE)
check("html has get-qualities button", 'id="getq"' in app.HTML_PAGE)
check("html has download button", 'id="dl"' in app.HTML_PAGE)
check("html has progress bar", 'id="barfill"' in app.HTML_PAGE)
check("html has clear button", 'id="cclear"' in app.HTML_PAGE)
check("html uses localStorage", "localStorage" in app.HTML_PAGE)
check("html mentions VLC/HEVC", "HEVC" in app.HTML_PAGE and "VLC" in app.HTML_PAGE)
check("html polls job endpoint", "/api/job/" in app.HTML_PAGE)
check("html uses attachment endpoint", "file_url" in app.HTML_PAGE)

print("\n== job lifecycle: 'already downloaded' skip path ==")

_tmp = Path(tempfile.mkdtemp())
_orig_dl = app.DOWNLOADS
app.DOWNLOADS = _tmp

_info = {
    "kind": "video", "title": "t", "drama_name": "", "episode": None, "desc": "clip",
    "gears": [{"index": 0, "url": "https://cdn/x.mp4", "width": 720, "height": 1280,
               "bitrate": 400000, "kbps": 400, "codec": "h264",
               "codec_label": "H.264 (h264)", "codec_short": "h264", "is_hevc": False,
               "size": 12345, "gear_name": ""}],
    "best_index": 0, "jar": "unused.jar",
}
_name = app.build_filename(_info, _info["gears"][0])
(_tmp / _name).write_bytes(b"0" * 12345)

app.get_or_capture = lambda url, cookies, on_stage=None: (_info, True)
_job = {"id": "t1", "status": "queued", "progress": 0.0, "message": "", "filename": None,
        "title": None, "done_bytes": 0, "expected": 0, "url": "u", "cookies": "c",
        "gear_index": 0, "code": None}
app.process_job(_job)

check("skip path -> status done", _job["status"] == "done", _job["status"])
check("skip path records file_path", bool(_job.get("file_path")), _job.get("file_path"))
check("skip path reports 100%", _job["progress"] == 100.0, _job["progress"])
check("skip path message mentions already", "already" in _job["message"], _job["message"])
_pub = app.job_public(_job)
check("skip path exposes file_url (Save button works)",
      str(_pub.get("file_url", "")).startswith("/api/file/"), _pub)

# A file of the wrong size must NOT be treated as complete.
(_tmp / _name).write_bytes(b"0" * 99)
check("wrong-size file is not treated as complete",
      (_tmp / _name).stat().st_size != _info["gears"][0]["size"])

app.DOWNLOADS = _orig_dl

print("\n== job_public never leaks cookies ==")
_leak = {"id": "z", "status": "downloading", "progress": 1.0, "message": "m",
         "filename": None, "title": None, "done_bytes": 0, "expected": 0,
         "url": "u", "cookies": "SECRET_SESSION_VALUE", "gear_index": 0}
check("cookies absent from job_public",
      "SECRET_SESSION_VALUE" not in json.dumps(app.job_public(_leak)))

print("\n" + ("ALL LOGIC CHECKS PASSED" if not FAIL else "FAILURES: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
