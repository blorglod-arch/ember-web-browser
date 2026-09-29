#!/usr/bin/env python3
"""
Ember - a tiny, modern-looking Dillo-style web browser in Python.

- No JavaScript, minimal and fast.
- Every link opens INSIDE this window (never launches Chrome or any other browser).
- Starts its own custom home page server (homeserver.py) automatically.
- Non-URL text in the address bar searches the web (DuckDuckGo results shown
  inside Ember) plus your own crawled index (engine.py).
  Start with "!w " to open DuckDuckGo Lite itself instead.

Install:   pip install tkinterweb cryptography
Run:       python3 ember.py [url]

Keys: Ctrl+L address bar | Alt+Left/Right back/forward | F5 reload
      Esc stop | Ctrl+Q quit
      Ctrl+Shift+P password manager | Ctrl+Shift+F autofill this page
"""
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from urllib.parse import quote_plus

try:
    from tkinterweb import HtmlFrame
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install tkinterweb")

import homeserver

try:
    import vault as vaultlib
    import passmanager
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install cryptography")

HOME = f"http://{homeserver.HOST}:{homeserver.PORT}/"
SEARCH = f"http://{homeserver.HOST}:{homeserver.PORT}/search?q="   # your own index
WEB_SEARCH = "https://lite.duckduckgo.com/lite/?q="                # "!w query"

# ---- theme ----
BG = "#14151b"
BAR = "#1b1c24"
FIELD = "#252733"
FG = "#e6e6e6"
MUTED = "#8b8fa3"
ACCENT = "#5b7fe0"
HOVER = "#2e3040"
FONT = ("Sans", 11)


