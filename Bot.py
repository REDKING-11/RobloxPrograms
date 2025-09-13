# pip install mss pyautogui numpy opencv-python
import time
import numpy as np
from mss import mss
import mouse
import cv2

# List of template image files
TEMPLATES = [
    ("template1.png", (0, 5)),   # (file, (x,y) offset)
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

THRESH = 0.85   # confidence threshold

sct = mss()
monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

# Load templates into memory
loaded_templates = []
for path, offset in TEMPLATES:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Template file not found: {path}")
    tw, th = img.shape[::-1]
    loaded_templates.append((img, tw, th, offset))
    print(f"Loaded {path} ({tw}x{th}) with offset {offset}")

print("Scanning full screen:", monitor)

# Define region (center 50% of screen)
region = {
    "left": monitor["left"] + monitor["width"]//4,
    "top":  monitor["top"]  + monitor["height"]//5,
    "width": monitor["width"]//2,
    "height": monitor["height"]//1
}

while True:
    frame = np.array(sct.grab(region))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    for tmpl, tw, th, offset in loaded_templates:
        res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= THRESH)

        for x, y in zip(xs, ys):
            cx = region["left"] + x + tw // 2 + offset[0]
            cy = region["top"]  + y + th // 2 + offset[1]
            print(f"Match for template at ({cx},{cy}) → click")

            # move + click with `mouse`
            mouse.move(cx, cy, absolute=True, duration=0)  # instant move
            mouse.click("left")
    time.sleep(0.01)  # loop delay


    time.sleep(0.01)  # loop delay
