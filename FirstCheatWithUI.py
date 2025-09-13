# Combined Overlay Assistant (UI + first-run terms + visual detector)
# Safe-by-default: logs matches; real clicking is OFF unless explicitly enabled in Settings.
# Dependencies (Windows): pip install mss numpy opencv-python pywin32
# Cross-platform note: clicking uses win32 API; on non-Windows, only detection/logging runs.

import json
import sys
import time
from pathlib import Path
import threading
import traceback

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import scrolledtext

# ---- Optional libs (guarded imports) ----
missing = []
try:
    import numpy as np
except Exception:
    np = None; missing.append("numpy")
try:
    from mss import mss
except Exception:
    mss = None; missing.append("mss")
try:
    import cv2
except Exception:
    cv2 = None; missing.append("opencv-python")
try:
    import win32api, win32con
    WINDOWS = True
except Exception:
    WINDOWS = False

APP_NAME = "Overlay Assistant"
CONFIG_DIR = Path.home() / ".overlay_assistant"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "accepted_terms": False,
    "settings": {
        "hotkey": "F6",
        "overlay_opacity": 85,  # 0–100 (placeholder for your real overlay)
        "autostart": False,
        "simulate_only": True,      # Default: do NOT click; just log
        "allow_real_clicks": False, # Extra guard; must be True to actually click
        "template_folder": "",      # Folder where template images live
        "scan_fraction": 0.70,      # Fraction of screen area to scan (center crop)
        "threshold": 0.80,
        "scale": 0.50,
        "fps_target": 20,
        "templates_per_tick": 4,
        "wiggle": 2,
        "hover_delay": 0.03,
        "cooldown_s": 0.25
    }
}

HELP_TEXT = (
    "This app demonstrates a first‑run Terms dialog, a Tkinter UI, and a visual template "
    "detector that logs matches on your screen. It is provided for educational and accessibility "
    "use cases only. Do not use it to violate any platform/game Terms of Service.\n\n"
    "• Dashboard: Start/Stop the worker; see log output\n"
    "• Settings: Configure detection parameters and template folder\n"
    "• About: Basic info and config path\n\n"
    "Safe default: The app starts in 'Simulate only' mode (logging without clicking)."
)

def resource_path(filename):
    "Get absolute path to resource, works for dev and PyInstaller."
    if hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / filename)
    return str(Path(filename).resolve())

class FirstRunDialog(tk.Toplevel):
    def __init__(self, parent, on_accept):
        super().__init__(parent)
        self.parent = parent
        self.on_accept = on_accept
        self.title("Terms of Use")
        self.geometry("640x400")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.transient(parent)
        self.grab_set()

        wrapper = ttk.Frame(self, padding=16)
        wrapper.pack(fill="both", expand=True)

        heading = ttk.Label(wrapper, text="Read before continuing", font=("", 14, "bold"))
        heading.pack(anchor="w", pady=(0, 8))

        terms = (
            "By using this software, you agree to the following:\\n\\n"
            "1) You use it at your own risk.\\n"
            "2) The author is not responsible for crashes, bans, or data loss.\\n"
            "3) No refunds or chargebacks.\\n"
            "4) By clicking “Accept”, you take full responsibility for your use.\\n\\n"
            "Only use this tool in lawful, authorized contexts. Do not violate any platform's ToS."
        )
        text = tk.Text(wrapper, wrap="word", height=12)
        text.insert("1.0", terms)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

        self.var_ack = tk.BooleanVar(value=False)
        ack = ttk.Checkbutton(
            wrapper,
            text="I have read and accept the terms of use.",
            variable=self.var_ack,
            command=self._toggle_accept
        )
        ack.pack(anchor="w", pady=(10, 6))

        btns = ttk.Frame(wrapper)
        btns.pack(anchor="e", pady=(8, 0))

        self.btn_accept = ttk.Button(btns, text="Accept", command=self._accept, state="disabled")
        self.btn_accept.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Decline", command=self._decline).grid(row=0, column=1)

    def _toggle_accept(self):
        self.btn_accept.config(state="normal" if self.var_ack.get() else "disabled")

    def _accept(self):
        self.grab_release()
        self.destroy()
        self.on_accept()

    def _decline(self):
        messagebox.showinfo("Exit", "You must accept the terms to use this software.")
        self._on_close()

    def _on_close(self):
        self.grab_release()
        self.destroy()
        self.parent.destroy()
        sys.exit(0)


