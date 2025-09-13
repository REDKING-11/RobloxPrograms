import json
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import scrolledtext

APP_NAME = "Overlay Assistant"
CONFIG_DIR = Path.home() / ".overlay_assistant"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "accepted_terms": False,
    "settings": {
        "hotkey": "F6",
        "overlay_opacity": 85,  # 0–100
        "autostart": False
    }
}

class FirstRunDialog(tk.Toplevel):
    def __init__(self, parent, on_accept):
        super().__init__(parent)
        self.parent = parent
        self.on_accept = on_accept
        self.title("Terms of Use")
        self.geometry("640x380")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Make modal
        self.transient(parent)
        self.grab_set()

        wrapper = ttk.Frame(self, padding=16)
        wrapper.pack(fill="both", expand=True)

        heading = ttk.Label(wrapper, text="Read before continuing", font=("", 14, "bold"))
        heading.pack(anchor="w", pady=(0, 8))

        terms = (
            "By using this software, you agree to the following:\n\n"
            "1) You use it at your own risk.\n"
            "2) The author is not responsible for crashes, bans, or data loss.\n"
            "3) No refunds or chargebacks.\n"
            "4) By clicking “Accept”, you take full responsibility for your use.\n\n"
            "This dialog is shown only on first launch after acceptance."
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


class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.running = False
        self.config_data = self._load_config()

        root.title(APP_NAME)
        root.geometry("820x560")
        root.minsize(720, 480)

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
            # Use a nicer theme when available
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Settings", command=self._save_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        # Help
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

        # Status light
        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(top, textvariable=self.status_var, font=("", 12, "bold"))
        self.status_label.pack(side="left")

        ttk.Label(top, text="•").pack(side="left", padx=6)  # simple separator dot
        self.time_var = tk.StringVar(value="Uptime: 00:00:00")
        ttk.Label(top, textvariable=self.time_var).pack(side="left")

        # Start/Stop buttons
        btns = ttk.Frame(self.tab_dashboard)
        btns.pack(fill="x", pady=(0, 8))
        self.btn_start = ttk.Button(btns, text="Start", command=self._start)
        self.btn_stop = ttk.Button(btns, text="Stop", command=self._stop, state="disabled")
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop.pack(side="left")

        # Log
        ttk.Label(self.tab_dashboard, text="Log:").pack(anchor="w", pady=(12, 4))
        self.log = scrolledtext.ScrolledText(self.tab_dashboard, height=16, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

    def _build_settings(self):
        s = self.config_data["settings"]

        grid = ttk.Frame(self.tab_settings)
        grid.pack(fill="x", pady=(0, 12))

        ttk.Label(grid, text="Global hotkey (display only):").grid(row=0, column=0, sticky="w")
        self.var_hotkey = tk.StringVar(value=s.get("hotkey", "F6"))
        ttk.Entry(grid, textvariable=self.var_hotkey, width=12).grid(row=0, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(grid, text="Overlay opacity:").grid(row=1, column=0, sticky="w")
        self.var_opacity = tk.IntVar(value=int(s.get("overlay_opacity", 85)))
        ttk.Scale(grid, from_=0, to=100, variable=self.var_opacity, orient="horizontal", length=200).grid(
            row=1, column=1, sticky="w", padx=8, pady=4
        )
        ttk.Label(grid, text="0–100").grid(row=1, column=2, sticky="w")

        self.var_autostart = tk.BooleanVar(value=bool(s.get("autostart", False)))
        ttk.Checkbutton(grid, text="Start automatically after launch", variable=self.var_autostart).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=6
        )

        # Save button
        ttk.Button(self.tab_settings, text="Save Settings", command=self._save_settings).pack(anchor="w")

        # Spacer
        ttk.Separator(self.tab_settings, orient="horizontal").pack(fill="x", pady=12)

        # Note
        help_note = (
            "Note: This UI is a scaffold. Wire your actual features to Start/Stop.\n"
            "Avoid violating any platform’s ToS; keep it as a general overlay/assistant."
        )
        ttk.Label(self.tab_settings, text=help_note, foreground="#666").pack(anchor="w")

    def _build_about(self):
        ttk.Label(self.tab_about, text=APP_NAME, font=("", 16, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(self.tab_about, text="A sample Tkinter interface with a first-run disclaimer.").pack(anchor="w")
        ttk.Label(self.tab_about, text="• Dashboard: Start/Stop + status and logs\n• Settings: simple config saved to disk").pack(anchor="w", pady=(6,0))
        ttk.Label(self.tab_about, text="Config path:", font=("", 10, "bold")).pack(anchor="w", pady=(12, 0))
        ttk.Label(self.tab_about, text=str(CONFIG_FILE), foreground="#555").pack(anchor="w")

    # ---------- Logic ----------
    def _show_first_run(self):
        def accepted():
            self.config_data["accepted_terms"] = True
            self._save_config()
            self._log("Terms accepted.")
        FirstRunDialog(self.root, on_accept=accepted)

    def _start(self):
        if self.running:
            return
        self.running = True
        self.start_time = time.time()
        self.status_var.set("Running")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._log("Service started.")
        self._tick_uptime()

        # TODO: Start your worker/overlay logic here safely.
        # You can use .after(...) to schedule periodic tasks.

    def _stop(self):
        if not self.running:
            return
        self.running = False
        self.status_var.set("Stopped")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._log("Service stopped.")

        # TODO: Stop your worker/overlay logic here.

    def _tick_uptime(self):
        if not self.running:
            return
        elapsed = int(time.time() - self.start_time)
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        self.time_var.set(f"Uptime: {hh:02d}:{mm:02d}:{ss:02d}")
        self.root.after(1000, self._tick_uptime)

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
        # merge defaults to avoid KeyError if you add new settings later
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
            messagebox.showerror("Config", f"Failed to save config:\n{e}")

    def _save_settings(self):
        self.config_data["settings"]["hotkey"] = self.var_hotkey.get().strip()
        self.config_data["settings"]["overlay_opacity"] = int(self.var_opacity.get())
        self.config_data["settings"]["autostart"] = bool(self.var_autostart.get())
        self._save_config()
        self._log("Settings saved.")

    def _show_about_popup(self):
        message = (
            f"{APP_NAME}\n\n"
            "Sample interface with first-run terms, tabs, and persistent settings."
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
