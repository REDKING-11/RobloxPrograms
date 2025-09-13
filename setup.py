import sys
from cx_Freeze import setup, Executable

executables = [Executable("Cheat.py", base="Win32GUI")]

setup(
    name="ForsakenAutoClicker",
    version="1.0.0",
    description="Template-matching autoclicker for Roblox Forsaken popups",
    options={
        "build_exe": {
            "packages": ["cv2", "numpy", "mss", "win32api", "win32con"],
            "include_files": [
                "template1.png", "template2.png", "template3.png",
                "template4.png", "template5.png", "template6.png",
                "template7.png", "template8.png", "template9.png",
                "template10.png"
            ],
        }
    },
    executables=executables,
)
