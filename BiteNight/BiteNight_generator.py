import ctypes
import random
import time
import math
from pathlib import Path

import cv2
import mss
import numpy as np

# ============================================================
# CONFIG
# ============================================================

TEMPLATE_DIR = Path("templates")

WIRE_TEMPLATE = TEMPLATE_DIR / "wire_panel.png"
SWITCH_TEMPLATE = TEMPLATE_DIR / "switch_panel.png"
LAMP_OFF_TEMPLATE = TEMPLATE_DIR / "lamp_off.png"
LAMP_ON_TEMPLATE = TEMPLATE_DIR / "lamp_on.png"
LEVER_TEMPLATE = TEMPLATE_DIR / "lever_panel.png"

MATCH_THRESHOLD = 0.72
DEBUG_SHOW = False

# lever target: "down" or "up"
LEVER_TARGET = "down"

# if true, only click switches whose lamp is off
CLICK_ONLY_OFF_SWITCHES = True

# mouse movement timing
CLICK_DELAY = 0.03
DRAG_STEPS = 28
DRAG_STEP_DELAY = 0.008
POST_ACTION_SLEEP = 0.15

# ============================================================
# WINAPI INPUT
# ============================================================

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

SCREEN_W = user32.GetSystemMetrics(0)
SCREEN_H = user32.GetSystemMetrics(1)


def _to_absolute(x: int, y: int):
    abs_x = int(x * 65535 / max(1, SCREEN_W - 1))
    abs_y = int(y * 65535 / max(1, SCREEN_H - 1))
    return abs_x, abs_y


def move_mouse(x: int, y: int):
    abs_x, abs_y = _to_absolute(x, y)
    user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0)


def left_down():
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)


def left_up():
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def click(x: int, y: int, delay: float = CLICK_DELAY):
    move_mouse(x, y)
    time.sleep(delay)
    left_down()
    time.sleep(delay)
    left_up()


def drag(x1: int, y1: int, x2: int, y2: int, steps: int = DRAG_STEPS, delay: float = DRAG_STEP_DELAY):
    move_mouse(x1, y1)
    time.sleep(0.03)
    left_down()
    for i in range(1, steps + 1):
        xi = int(x1 + (x2 - x1) * i / steps)
        yi = int(y1 + (y2 - y1) * i / steps)
        move_mouse(xi, yi)
        time.sleep(delay)
    left_up()


# ============================================================
# SCREEN / IMAGE HELPERS
# ============================================================

def load_bgr(path: Path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not load image: {path}")
    return img


def grab_screen():
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = np.array(sct.grab(mon))
        frame = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
    return frame


def match_template(screen_bgr, template_bgr, threshold=MATCH_THRESHOLD):
    result = cv2.matchTemplate(screen_bgr, template_bgr, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None, max_val
    th, tw = template_bgr.shape[:2]
    x, y = max_loc
    return (x, y, tw, th), max_val


def crop(img, rect):
    x, y, w, h = rect
    return img[y:y+h, x:x+w]


def show_debug(name, img):
    if DEBUG_SHOW:
        cv2.imshow(name, img)
        cv2.waitKey(1)


# ============================================================
# COLOR DETECTION
# ============================================================

def hsv_mask(img_bgr, lower, upper):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))


COLOR_RANGES = {
    "red1": ([0, 80, 80], [10, 255, 255]),
    "red2": ([170, 80, 80], [179, 255, 255]),
    "green": ([40, 70, 70], [90, 255, 255]),
    "blue": ([95, 90, 70], [135, 255, 255]),
    "purple": ([130, 70, 70], [165, 255, 255]),
}


def color_mask(img_bgr, color_name):
    if color_name == "red":
        m1 = hsv_mask(img_bgr, *COLOR_RANGES["red1"])
        m2 = hsv_mask(img_bgr, *COLOR_RANGES["red2"])
        return cv2.bitwise_or(m1, m2)
    return hsv_mask(img_bgr, *COLOR_RANGES[color_name])


def dominant_color_name(roi_bgr):
    names = ["red", "green", "blue", "purple"]
    best_name = None
    best_score = -1
    for name in names:
        mask = color_mask(roi_bgr, name)
        score = int(cv2.countNonZero(mask))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name, best_score