class Ember(tk.Tk):
    def __init__(self, start=None):
        super().__init__(className="Ember")   # WM_CLASS: how the dock identifies us
        self.title("Ember")
        self.geometry("1100x760")
        self.configure(bg=BG)
        self.set_icon()
        self.apply_style()

        # ---- toolbar ----
        bar = ttk.Frame(self, style="Bar.TFrame", padding=(8, 8))
        bar.pack(fill="x")
        for text, cmd in (
            ("\u2190", self.go_back),
            ("\u2192", self.go_forward),
            ("\u27f3", self.reload),
            ("\u2715", self.stop),
            ("\u2302", self.go_home),
        ):
            ttk.Button(bar, text=text, width=3, style="Tool.TButton",
                       command=cmd, takefocus=False).pack(side="left", padx=2)

        self.url_var = tk.StringVar()
        self.entry = ttk.Entry(bar, textvariable=self.url_var, style="Url.TEntry",
                               font=FONT)
        self.entry.pack(side="left", fill="x", expand=True, padx=(10, 6), ipady=5)
        self.entry.bind("<Return>", lambda e: self.navigate(self.url_var.get()))
        self.entry.bind("<FocusIn>",
                        lambda e: self.after(10, lambda: self.entry.select_range(0, "end")))
        ttk.Button(bar, text="Go", width=5, style="Accent.TButton",
                   command=lambda: self.navigate(self.url_var.get()),
                   takefocus=False).pack(side="left", padx=2)
        ttk.Button(bar, text="Keys", width=5, style="Tool.TButton",
                   command=lambda: self.passwords.open_manager(),
                   takefocus=False).pack(side="left", padx=(6, 2))

        # thin divider under the toolbar
        tk.Frame(self, bg="#2a2c3a", height=1).pack(fill="x")

        # ---- page view ----
        self.page = HtmlFrame(self, messages_enabled=False)
        self.page.pack(fill="both", expand=True)
        self.page.bind("<<UrlChanged>>", self.on_url_change)
        self.page.bind("<<TitleChanged>>", self.on_title_change)

        # ---- status bar ----
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, style="Status.TLabel",
                  anchor="w", padding=(10, 4)).pack(fill="x")

        # ---- shortcuts ----
        self.bind("<Control-l>", lambda e: (self.entry.focus_set(),
                                            self.entry.select_range(0, "end")))
        self.bind("<Alt-Left>", lambda e: self.go_back())
        self.bind("<Alt-Right>", lambda e: self.go_forward())
        self.bind("<F5>", lambda e: self.reload())
        self.bind("<Escape>", lambda e: self.stop())
        self.bind("<Control-q>", lambda e: self.destroy())

        # ---- password manager ----
        self.passwords = passmanager.PasswordManager(self, vaultlib.Vault())
        for seq in ("<Control-Shift-p>", "<Control-Shift-P>"):
            self.bind(seq, lambda e: self.passwords.open_manager())
        for seq in ("<Control-Shift-f>", "<Control-Shift-F>"):
            self.bind(seq, lambda e: self.passwords.autofill())

        self.navigate(start or HOME)

    def set_icon(self):
        here = Path(__file__).resolve().parent
        try:
            # larger sizes first so the window manager can pick the best fit
            self._icons = [tk.PhotoImage(file=str(here / n))
                           for n in ("logo.png", "logo-64.png")]
            self.iconphoto(True, *self._icons)
        except (tk.TclError, OSError):
            pass  # no logo files found: just use the default icon

    def apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Bar.TFrame", background=BAR)

        s.configure("Tool.TButton", background=BAR, foreground=FG, borderwidth=0,
                    focusthickness=0, relief="flat", padding=(6, 4),
                    font=("Sans", 13))
        s.map("Tool.TButton",
              background=[("active", HOVER), ("pressed", HOVER)],
              foreground=[("active", "#ffffff")])

        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    borderwidth=0, focusthickness=0, relief="flat",
                    padding=(10, 5), font=("Sans", 10, "bold"))
        s.map("Accent.TButton", background=[("active", "#7194ee")])

        s.configure("Url.TEntry", fieldbackground=FIELD, foreground=FG,
                    insertcolor=FG, bordercolor=FIELD, lightcolor=FIELD,
                    darkcolor=FIELD, padding=(10, 4))
        s.map("Url.TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])

        s.configure("Status.TLabel", background=BAR, foreground=MUTED,
                    font=("Sans", 9))
        passmanager.apply_styles(s)

    # ---- navigation ----
    def navigate(self, text):
        text = text.strip()
        if not text:
            return
        if text.startswith("!w ") and text[3:].strip():
            url = WEB_SEARCH + quote_plus(text[3:].strip())
        elif "://" in text:
            url = text
        elif "." in text and " " not in text or text.startswith("localhost"):
            url = "http://" + text
        else:
            url = SEARCH + quote_plus(text)
        self.status.set(f"Loading {url} ...")
        self.page.load_website(url)
        self.page.focus_set()

    def go_back(self):
        self.page.back()

    def go_forward(self):
        self.page.forward()

    def reload(self):
        self.page.reload()

    def stop(self):
        self.page.stop()
        self.status.set("Stopped")

    def go_home(self):
        self.navigate(HOME)

    # ---- callbacks ----
    def on_url_change(self, event=None):
        url = getattr(self.page, "current_url", "") or ""
        self.url_var.set("" if url == HOME else url)
        self.status.set(f"Loaded {url}")

    def on_title_change(self, event=None):
        title = getattr(self.page, "title", "") or ""
        self.title(f"{title} - Ember" if title else "Ember")


def install_desktop_entry():
    """Create an app-menu/dock entry so Ember shows its own name and icon
    instead of the generic Tk gear. Run once:  python3 ember.py --install"""
    here = Path(__file__).resolve().parent
    share = Path.home() / ".local" / "share"
    for size, name in (("256x256", "logo.png"), ("64x64", "logo-64.png")):
        src = here / name
        if src.exists():
            dest = share / "icons" / "hicolor" / size / "apps"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / "ember.png")
    apps = share / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    script = str(here / "ember.py").replace(" ", "\\\\ ")
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Ember\n"
        "Comment=Lightweight web browser\n"
        f"Exec={sys.executable} {script} %u\n"
        "Icon=ember\n"
        "Terminal=false\n"
        "Categories=Network;WebBrowser;\n"
        "StartupWMClass=Ember\n"
    )
    (apps / "ember.desktop").write_text(entry)
    for cmd in (["update-desktop-database", str(apps)],
                ["gtk-update-icon-cache", "-f", "-t", str(share / "icons" / "hicolor")]):
        try:
            subprocess.run(cmd, check=False, capture_output=True)
        except OSError:
            pass  # tool not installed: not needed on most desktops
    print(f"Installed {apps / 'ember.desktop'}")
    print("Now close Ember completely and start it again. If the dock still shows the "
          "old icon, log out and back in once.")


if __name__ == "__main__":
    if "--install" in sys.argv[1:]:
        install_desktop_entry()
        sys.exit(0)
    homeserver.start_in_thread()
    Ember(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
