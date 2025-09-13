# pip install mss numpy opencv-python pywin32
import time
import numpy as np
from mss import mss
import cv2
import sys, os
def resource_path(filename):
    """Get absolute path to resource, works for dev and for PyInstaller exe"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.abspath(filename)
import win32api, win32con
import keyboard

# ── your templates (unchanged) ────────────────────────────────────────────────
TEMPLATES = [
    ("template1.png", (0, 5)),
    ("template2.png", (0, 5)),
    ("template3.png", (0, 5)),
    ("template4.png", (0, 5)),
    ("template5.png", (0, 5)),
    ("template6.png", (0, 5)),
    ("template7.png", (0, 5)),
    ("template8.png", (0, 5)),
    ("template9.png", (0, 5)),
    ("template10.png", (0, 5)),
    ("template11.png", (0, 5)),
    ("template12.png", (0, 5)),
    ("template13.png", (0, 5)),
    ("template14.png", (0, 5)),
    ("template15.png", (0, 5)),
]

THRESH       = 0.80            # template match threshold
SCALE        = 0.50            # process at 50% size for speed
FPS_TARGET   = 35              # detector loop target fps
WIGGLE       = 2               # tiny move to wake hover
HOVER_DELAY  = 0.03            # short pause before click
COOLDOWN_S   = 0.25            # don't click the same template too fast
TEMPLATES_PER_TICK = 4         # round-robin: how many templates to check each frame

sct = mss()
monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

# center region (50% of screen) — tweak or set to full monitor to scan all
region = {
    "left":   monitor["left"] + int(monitor["width"]  * 0.15),   # 15% margin left
    "top":    monitor["top"]  + int(monitor["height"] * 0.15),   # 15% margin top
    "width":  int(monitor["width"]  * 0.70),                     # 70% width
    "height": int(monitor["height"] * 0.70),                     # 70% height
}

print("Scanning region:", region)
print("Press F6 to toggle scanning, F7 to quit")
# ── load + pre-scale templates once ───────────────────────────────────────────
loaded_templates = []
for path, offset in TEMPLATES:
    img = cv2.imread(resource_path(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Template file not found: {path}")
    # template at native and scaled sizes
    t_native = img
    t_small  = cv2.resize(img, (0, 0), fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    tw_s, th_s = t_small.shape[::-1]
    loaded_templates.append({
        "path": path,
        "offset": offset,
        "tmpl_small": t_small,
        "tw_s": tw_s, "th_s": th_s,
        "last_click_ts": 0.0
    })
    #print(f"Loaded {path} (scaled: {tw_s}x{th_s})")
# ── fast low-level click with tiny wiggle ─────────────────────────────────────
def lowlevel_hover_click(x, y, offset=(0, 0), jiggle=WIGGLE, hover_delay=HOVER_DELAY):
    tx, ty = x + offset[0], y + offset[1]
    win32api.SetCursorPos((int(tx), int(ty)))
    # send tiny MOVE events to trigger hover
    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, jiggle, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, -jiggle, 0, 0, 0)
    time.sleep(hover_delay)
    # reliable click
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.008)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

# ── round-robin index ─────────────────────────────────────────────────────────
idx = 0
frame_interval = 1.0 / FPS_TARGET
scanning = True   # start enabled

while True:
    # --- hotkeys ---
    if keyboard.is_pressed("f6"):
        scanning = not scanning
        print("Scanning:", scanning)
        time.sleep(0.5)  # debounce so it doesn’t flip multiple times

    if keyboard.is_pressed("f7"):
        print("Exiting...")
        close_console()
        sys.exit()

    if scanning:
        t0 = time.perf_counter()

        # capture region and downscale once
        frame_bgra = np.array(sct.grab(region))
        gray = cv2.cvtColor(frame_bgra, cv2.COLOR_BGR2GRAY)
        gray_small = cv2.resize(gray, (0, 0), fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)

        # choose a slice of templates this tick
        end = min(idx + TEMPLATES_PER_TICK, len(loaded_templates))
        subset = loaded_templates[idx:end]
        if end - idx < TEMPLATES_PER_TICK:  # wrap
            subset += loaded_templates[:TEMPLATES_PER_TICK - (end - idx)]
        idx = (idx + TEMPLATES_PER_TICK) % len(loaded_templates)

        now = time.perf_counter()
        clicked_this_frame = False

        for entry in subset:
            # simple debounce per template
            if now - entry["last_click_ts"] < COOLDOWN_S:
                continue

            tmpl = entry["tmpl_small"]
            res = cv2.matchTemplate(gray_small, tmpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= THRESH)

            # click first hit only (faster; avoids duplicate hits)
            for x_s, y_s in zip(xs, ys):
                # map small-scale coords back to screen
                cx = region["left"] + int((x_s + entry["tw_s"] // 2) / SCALE)
                cy = region["top"]  + int((y_s + entry["th_s"] // 2) / SCALE)
                print(f"[{entry['path']}] match at ({cx},{cy}) → click")
                lowlevel_hover_click(cx, cy, offset=entry["offset"])
                entry["last_click_ts"] = time.perf_counter()
                clicked_this_frame = True
                break  # one click per template per frame

            if clicked_this_frame:
                break  # stop after first successful click

        # pace the loop to target fps
        elapsed = time.perf_counter() - t0
        sleep_for = frame_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

