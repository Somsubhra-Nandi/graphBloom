"""Record the demo video's picture: drives the recording build of the site in step with the voiceover.

Needs: the site built with NEXT_PUBLIC_DEMO=1 and served on localhost:4173 (see demo/README.md),
Playwright with Chromium (.venv/bin/pip install playwright; .venv/bin/python -m playwright install chromium),
ffmpeg, and video/timings.json. Writes video/raw/frames + video/raw/frames.txt (frame list with durations) and
video/raw/events.json (what happened when, in audio time).

macOS screencapture needs a Screen Recording permission that a terminal session may not have, so this records
with Chromium's own screencast (headless: no browser UI, no cursor, no notifications on screen).
  .venv/bin/python scripts/record_demo.py
"""
import base64
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
VID = ROOT / "video"
RAW = VID / "raw"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4173/?demo=1"
T = json.loads((VID / "timings.json").read_text())
SEG = {s["n"]: s for s in T["segments"]}
END = T["audio_duration"] + 1.0  # stop 1 s after the audio ends

# (audio time, js to run)
ACTIONS = [
    (SEG[2]["start"] + 1.15, "demo.startStory(0)"),  # lands on "Someone asks"
    (SEG[3]["start"], "demo.startReplay()"),
    (SEG[4]["start"], "demo.scrollTo('curve')"),
    (SEG[5]["start"], "demo.scrollTo('cost')"),
    ((SEG[5]["start"] + SEG[5]["end"]) / 2, "demo.scrollTo('who-for')"),
    (SEG[6]["start"], "demo.scrollTo('how')"),
    (SEG[7]["start"], "demo.scrollTo('latency')"),
    (SEG[7]["start"] + 0.6 * (SEG[7]["end"] - SEG[7]["start"]), "demo.scrollTo('pilot')"),
]

if RAW.exists():
    shutil.rmtree(RAW)
(RAW / "frames").mkdir(parents=True)

frames = []  # (epoch timestamp, filename)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--use-angle=metal", "--enable-gpu-rasterization", "--hide-scrollbars"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(URL)
    page.wait_for_function("performance.getEntriesByName('gb-first-frame').length > 0 && window.demo", timeout=60000)
    page.wait_for_timeout(2500)  # the rest of the graph has faded in
    page.evaluate("window.scrollTo(0, 0)")
    cdp = ctx.new_cdp_session(page)

    def on_frame(f):
        name = f"{len(frames):06d}.jpg"
        (RAW / "frames" / name).write_bytes(base64.b64decode(f["data"]))
        frames.append((f["metadata"]["timestamp"], name))
        cdp.send("Page.screencastFrameAck", {"sessionId": f["sessionId"]})

    cdp.on("Page.screencastFrame", on_frame)
    cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
    page.wait_for_timeout(500)
    t0 = time.time()
    events, todo, next_sample = [], list(ACTIONS), 0.0
    while True:
        now = time.time() - t0
        if now >= END:
            break
        if todo and now >= todo[0][0]:
            at, js = todo.pop(0)
            page.evaluate(js)
            events.append({"t": round(time.time() - t0, 2), "planned": round(at, 2), "call": js})
            continue
        if now >= next_sample:
            next_sample = now + 0.5
            txt = page.evaluate("document.querySelector('section').innerText.replace(/\\s+/g,' ').match(/(The starting graph|Round \\d added links for: [^.]*|Dead end[^.]*|The missing link[^.]*|The path now reaches[^.]*|Held-out accuracy[^.]*)/g)?.join(' | ')")
            if txt and (not [e for e in events if "text" in e] or [e for e in events if "text" in e][-1]["text"] != txt):
                events.append({"t": round(now, 2), "text": txt})
            continue
        page.wait_for_timeout(20)
    cdp.send("Page.stopScreencast")
    page.wait_for_timeout(200)
    b.close()

(RAW / "events.json").write_text(json.dumps(events, indent=1))

# frame list: the picture at audio time 0 is the last frame at or before t0
keep = [(ts, n) for ts, n in frames if ts >= t0 - 5]
before = [x for x in keep if x[0] <= t0]
keep = ([before[-1]] if before else []) + [x for x in keep if x[0] > t0]
lines = []
for i, (ts, n) in enumerate(keep):
    start = max(ts, t0)
    nxt = keep[i + 1][0] if i + 1 < len(keep) else t0 + END
    lines.append(f"file 'frames/{n}'\nduration {max(0.001, min(nxt, t0 + END) - start):.4f}")
lines.append(f"file 'frames/{keep[-1][1]}'")
(RAW / "frames.txt").write_text("\n".join(lines) + "\n")
span = keep[-1][0] - t0
print(f"{len(keep)} frames kept, {len(keep) / END:.1f} fps average, last frame at {span:.1f}s of {END:.1f}s")
