import time
import threading
from pathlib import Path
import ctypes
from ctypes import wintypes

import cv2
import numpy as np
import mss

# ----------------------------
# CONFIG: screen region to scan (ROI)
# ----------------------------
ROI = {
    "left": 1237,  # x
    "top": 1198,    # y
    "width": 85,
    "height": 85,
}

LOOP_DELAY = 0.03
KEY_COOLDOWN = 0.15
PRESS_DURATION = 0.02

MATCH_THRESHOLD = 0.75
SCALE_STEPS = [1.0]

# ----------------------------
# STOP CONTROL: type "end" in console
# ----------------------------
stop_event = threading.Event()

def console_listener() -> None:
    print("Type 'end' and press Enter to stop the script.")
    while not stop_event.is_set():
        try:
            cmd = input().strip().lower()
            if cmd == "end":
                stop_event.set()
                print("Stopping...")
                break
        except EOFError:
            stop_event.set()
            break

# ----------------------------
# Windows SendInput (scan codes)
# ----------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

# Scan codes for WASD
SCANCODES = {
    "W": 0x11,
    "A": 0x1E,
    "S": 0x1F,
    "D": 0x20,
}

# ctypes.wintypes may not expose ULONG_PTR on all Python builds, so define it safely:
ULONG_PTR = wintypes.WPARAM  # pointer-sized integer on Windows


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def _send_input(inp: INPUT) -> None:
    n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if n != 1:
        err = ctypes.get_last_error()
        print(f"SendInput failed (sent={n}) GetLastError={err}")


def press_scancode(scan_code: int, hold_time: float = 0.02) -> None:
    down = INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=KEYEVENTF_SCANCODE,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )

    up = INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )

    _send_input(down)
    time.sleep(hold_time)
    _send_input(up)

# ----------------------------
# Load templates (from same folder as this .py file)
# ----------------------------
def load_templates(folder: Path) -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    for key in ["W", "A", "S", "D"]:
        candidates = sorted(folder.glob(f"{key}*.png")) + sorted(folder.glob(f"{key.lower()}*.png"))
        if not candidates:
            continue

        img = cv2.imread(str(candidates[0]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue

        img = cv2.GaussianBlur(img, (3, 3), 0)
        templates[key] = img

    if len(templates) != 4:
        missing = [k for k in ["W", "A", "S", "D"] if k not in templates]
        raise FileNotFoundError(
            f"Missing templates for: {missing}\n"
            f"Put 4 PNGs next to this script starting with W, A, S, D (e.g., W.png, A.png, S.png, D.png)."
        )

    return templates

# ----------------------------
# Template matching
# ----------------------------
def match_best(
    gray_roi: np.ndarray,
    templates: dict[str, np.ndarray],
) -> tuple[str | None, float, tuple[int, int, int, int] | None]:
    best_key: str | None = None
    best_score: float = -1.0
    best_rect: tuple[int, int, int, int] | None = None

    roi_blur = cv2.GaussianBlur(gray_roi, (3, 3), 0)

    for key, tmpl in templates.items():
        for scale in SCALE_STEPS:
            if scale != 1.0:
                th, tw = tmpl.shape[:2]
                new_w = max(8, int(tw * scale))
                new_h = max(8, int(th * scale))
                tmpl_use = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            else:
                tmpl_use = tmpl

            if tmpl_use.shape[0] >= roi_blur.shape[0] or tmpl_use.shape[1] >= roi_blur.shape[1]:
                continue

            res = cv2.matchTemplate(roi_blur, tmpl_use, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_score:
                best_score = float(max_val)
                best_key = key
                x, y = max_loc
                h, w = tmpl_use.shape[:2]
                best_rect = (x, y, w, h)

    if best_score < MATCH_THRESHOLD:
        return None, best_score, None

    return best_key, best_score, best_rect

# ----------------------------
# Main loop
# ----------------------------
def main() -> None:
    script_dir = Path(__file__).resolve().parent
    templates = load_templates(script_dir)
    print("Loaded templates from:", script_dir)

    last_press_time = 0.0
    last_key: str | None = None

    with mss.mss() as sct:
        while not stop_event.is_set():
            frame = np.array(sct.grab(ROI))  # BGRA
            bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

            key, score, rect = match_best(gray, templates)

            now = time.time()
            if key and (now - last_press_time) >= KEY_COOLDOWN:
                print(f"PRESSING {key}  score={score:.2f}")
                press_scancode(SCANCODES[key], PRESS_DURATION)
                last_press_time = now
                last_key = key

            overlay = bgr.copy()
            h, w = overlay.shape[:2]

            cv2.rectangle(overlay, (0, 0), (w - 1, h - 1), (0, 255, 0), 2)

            if rect is not None:
                x, y, rw, rh = rect
                cv2.rectangle(overlay, (x, y), (x + rw, y + rh), (0, 255, 255), 2)

            label = f"Detected: {key if key else '-'} (score {score:.2f}) | Last pressed: {last_key if last_key else '-'}"
            cv2.putText(overlay, label, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("WASD template detector (ROI preview)", overlay)
            cv2.waitKey(1)

            time.sleep(LOOP_DELAY)

    cv2.destroyAllWindows()

if __name__ == "__main__":
    listener = threading.Thread(target=console_listener, daemon=True)
    listener.start()
    main()
