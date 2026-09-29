"""
Ember password manager UI: unlock/create dialogs, manager window,
add/edit dialog with generator, clipboard auto-clear, idle auto-lock, autofill.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import vault as vaultlib

BG = "#14151b"
BAR = "#1b1c24"
FIELD = "#252733"
FG = "#e6e6e6"
MUTED = "#8b8fa3"
ACCENT = "#5b7fe0"
FONT = ("Sans", 11)

IDLE_LOCK_MS = 5 * 60 * 1000     # auto-lock after 5 minutes of no activity
CLIP_CLEAR_MS = 30 * 1000        # clear copied passwords after 30 seconds


def apply_styles(s):
    s.configure("Dark.TFrame", background=BG)
    s.configure("Dark.TLabel", background=BG, foreground=FG, font=FONT)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Sans", 9))
    s.configure("Err.TLabel", background=BG, foreground="#ff7b7b", font=("Sans", 9))
    s.configure("Dark.TCheckbutton", background=BG, foreground=FG, font=("Sans", 10))
    s.map("Dark.TCheckbutton", background=[("active", BG)],
          foreground=[("active", "#ffffff")])
    s.configure("Dark.TSpinbox", fieldbackground=FIELD, foreground=FG, background=FIELD,
                arrowcolor=FG, bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD,
                insertcolor=FG)
    s.configure("Vault.Treeview", background=BAR, fieldbackground=BAR, foreground=FG,
                borderwidth=0, rowheight=30, font=FONT)
    s.map("Vault.Treeview", background=[("selected", ACCENT)],
          foreground=[("selected", "#ffffff")])
    s.configure("Vault.Treeview.Heading", background=FIELD, foreground=MUTED,
                borderwidth=0, font=("Sans", 9, "bold"), relief="flat")
    s.map("Vault.Treeview.Heading", background=[("active", FIELD)])


# ---------------------------------------------------------------- helpers
def _dialog(parent, title):
    d = tk.Toplevel(parent)
    d.title(title)
    d.configure(bg=BG)
    d.transient(parent)
    d.resizable(False, False)
    return d


def _show_modal(d, parent):
    d.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - d.winfo_width()) // 2
    y = parent.winfo_rooty() + max(40, (parent.winfo_height() - d.winfo_height()) // 3)
    d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    d.wait_visibility()
    d.grab_set()
    parent.wait_window(d)


def _entry(parent, var, **kw):
    return ttk.Entry(parent, textvariable=var, style="Url.TEntry", font=FONT, **kw)


# ---------------------------------------------------------------- dialogs
def master_dialog(parent, vault, mode):
    """mode: 'create' | 'unlock' | 'change'. Returns True on success."""
    titles = {"create": "Create master password", "unlock": "Unlock vault",
              "change": "Change master password"}
    texts = {
        "create": "Choose a master password. It encrypts all your logins and "
                  "cannot be recovered if you forget it.",
        "unlock": "Enter your master password to unlock the vault.",
        "change": "Choose a new master password for your vault.",
    }
    d = _dialog(parent, titles[mode])
    result = {"ok": False}
    body = ttk.Frame(d, style="Dark.TFrame", padding=22)
    body.pack()

    ttk.Label(body, text=texts[mode], style="Muted.TLabel", wraplength=340,
              justify="left").grid(row=0, column=0, sticky="w", pady=(0, 12))
    pw, pw2, err = tk.StringVar(), tk.StringVar(), tk.StringVar()
    e1 = _entry(body, pw, show="\u2022", width=34)
    e1.grid(row=1, column=0, sticky="ew", ipady=5)
    if mode != "unlock":
        ttk.Label(body, text="Confirm", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(10, 2))
        _entry(body, pw2, show="\u2022", width=34).grid(row=3, column=0, sticky="ew", ipady=5)
    ttk.Label(body, textvariable=err, style="Err.TLabel").grid(
        row=4, column=0, sticky="w", pady=(8, 0))

    def submit(event=None):
        try:
            if mode == "unlock":
                vault.unlock(pw.get())
            else:
                if len(pw.get()) < 10:
                    err.set("Use at least 10 characters.")
                    return
                if pw.get() != pw2.get():
                    err.set("The passwords don't match.")
                    return
                if mode == "create":
                    vault.create(pw.get())
                else:
                    vault.change_master(pw.get())
        except vaultlib.WrongPassword:
            err.set("Wrong master password.")
            pw.set("")
            return
        except vaultlib.VaultError as ex:
            err.set(str(ex))
            return
        result["ok"] = True
        d.destroy()

    btns = ttk.Frame(body, style="Dark.TFrame")
    btns.grid(row=5, column=0, sticky="e", pady=(14, 0))
    ttk.Button(btns, text="Cancel", style="Tool.TButton", command=d.destroy).pack(side="left", padx=4)
    ttk.Button(btns, text={"create": "Create", "unlock": "Unlock", "change": "Change"}[mode],
               style="Accent.TButton", command=submit).pack(side="left", padx=4)
    d.bind("<Return>", submit)
    d.bind("<Escape>", lambda e: d.destroy())
    e1.focus_set()
    _show_modal(d, parent)
    return result["ok"]


def entry_dialog(parent, entry=None, site=""):
    """Add/edit dialog. Returns a dict of fields, or None if cancelled."""
    d = _dialog(parent, "Edit login" if entry else "Add login")
    result = {"data": None}
    body = ttk.Frame(d, style="Dark.TFrame", padding=22)
    body.pack()

    site_v = tk.StringVar(value=entry["site"] if entry else site)
    user_v = tk.StringVar(value=entry["username"] if entry else "")
    pass_v = tk.StringVar(value=entry["password"] if entry else "")
    show_v = tk.BooleanVar(value=False)
    len_v = tk.IntVar(value=20)
    sym_v = tk.BooleanVar(value=True)
    err = tk.StringVar()

    def lab(text, r):
        ttk.Label(body, text=text, style="Dark.TLabel").grid(
            row=r, column=0, sticky="w", pady=7, padx=(0, 14))

    lab("Website", 0)
    _entry(body, site_v, width=34).grid(row=0, column=1, columnspan=2, sticky="ew", ipady=4)
    lab("Username", 1)
    _entry(body, user_v, width=34).grid(row=1, column=1, columnspan=2, sticky="ew", ipady=4)
    lab("Password", 2)
    pw_entry = _entry(body, pass_v, width=34, show="\u2022")
    pw_entry.grid(row=2, column=1, sticky="ew", ipady=4)
    ttk.Checkbutton(body, text="Show", variable=show_v, style="Dark.TCheckbutton",
                    command=lambda: pw_entry.config(show="" if show_v.get() else "\u2022")
                    ).grid(row=2, column=2, padx=(10, 0))

    gen = ttk.Frame(body, style="Dark.TFrame")
    gen.grid(row=3, column=1, columnspan=2, sticky="w")
    ttk.Label(gen, text="Length", style="Muted.TLabel").pack(side="left")
    ttk.Spinbox(gen, from_=8, to=64, width=4, textvariable=len_v,
                style="Dark.TSpinbox").pack(side="left", padx=(6, 10))
    ttk.Checkbutton(gen, text="Symbols", variable=sym_v,
                    style="Dark.TCheckbutton").pack(side="left", padx=(0, 10))

    def generate():
        try:
            n = int(len_v.get())
        except (tk.TclError, ValueError):
            n = 20
        pass_v.set(vaultlib.generate_password(n, sym_v.get()))
        show_v.set(True)
        pw_entry.config(show="")

    ttk.Button(gen, text="Generate", style="Tool.TButton", command=generate).pack(side="left")

    lab("Notes", 4)
    notes = tk.Text(body, width=34, height=4, bg=FIELD, fg=FG, insertbackground=FG,
                    relief="flat", font=FONT, padx=8, pady=6, highlightthickness=0)
    notes.grid(row=4, column=1, columnspan=2, sticky="ew", pady=7)
    if entry:
        notes.insert("1.0", entry.get("notes", ""))

    ttk.Label(body, textvariable=err, style="Err.TLabel").grid(row=5, column=1, sticky="w")

    def save(event=None):
        if not site_v.get().strip():
            err.set("Website is required.")
            return
        if not pass_v.get():
            err.set("Password is required.")
            return
        result["data"] = {"site": site_v.get().strip(), "username": user_v.get().strip(),
                          "password": pass_v.get(), "notes": notes.get("1.0", "end").strip()}
        d.destroy()

    btns = ttk.Frame(body, style="Dark.TFrame")
    btns.grid(row=6, column=1, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="Cancel", style="Tool.TButton", command=d.destroy).pack(side="left", padx=4)
    ttk.Button(btns, text="Save", style="Accent.TButton", command=save).pack(side="left", padx=4)
    d.bind("<Escape>", lambda e: d.destroy())
    _show_modal(d, parent)
    return result["data"]


def choose_dialog(parent, entries):
    """Pick one login from several matches. Returns an entry or None."""
    d = _dialog(parent, "Choose a login")
    result = {"e": None}
    body = ttk.Frame(d, style="Dark.TFrame", padding=20)
    body.pack()
    ttk.Label(body, text="Several logins match this site:", style="Dark.TLabel").pack(anchor="w", pady=(0, 8))
    lb = tk.Listbox(body, width=44, height=min(8, len(entries)), bg=BAR, fg=FG,
                    selectbackground=ACCENT, relief="flat", font=FONT, highlightthickness=0)
    for e in entries:
        lb.insert("end", f'{e["site"]}  \u2014  {e["username"]}')
    lb.selection_set(0)
    lb.pack()

    def pick(event=None):
        sel = lb.curselection()
        if sel:
            result["e"] = entries[sel[0]]
        d.destroy()

    lb.bind("<Double-1>", pick)
    ttk.Button(body, text="Fill", style="Accent.TButton", command=pick).pack(anchor="e", pady=(12, 0))
    d.bind("<Return>", pick)
    d.bind("<Escape>", lambda e: d.destroy())
    _show_modal(d, parent)
    return result["e"]


# ---------------------------------------------------------------- manager
class PasswordManager:
    def __init__(self, app, vault):
        self.app = app
        self.vault = vault
        self.win = None
        self.tree = None
        self.q = tk.StringVar()
        self._idle_job = None
        self._clip_job = None
        self._clip_value = None
        app.bind_all("<Key>", self.touch, add="+")
        app.bind_all("<Button>", self.touch, add="+")

    # ---- lock handling ----
    def touch(self, event=None):
        if not self.vault.unlocked:
            return
        if self._idle_job:
            self.app.after_cancel(self._idle_job)
        self._idle_job = self.app.after(IDLE_LOCK_MS, self.lock)

    def lock(self):
        if self._idle_job:
            self.app.after_cancel(self._idle_job)
            self._idle_job = None
        self.vault.lock()
        if self.win and self.win.winfo_exists():
            self.win.destroy()
        self.win = None
        self.app.status.set("Vault locked")

    def ensure_unlocked(self):
        if self.vault.unlocked:
            self.touch()
            return True
        mode = "unlock" if self.vault.exists() else "create"
        if master_dialog(self.app, self.vault, mode):
            self.touch()
            return True
        return False

    # ---- helpers ----
    def current_host(self):
        host = vaultlib.host_of(getattr(self.app.page, "current_url", "") or "")
        return "" if host in ("127.0.0.1", "localhost") else host

    def copy(self, text, label):
        self.app.clipboard_clear()
        self.app.clipboard_append(text)
        self._clip_value = text
        if self._clip_job:
            self.app.after_cancel(self._clip_job)
        self._clip_job = self.app.after(CLIP_CLEAR_MS, self._clear_clip)
        self.app.status.set(f"{label} copied \u2014 clipboard clears in 30 seconds")

    def _clear_clip(self):
        try:
            if self.app.clipboard_get() == self._clip_value:
                self.app.clipboard_clear()
                self.app.clipboard_append("")
        except tk.TclError:
            pass
        self._clip_value = None

    def selected(self):
        if not self.tree:
            return None
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Ember", "Select a login first.", parent=self.win)
            return None
        return next((e for e in self.vault.entries if e["id"] == sel[0]), None)

    # ---- manager window ----
    def open_manager(self, search=None):
        if not self.ensure_unlocked():
            return
        if search is None:
            search = self.current_host()
        if self.win and self.win.winfo_exists():
            self.q.set(search)
            self.win.lift()
            return

        w = tk.Toplevel(self.app)
        w.title("Ember Passwords")
        w.geometry("780x500")
        w.minsize(640, 380)
        w.configure(bg=BG)
        self.win = w

        top = ttk.Frame(w, style="Dark.TFrame", padding=(16, 14, 16, 8))
        top.pack(fill="x")
        self.q.set(search)
        _entry(top, self.q).pack(side="left", fill="x", expand=True, ipady=5)
        ttk.Button(top, text="+ Add", style="Accent.TButton",
                   command=self.add).pack(side="left", padx=(10, 0))

        mid = ttk.Frame(w, style="Dark.TFrame", padding=(16, 4, 16, 4))
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("site", "user"), show="headings",
                                 style="Vault.Treeview", selectmode="browse")
        self.tree.heading("site", text="WEBSITE")
        self.tree.heading("user", text="USERNAME")
        self.tree.column("site", width=360)
        self.tree.column("user", width=300)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit())

        bot = ttk.Frame(w, style="Dark.TFrame", padding=(16, 8, 16, 14))
        bot.pack(fill="x")
        for text, cmd in (("Copy user", self.copy_user), ("Copy password", self.copy_pass),
                          ("Fill page", self.fill_selected), ("Edit", self.edit),
                          ("Delete", self.delete)):
            ttk.Button(bot, text=text, style="Tool.TButton", command=cmd).pack(side="left", padx=(0, 6))
        ttk.Button(bot, text="Lock", style="Accent.TButton",
                   command=self.lock).pack(side="right")
        ttk.Button(bot, text="Master password\u2026", style="Tool.TButton",
                   command=lambda: master_dialog(self.win, self.vault, "change")
                   ).pack(side="right", padx=6)

        self.q.trace_add("write", lambda *a: self.refresh())
        w.bind("<Escape>", lambda e: w.destroy())
        self.refresh()

    def refresh(self):
        if not (self.tree and self.win and self.win.winfo_exists()):
            return
        needle = self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for e in sorted(self.vault.entries, key=lambda x: x["site"].lower()):
            if needle in e["site"].lower() or needle in e["username"].lower():
                self.tree.insert("", "end", iid=e["id"], values=(e["site"], e["username"]))

    # ---- actions ----
    def add(self):
        parent = self.win if self.win and self.win.winfo_exists() else self.app
        data = entry_dialog(parent, site=self.current_host())
        if data:
            self.vault.add(**data)
            self.refresh()

    def edit(self):
        e = self.selected()
        if not e:
            return
        data = entry_dialog(self.win, entry=e)
        if data:
            self.vault.update(e["id"], **data)
            self.refresh()

    def delete(self):
        e = self.selected()
        if e and messagebox.askyesno("Delete login", f'Delete the login for {e["site"]}?',
                                     parent=self.win):
            self.vault.delete(e["id"])
            self.refresh()

    def copy_user(self):
        e = self.selected()
        if e:
            self.copy(e["username"], "Username")

    def copy_pass(self):
        e = self.selected()
        if e:
            self.copy(e["password"], "Password")

    def fill_selected(self):
        e = self.selected()
        if e:
            self.fill(e)

    # ---- autofill ----
    def autofill(self):
        """Fill the login form on the current page (Ctrl+Shift+F)."""
        if not self.ensure_unlocked():
            return
        url = getattr(self.app.page, "current_url", "") or ""
        matches = self.vault.find_for_url(url)
        if not matches:
            self.app.status.set("No saved login for this site \u2014 open Keys to add one")
            return
        entry = matches[0] if len(matches) == 1 else choose_dialog(self.app, matches)
        if entry:
            self.fill(entry)

    def fill(self, entry):
        if self._try_fill(entry):
            self.app.status.set(f'Filled login for {entry["site"]}')
        else:
            self.copy(entry["password"], "Password")
            self.app.status.set("Couldn't auto-fill this page \u2014 password copied "
                                f'(username: {entry["username"]})')

    def _try_fill(self, entry):
        """Best effort: set values on the page's form fields via tkinterweb's DOM."""
        try:
            inputs = list(self.app.page.document.getElementsByTagName("input"))
            pw_idx = next((i for i, el in enumerate(inputs)
                           if (el.getAttribute("type") or "").lower() == "password"), None)
            if pw_idx is None:
                return False
            user_el = None
            for el in inputs[:pw_idx]:
                if (el.getAttribute("type") or "text").lower() in ("text", "email", "tel", ""):
                    user_el = el
            if user_el is not None:
                user_el.value = entry["username"]
            inputs[pw_idx].value = entry["password"]
            return True
        except Exception:
            return False