# ============================================================
# WIRE PANEL SOLVER
# ============================================================

# bigger = faster
SPEED = 20.0

# tiny safety floor so sleeps never become 0
MIN_SLEEP = 0.001


def sp(value):
    return max(MIN_SLEEP, value / SPEED)


def get_wire_positions(board_bgr):
    hsv = cv2.cvtColor(board_bgr, cv2.COLOR_BGR2HSV)

    masks = []
    masks.append(cv2.inRange(hsv, (0, 80, 80), (10, 255, 255)))
    masks.append(cv2.inRange(hsv, (170, 80, 80), (179, 255, 255)))
    masks.append(cv2.inRange(hsv, (40, 70, 70), (90, 255, 255)))
    masks.append(cv2.inRange(hsv, (95, 90, 70), (135, 255, 255)))
    masks.append(cv2.inRange(hsv, (130, 70, 70), (165, 255, 255)))

    mask = masks[0]
    for m in masks[1:]:
        mask = cv2.bitwise_or(mask, m)

    mask = cv2.GaussianBlur(mask, (5, 5), 0)
    _, mask = cv2.threshold(mask, 40, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    points = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 150:
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        cx = x + w // 2
        cy = y + h // 2
        points.append((cx, cy))

    if len(points) < 8:
        raise RuntimeError(f"Expected ~8 wire points, got {len(points)}")

    mid_x = board_bgr.shape[1] // 2

    left = []
    right = []

    for cx, cy in points:
        if cx < mid_x:
            left.append((cx, cy))
        else:
            right.append((cx, cy))

    left.sort(key=lambda p: p[1])
    right.sort(key=lambda p: p[1])

    return left, right


def wiggle_mouse(x, y, radius=4, steps=3):
    for _ in range(steps):
        dx = random.randint(-radius, radius)
        dy = random.randint(-radius, radius)
        move_mouse(x + dx, y + dy)
        time.sleep(sp(0.008))

    move_mouse(x, y)


def move_mouse_line(x1, y1, x2, y2, duration=0.04, step_px=4):
    dx = x2 - x1
    dy = y2 - y1
    distance = math.hypot(dx, dy)

    steps = max(2, int(distance / step_px))
    sleep_time = max(MIN_SLEEP, duration / steps)

    for i in range(1, steps + 1):
        t = i / steps
        x = int(x1 + dx * t)
        y = int(y1 + dy * t)
        move_mouse(x, y)
        time.sleep(sleep_time)


def solve_wires(screen_bgr, wire_rect):
    x, y, w, h = wire_rect
    board = crop(screen_bgr, wire_rect)

    left_points, right_points = get_wire_positions(board)

    print(f"[WIRE] fast sweep... SPEED={SPEED}x")

    for i, (lx, ly) in enumerate(left_points[:4]):
        sx = x + lx
        sy = y + ly

        print(f"[WIRE] sweeping wire {i+1}")

        move_mouse(sx, sy)
        time.sleep(sp(0.02))

        wiggle_mouse(sx, sy, radius=3, steps=2)

        left_down()
        time.sleep(sp(0.015))
        left_up()
        time.sleep(sp(0.02))

        wiggle_mouse(sx, sy, radius=2, steps=2)

        left_down()
        time.sleep(sp(0.25))

        cur_x, cur_y = sx, sy

        for rx, ry in right_points:
            ex = x + rx
            ey = y + ry

            move_mouse_line(cur_x, cur_y, ex, ey, duration=sp(0.035), step_px=5)
            time.sleep(sp(0.005))

            cur_x, cur_y = ex, ey

        left_up()
        time.sleep(sp(0.02))

# ============================================================
# SWITCH PANEL SOLVER
# ============================================================

def get_switch_rows(panel_bgr):
    h, w = panel_bgr.shape[:2]

    row_ys = [
        int(h * 0.145),
        int(h * 0.325),
        int(h * 0.505),
        int(h * 0.685),
        int(h * 0.865),
    ]

    switch_x = int(w * 0.26)
    lamp_x = int(w * 0.79)

    rows = []
    for cy in row_ys:
        rows.append({
            "switch": (switch_x, cy),
            "lamp": (lamp_x, cy),
        })
    return rows


def lamp_is_on(panel_bgr, lamp_center):
    lx, ly = lamp_center

    r = 26
    x1 = max(0, lx - r)
    y1 = max(0, ly - r)
    x2 = min(panel_bgr.shape[1], lx + r)
    y2 = min(panel_bgr.shape[0], ly + r)

    roi = panel_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return False

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    m1 = cv2.inRange(hsv, np.array([0, 100, 120]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 100, 120]), np.array([179, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)

    score = cv2.countNonZero(mask)
    return score > 250


def switch_wiggle_click(x, y):
    # move onto the switch
    move_mouse(x, y)
    time.sleep(0.006)

    # tiny wiggle so hover/register feels more reliable
    move_mouse(x - 2, y - 1)
    time.sleep(0.004)
    move_mouse(x + 2, y + 1)
    time.sleep(0.004)
    move_mouse(x, y)
    time.sleep(0.006)

    # one clean click only
    left_up()
    time.sleep(0.003)

    left_down()
    time.sleep(0.028)
    left_up()

    time.sleep(0.03)


def solve_switches(screen_bgr, switch_rect):
    x, y, w, h = switch_rect

    # single fresh scan
    screen = grab_screen()
    panel = crop(screen, switch_rect)
    rows = get_switch_rows(panel)

    for idx in range(5):
        row = rows[idx]
        on = lamp_is_on(panel, row["lamp"])

        print(f"[SWITCH] row {idx+1}: lamp {'ON' if on else 'OFF'}")

        if not on:
            sx, sy = row["switch"]
            print(f"[SWITCH] clicking row {idx+1}")
            switch_wiggle_click(x + sx, y + sy)

            # brief settle before next row
            time.sleep(0.08)

            # refresh once for the next row only
            screen = grab_screen()
            panel = crop(screen, switch_rect)
            rows = get_switch_rows(panel)

# ============================================================
# LEVER PANEL SOLVER
# ============================================================

def find_red_handle_center(panel_bgr):
    hsv = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2HSV)

    m1 = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 70, 70]), np.array([179, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 300:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        # handle is wide and near lower half
        if w > 60 and h > 12:
            if area > best_area:
                best_area = area
                best = (x + w // 2, y + h // 2, x, y, w, h)

    if best is None:
        raise RuntimeError("Could not find lever handle.")
    return best

def get_lever_green_ratio(panel_bgr):
    h, w = panel_bgr.shape[:2]

    # top progress bar area
    x1 = int(w * 0.20)
    y1 = int(h * 0.11)
    x2 = int(w * 0.80)
    y2 = int(h * 0.19)

    roi = panel_bgr[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # green bar mask
    mask = cv2.inRange(hsv, np.array([40, 70, 70]), np.array([90, 255, 255]))

    green_pixels = cv2.countNonZero(mask)
    total_pixels = roi.shape[0] * roi.shape[1]

    if total_pixels == 0:
        return 0.0

    return green_pixels / total_pixels

def grab_lever_with_wiggle(start_x, start_y, lever_rect, attempts=4):
    x, y, w, h = lever_rect

    for attempt in range(attempts):
        print(f"[LEVER] grab attempt {attempt+1}")

        # clean state
        left_up()
        time.sleep(0.01)

        # move to center
        move_mouse(start_x, start_y)
        time.sleep(0.015)

        # small wiggle around handle
        offsets = [
            (0, 0),
            (-4, -2),
            (4, -2),
            (-3, 2),
            (3, 2),
            (0, 0),
        ]

        for ox, oy in offsets:
            move_mouse(start_x + ox, start_y + oy)
            time.sleep(0.008)

        # hold on the center
        move_mouse(start_x, start_y)
        time.sleep(0.01)

        left_down()
        time.sleep(0.06)

        # tiny downward tug just to latch onto it better
        test_y = y + int(h * 0.78)
        move_mouse_line(start_x, start_y, start_x, test_y, duration=0.02, step_px=5)
        time.sleep(0.015)

        # do NOT judge success by bar ratio here
        # if the handle was visually being held, assume success
        return True

    return False

def pull_lever(screen_bgr, lever_rect, target="down"):
    x, y, w, h = lever_rect

    # find handle once at the start
    screen = grab_screen()
    panel = crop(screen, lever_rect)
    cx, cy, bx, by, bw, bh = find_red_handle_center(panel)

    start_x = x + cx
    start_y = y + cy

    top_y = y + int(h * 0.46)
    bottom_y = y + int(h * 0.99)

    done_ratio = 0.88
    max_pumps = 11

    print("[LEVER] hold and pump...")

    grabbed = grab_lever_with_wiggle(start_x, start_y, lever_rect, attempts=4)
    if not grabbed:
        raise RuntimeError("Failed to grab lever reliably")

    best_ratio = 0.0
    no_progress_pumps = 0

    for i in range(max_pumps):
        # keep holding entire time
        move_mouse_line(start_x, start_y, start_x, bottom_y, duration=0.018, step_px=6)
        time.sleep(0.005)

        move_mouse_line(start_x, bottom_y, start_x, top_y, duration=0.018, step_px=6)
        time.sleep(0.005)

        screen = grab_screen()
        panel = crop(screen, lever_rect)
        ratio = get_lever_green_ratio(panel)

        print(f"[LEVER] pump {i+1}, green ratio={ratio:.3f}, best={best_ratio:.3f}")

        if ratio > best_ratio + 0.003:
            best_ratio = ratio
            no_progress_pumps = 0
        else:
            no_progress_pumps += 1

        if ratio >= done_ratio:
            print("[LEVER] bar full enough, done")
            break

        # only suspect lost grab after several pumps with zero progress
        if i >= 5 and best_ratio < 0.02 and no_progress_pumps >= 6:
            print("[LEVER] no progress, trying re-grab")
            left_up()
            time.sleep(0.03)

            screen = grab_screen()
            panel = crop(screen, lever_rect)
            cx, cy, bx, by, bw, bh = find_red_handle_center(panel)
            start_x = x + cx
            start_y = y + cy

            grabbed = grab_lever_with_wiggle(start_x, start_y, lever_rect, attempts=3)
            if not grabbed:
                raise RuntimeError("Lost lever grab and could not re-grab")

            no_progress_pumps = 0

    left_up()
    time.sleep(0.03)

# ============================================================
# MAIN
# ============================================================

def run_cycle():
    print("Loading templates...")
    wire_template = load_bgr(WIRE_TEMPLATE)
    switch_template = load_bgr(SWITCH_TEMPLATE)
    lever_template = load_bgr(LEVER_TEMPLATE)

    print("Capturing screen for wires...")
    screen = grab_screen()

    print("Finding wire panel...")
    wire_rect, wire_score = match_template(screen, wire_template, threshold=0.68)
    if not wire_rect:
        raise RuntimeError(f"Wire panel not found. score={wire_score:.3f}")
    print(f"Wire panel found: {wire_rect}, score={wire_score:.3f}")

    solve_wires(screen, wire_rect)

    print("Waiting for switch panel...")
    time.sleep(0.3)

    screen = grab_screen()
    switch_rect, switch_score = match_template(screen, switch_template, threshold=0.20)
    if not switch_rect:
        raise RuntimeError(f"Switch panel not found. score={switch_score:.3f}")
    print(f"Switch panel found: {switch_rect}, score={switch_score:.3f}")

    solve_switches(screen, switch_rect)

    print("Waiting for lever...")
    time.sleep(0.3)

    screen = grab_screen()
    lever_rect, lever_score = match_template(screen, lever_template, threshold=0.45)
    if not lever_rect:
        raise RuntimeError(f"Lever panel not found. score={lever_score:.3f}")
    print(f"Lever panel found: {lever_rect}, score={lever_score:.3f}")

    pull_lever(screen, lever_rect, target=LEVER_TARGET)

    print("[CYCLE DONE]")

def main():
    cycles = 4

    for i in range(cycles):
        print(f"\n========== CYCLE {i+1}/{cycles} ==========")

        try:
            run_cycle()
        except Exception as e:
            print(f"[ERROR] cycle {i+1} failed: {e}")

        # wait for game to reset
        print("Waiting for reset...")
        time.sleep(0.1)

    print("All cycles done.")

if __name__ == "__main__":
    main()