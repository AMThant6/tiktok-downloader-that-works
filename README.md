# TikTok Downloader That Works

**Downloads TikTok videos and short dramas in the best available quality, using
your own logged-in Chrome session — so it keeps working on networks where other
downloaders get blocked.**

No command line, no cloud service, no third-party API. You paste a URL, pick a
quality, and the file lands in your Downloads folder. Nothing leaves your machine.

---

## Why this exists

Most TikTok downloaders wrap `yt-dlp`. That works fine until it doesn't: on many
networks and IP ranges, `yt-dlp` fails with

```
Your IP address is blocked from accessing this post
```

even when you supply valid, freshly-exported cookies. The block is at the CDN
layer, keyed on how the request looks, not on whether you are authenticated.

This project takes a different route. Instead of impersonating a browser with an
HTTP client, it **drives the real one**. Playwright launches your installed Google
Chrome, loads your cookies into it, opens the page like a person would, and reads
the video metadata out of the response stream. The download itself then goes
through `curl.exe`, which handles the CDN's flaky connections far better than any
Python HTTP stack.

In short: **if you can watch it in Chrome, this can download it.**

## How it works

```
  Web UI  ──►  Flask API  ──►  Playwright + Chrome  ──►  curl.exe  ──►  Downloads
 cookies+URL   one job at a      captures bitrateInfo      http/1.1
               time              (cached 10 minutes)       + resume
```

1. **Parse cookies.** Accepts either a Netscape `cookies.txt` export or a
   Cookie-Editor / EditThisCookie JSON export. Only `tiktok` domains survive,
   duplicates collapse on `(domain, name)`, expired entries are dropped. The
   result feeds *both* the browser context and a filtered curl cookie jar, so the
   two can never drift apart.

2. **Capture.** Headless Chrome opens the URL with your session. Every response
   matching `/api/drama/` or `/api/item/detail/` is recorded. For regular videos,
   the item data is read from the server-rendered
   `__UNIVERSAL_DATA_FOR_REHYDRATION__` script tag; for dramas, episodes come from
   the `/api/drama/episode/item_list/` payload, with a scroll loop to pull in more
   episodes when the target one isn't in the first page.

3. **Pick a gear.** `bitrateInfo` entries are normalised into
   resolution / kbps / codec / estimated size. The best is preselected — usually
   1080x1920 HEVC.

4. **Download.** `curl.exe --http1.1 -L --retry 5 --retry-all-errors -C -` pulls
   the chosen URL, with progress polled from the growing file. HTTP/2 is
   deliberately avoided: TikTok's CDNs break it in some clients with
   `expected SETTINGS frame`. `-C -` matters because connections get reset
   mid-transfer; a second click resumes instead of restarting.

5. **Cache.** Capture results are keyed on `sha1(url + cookies)` and reused for
   10 minutes, so pressing Download after Get qualities does not reopen the
   browser. The TTL is sized against the `expire=` parameter TikTok puts in the
   media URLs.

## Requirements

- Windows 10 or 11
- Python 3.10+
- Google Chrome installed
- `curl.exe` (bundled with Windows 10 1803 and later)

## Setup

```bash
pip install -r requirements.txt
```

You do **not** need to run `playwright install`. The app launches your existing
Chrome via `channel="chrome"`, so there is no 150 MB Chromium download.

## Run

```bash
python app.py
```

It binds to `127.0.0.1:5000`, prints the URL, and opens the page automatically.
Use `python app.py --no-browser` to skip the auto-open.

## Usage

1. **Cookies.** Log in to tiktok.com in Chrome, then export your cookies for that
   site — either format works. Paste them into the Cookies box. They are kept in
   your browser's `localStorage` only, and there is a Clear button.
2. **URL.** Paste either kind of link:
   - `https://www.tiktok.com/@user/video/1234567890`
   - `https://www.tiktok.com/shortdrama/episode/1234567890/2`
3. **Get qualities**, pick a gear, **Download**.

Files are written to your Downloads folder as
`{dramaName} EP{n} {desc} {w}x{h} {codec}.mp4`, with the drama parts omitted for
regular videos. Windows-illegal characters are stripped and the name is capped so
the full path stays clear of the 260-character limit.

## Notes and caveats

- **HEVC needs a real player.** The top gear is usually 1080x1920 HEVC
  (`bytevc1` or `h265_hvc1` — TikTok uses both spellings). Windows Media Player
  may refuse it; use VLC, mpv, or install the HEVC extension for Films & TV.
- **Cookies expire.** A sudden HTTP 403 means re-export them. This is normal, not
  a bug.
- **A download that stops short resumes.** Press Download again; curl picks up
  from where it stopped rather than starting over.
- **Identical files are skipped.** If a file of exactly the expected size is
  already in Downloads, the job completes instantly without re-downloading.
- **One job at a time** by design, so only ever one Chrome instance is running.
- The Flask dev server is used deliberately. This is a single-user localhost tool;
  it is not hardened for exposure to a network.

## Testing

Three layers, all in the repo:

| Script | What it covers |
|---|---|
| `smoke_logic.py` | ~70 offline assertions: cookie parsing (both formats), gear parsing, unit conversions, filename sanitising, DOM extraction, job lifecycle. No browser needed. |
| `smoke_live.py` | Boots the server and exercises every endpoint and error path, including the 404s and the localhost-only bind. |
| `live_test.py --cookies <path> --url <url> [--download]` | Real end-to-end run against a live URL. Reads cookies from a path; never embeds them. |

Verified end-to-end against real TikTok content with exact byte matches on
regular videos, short-drama episodes, and multiple gears.

## Credits and responsible use

Built because the usual tool failed on a network it could not handle. It is
intended for downloading content you have the right to download — your own
uploads, material you have permission to use, or content you are entitled to
archive.

Respect creators and TikTok's Terms of Service. Do not redistribute other
people's work, and do not use this to bulk-scrape the platform.

## License

MIT — see [LICENSE](LICENSE).