class DetectorWorker:
    "Runs in a thread; does screen capture + template matching; posts logs/callbacks."
    def __init__(self, settings, log_func, status_func):
        self.settings = settings
        self.log = log_func
        self.set_status = status_func
        self._stop_evt = threading.Event()
        self._thread = None
        self._loaded_templates = []
        self._idx = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_evt.set()

    def _prepare_templates(self, folder):
        self._loaded_templates.clear()
        if not folder:
            self.log("No template folder set. Go to Settings to choose one.")
            return
        p = Path(folder)
        if not p.exists():
            self.log(f"Template folder not found: {folder}")
            return
        # Any .png/.jpg in the folder
        files = sorted([*p.glob("*.png"), *p.glob("*.jpg"), *p.glob("*.jpeg")])
        if not files:
            self.log("No template images found in folder.")
            return

        SCALE = float(self.settings.get("scale", 0.5))
        for f in files:
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is None:
                self.log(f"Failed to load: {f.name}")
                continue
            t_small = cv2.resize(img, (0, 0), fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
            tw_s, th_s = t_small.shape[::-1]
            self._loaded_templates.append({
                "name": f.name,
                "tmpl_small": t_small,
                "tw_s": tw_s, "th_s": th_s,
                "last_click_ts": 0.0
            })
        self.log(f"Loaded {len(self._loaded_templates)} templates.")

    def _run(self):
        # Check dependencies
        if any(lib is None for lib in (np, mss, cv2)):
            self.log("Missing dependencies: " + ", ".join(missing))
            return

        try:
            self._prepare_templates(self.settings.get("template_folder", ""))

            sct = mss()
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

            frac = float(self.settings.get("scan_fraction", 0.70))
            frac = max(0.1, min(frac, 1.0))
            region = {
                "left":   monitor["left"] + int(monitor["width"]  * (0.5 - frac/2)),
                "top":    monitor["top"]  + int(monitor["height"] * (0.5 - frac/2)),
                "width":  int(monitor["width"]  * frac),
                "height": int(monitor["height"] * frac),
            }
            self.log(f"Scanning region: {region}")

            THRESH = float(self.settings.get("threshold", 0.80))
            SCALE = float(self.settings.get("scale", 0.50))
            FPS_TARGET = int(self.settings.get("fps_target", 20))
            TEMPLATES_PER_TICK = int(self.settings.get("templates_per_tick", 4))
            WIGGLE = int(self.settings.get("wiggle", 2))
            HOVER_DELAY = float(self.settings.get("hover_delay", 0.03))
            COOLDOWN_S = float(self.settings.get("cooldown_s", 0.25))

            simulate_only = bool(self.settings.get("simulate_only", True))
            allow_real = bool(self.settings.get("allow_real_clicks", False))

            frame_interval = 1.0 / max(1, FPS_TARGET)
            clicked_this_frame = False

            while not self._stop_evt.is_set():
                t0 = time.perf_counter()
                frame_bgra = np.array(sct.grab(region))
                gray = cv2.cvtColor(frame_bgra, cv2.COLOR_BGR2GRAY)
                gray_small = cv2.resize(gray, (0, 0), fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)

                # Choose subset round-robin
                if not self._loaded_templates:
                    # Sleep a bit more if nothing loaded
                    time.sleep(0.3)
                    continue

                end = min(self._idx + TEMPLATES_PER_TICK, len(self._loaded_templates))
                subset = self._loaded_templates[self._idx:end]
                if end - self._idx < TEMPLATES_PER_TICK:  # wrap
                    subset += self._loaded_templates[:TEMPLATES_PER_TICK - (end - self._idx)]
                self._idx = (self._idx + TEMPLATES_PER_TICK) % len(self._loaded_templates)

                now = time.perf_counter()
                clicked_this_frame = False

                for entry in subset:
                    if now - entry["last_click_ts"] < COOLDOWN_S:
                        continue

                    tmpl = entry["tmpl_small"]
                    res = cv2.matchTemplate(gray_small, tmpl, cv2.TM_CCOEFF_NORMED)
                    ys, xs = np.where(res >= THRESH)

                    for x_s, y_s in zip(xs, ys):
                        cx = region["left"] + int((x_s + entry["tw_s"] // 2) / SCALE)
                        cy = region["top"]  + int((y_s + entry["th_s"] // 2) / SCALE)
                        self.log(f"[{entry['name']}] match at ({cx},{cy})")
                        entry["last_click_ts"] = time.perf_counter()

                        if not simulate_only and allow_real and WINDOWS:
                            try:
                                # tiny wiggle to ensure hover, then click
                                win32api.SetCursorPos((int(cx), int(cy)))
                                win32api.mouse_event(0x0001, int(self.settings.get("wiggle",2)), 0, 0, 0)
                                win32api.mouse_event(0x0001, -int(self.settings.get("wiggle",2)), 0, 0, 0)
                                time.sleep(HOVER_DELAY)
                                win32api.mouse_event(0x0002, 0, 0, 0, 0)  # left down
                                time.sleep(0.008)
                                win32api.mouse_event(0x0004, 0, 0, 0, 0)  # left up
                                self.log("→ clicked")
                            except Exception as e:
                                self.log(f"Click failed: {e}")
                        elif not WINDOWS and not simulate_only and allow_real:
                            self.log("Real clicking not supported on this OS.")
                        clicked_this_frame = True
                        break  # one hit per template per frame

                    if clicked_this_frame:
                        break

                elapsed = time.perf_counter() - t0
                sleep_for = frame_interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)

        except Exception as e:
            self.log("Worker crashed: " + str(e))
            self.log(traceback.format_exc())
        finally:
            self.set_status("Stopped")

class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.running = False
        self.config_data = self._load_config()

        root.title(APP_NAME)
        root.geometry("900x620")
        root.minsize(760, 520)

        self._init_style()
        self._build_menu()
        self._build_ui()

        # First-run gate
        if not self.config_data.get("accepted_terms", False):
            self.root.after(50, self._show_first_run)

        # Autostart if accepted + enabled
        if self.config_data.get("accepted_terms") and self.config_data["settings"].get("autostart"):
            self._start()

    # ---------- UI ----------
    def _init_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Settings", command=self._save_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about_popup)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)

        # Tabs
        self.tab_dashboard = ttk.Frame(self.notebook, padding=12)
        self.tab_settings = ttk.Frame(self.notebook, padding=12)
        self.tab_about = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_dashboard, text="Dashboard")
        self.notebook.add(self.tab_settings, text="Settings")
        self.notebook.add(self.tab_about, text="About")

        self._build_dashboard()
        self._build_settings()
        self._build_about()

    def _build_dashboard(self):
        top = ttk.Frame(self.tab_dashboard)
        top.pack(fill="x", pady=(0, 10))

        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(top, textvariable=self.status_var, font=("", 12, "bold")).pack(side="left")

        ttk.Label(top, text="•").pack(side="left", padx=6)
        self.time_var = tk.StringVar(value="Uptime: 00:00:00")
        ttk.Label(top, textvariable=self.time_var).pack(side="left")

        btns = ttk.Frame(self.tab_dashboard)
        btns.pack(fill="x", pady=(0, 8))
        self.btn_start = ttk.Button(btns, text="Start", command=self._start)
        self.btn_stop = ttk.Button(btns, text="Stop", command=self._stop, state="disabled")
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop.pack(side="left")

        # Log
        ttk.Label(self.tab_dashboard, text="Log:").pack(anchor="w", pady=(12, 4))
        self.log = scrolledtext.ScrolledText(self.tab_dashboard, height=18, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

    def _build_settings(self):
        s = self.config_data["settings"]
        grid = ttk.Frame(self.tab_settings)
        grid.pack(fill="x", pady=(0, 12))

        # Template folder picker
        ttk.Label(grid, text="Template folder:").grid(row=0, column=0, sticky="w")
        self.var_folder = tk.StringVar(value=s.get("template_folder", ""))
        entry = ttk.Entry(grid, textvariable=self.var_folder, width=48)
        entry.grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Button(grid, text="Browse…", command=self._browse_folder).grid(row=0, column=2, padx=4)

        ttk.Label(grid, text="Threshold:").grid(row=1, column=0, sticky="w")
        self.var_thresh = tk.DoubleVar(value=float(s.get("threshold", 0.80)))
        ttk.Scale(grid, from_=0.5, to=0.99, variable=self.var_thresh, orient="horizontal", length=200).grid(
            row=1, column=1, sticky="w", padx=8, pady=4
        )

        ttk.Label(grid, text="Scale:").grid(row=2, column=0, sticky="w")
        self.var_scale = tk.DoubleVar(value=float(s.get("scale", 0.50)))
        ttk.Scale(grid, from_=0.25, to=1.0, variable=self.var_scale, orient="horizontal", length=200).grid(
            row=2, column=1, sticky="w", padx=8, pady=4
        )

        ttk.Label(grid, text="FPS target:").grid(row=3, column=0, sticky="w")
        self.var_fps = tk.IntVar(value=int(s.get("fps_target", 20)))
        ttk.Spinbox(grid, from_=5, to=60, textvariable=self.var_fps, width=6).grid(
            row=3, column=1, sticky="w", padx=8, pady=4
        )

        ttk.Label(grid, text="Templates / tick:").grid(row=4, column=0, sticky="w")
        self.var_tpt = tk.IntVar(value=int(s.get("templates_per_tick", 4)))
        ttk.Spinbox(grid, from_=1, to=20, textvariable=self.var_tpt, width=6).grid(
            row=4, column=1, sticky="w", padx=8, pady=4
        )

        ttk.Label(grid, text="Scan area (center fraction):").grid(row=5, column=0, sticky="w")
        self.var_frac = tk.DoubleVar(value=float(s.get("scan_fraction", 0.70)))
        ttk.Scale(grid, from_=0.1, to=1.0, variable=self.var_frac, orient="horizontal", length=200).grid(
            row=5, column=1, sticky="w", padx=8, pady=4
        )

        # Safety toggles
        self.var_sim = tk.BooleanVar(value=bool(s.get("simulate_only", True)))
        ttk.Checkbutton(grid, text="Simulate only (no clicking)", variable=self.var_sim).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=6
        )
        self.var_allow = tk.BooleanVar(value=bool(s.get("allow_real_clicks", False)))
        ttk.Checkbutton(grid, text="Allow real clicks (Windows only)", variable=self.var_allow).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=0
        )

        # Save button
        ttk.Button(self.tab_settings, text="Save Settings", command=self._save_settings).pack(anchor="w", pady=(8,0))

        ttk.Separator(self.tab_settings, orient="horizontal").pack(fill="x", pady=12)
        ttk.Label(self.tab_settings, text=HELP_TEXT, foreground="#555", wraplength=680, justify="left").pack(anchor="w")

    def _build_about(self):
        ttk.Label(self.tab_about, text=APP_NAME, font=("", 16, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(self.tab_about, text="First-run terms + Tkinter UI + visual detection (safe-by-default).").pack(anchor="w")
        ttk.Label(self.tab_about, text="• Dashboard: Start/Stop + status and logs\n• Settings: configure detector & safety", justify="left").pack(anchor="w", pady=(6,0))
        ttk.Label(self.tab_about, text="Config path:", font=("", 10, "bold")).pack(anchor="w", pady=(12, 0))
        ttk.Label(self.tab_about, text=str(CONFIG_FILE), foreground="#555").pack(anchor="w")

    # ---------- Logic ----------
    def _show_first_run(self):
        def accepted():
            self.config_data["accepted_terms"] = True
            self._save_config()
            self._log("Terms accepted.")
        FirstRunDialog(self.root, on_accept=accepted)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select template folder")
        if folder:
            self.var_folder.set(folder)

    def _start(self):
        if self.running:
            return
        # Dependency check
        if missing:
            messagebox.showerror("Missing dependencies", "Install: " + ", ".join(missing))
            return

        self.running = True
        self.start_time = time.time()
        self._set_status("Running")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._log("Service started.")

        # Build settings snapshot
        s = self.config_data["settings"]
        s["template_folder"]  = self.var_folder.get()
        s["threshold"]        = float(self.var_thresh.get())
        s["scale"]            = float(self.var_scale.get())
        s["fps_target"]       = int(self.var_fps.get())
        s["templates_per_tick"]= int(self.var_tpt.get())
        s["scan_fraction"]    = float(self.var_frac.get())
        s["simulate_only"]    = bool(self.var_sim.get())
        s["allow_real_clicks"]= bool(self.var_allow.get())

        # Launch worker
        self.worker = DetectorWorker(s, self._log, self._set_status)
        self.worker.start()
        self._tick_uptime()

    def _stop(self):
        if not self.running:
            return
        self.running = False
        try:
            if hasattr(self, "worker"):
                self.worker.stop()
        except Exception:
            pass
        self._set_status("Stopped")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._log("Service stopped.")

    def _tick_uptime(self):
        if not self.running:
            return
        elapsed = int(time.time() - self.start_time)
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        self.time_var.set(f"Uptime: {hh:02d}:{mm:02d}:{ss:02d}")
        self.root.after(1000, self._tick_uptime)

    def _set_status(self, text):
        self.status_var.set(text)

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------- Config ----------
    def _load_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            self._write_config(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            messagebox.showwarning("Config", "Config file was corrupted. Restoring defaults.")
            data = json.loads(json.dumps(DEFAULT_CONFIG))
            self._write_config(data)
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update({k: v for k, v in data.items() if k in merged})
        if "settings" in data:
            merged["settings"].update(data["settings"])
        return merged

    def _save_config(self):
        self._write_config(self.config_data)

    def _write_config(self, data):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Config", f"Failed to save config:\\n{e}")

    def _save_settings(self):
        self.config_data["settings"]["template_folder"]   = self.var_folder.get().strip()
        self.config_data["settings"]["threshold"]         = float(self.var_thresh.get())
        self.config_data["settings"]["scale"]             = float(self.var_scale.get())
        self.config_data["settings"]["fps_target"]        = int(self.var_fps.get())
        self.config_data["settings"]["templates_per_tick"]= int(self.var_tpt.get())
        self.config_data["settings"]["scan_fraction"]     = float(self.var_frac.get())
        self.config_data["settings"]["simulate_only"]     = bool(self.var_sim.get())
        self.config_data["settings"]["allow_real_clicks"] = bool(self.var_allow.get())
        self._save_config()
        self._log("Settings saved.")

    def _show_about_popup(self):
        message = (
            f"{APP_NAME}\\n\\n"
            "Sample interface with first-run terms, tabs, persistent settings, and a safe-by-default detector."
        )
        messagebox.showinfo("About", message)


def main():
    root = tk.Tk()
    # HiDPI scaling hint (especially on Windows); harmless elsewhere
    try:
        if sys.platform.startswith("win"):
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App(root)
    app.pack(fill="both", expand=True)
    root.mainloop()

if __name__ == "__main__":
    main()
