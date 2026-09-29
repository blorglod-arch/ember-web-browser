#!/usr/bin/env python3
"""
Ember local server (standard library only): home page + search engine UI.

  /            custom start page
  /search      web results (websearch.py) plus matches from your own index (engine.py)
  /index       manage the index: add sites to crawl, see stats, remove sites
  /logo.png    the Ember logo

Ember starts this automatically; you can also run it alone:  python3 homeserver.py
Custom shortcut tiles: create links.json next to this file:
    [{"name": "Wikipedia", "url": "https://en.wikipedia.org"}]
"""
import json
import secrets
import threading
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

import engine
import websearch

HOST, PORT = "127.0.0.1", 8080
BASE = f"http://{HOST}:{PORT}"
WEB_SEARCH = "https://lite.duckduckgo.com/lite/?q="

# Protects the POST actions (crawl / stop / remove) from other web pages that
# might try to trigger them, and Host checking blocks DNS-rebinding tricks.
TOKEN = secrets.token_hex(16)
ALLOWED_HOSTS = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
_flash = ""

DEFAULT_LINKS = [
    {"name": "Wikipedia", "url": "https://en.wikipedia.org"},
    {"name": "Hacker News", "url": "https://news.ycombinator.com"},
    {"name": "Lite News (CNN)", "url": "https://lite.cnn.com"},
    {"name": "Text Weather", "url": "https://wttr.in"},
    {"name": "GitHub", "url": "https://github.com"},
    {"name": "Debian", "url": "https://www.debian.org"},
    {"name": "Lobsters", "url": "https://lobste.rs"},
    {"name": "Archive.org", "url": "https://archive.org"},
]

# Tkhtml (Ember's HTML engine) has no flexbox/grid: layout uses tables + simple CSS.
CSS = """
body { background: #14151b; color: #e6e6e6; font-family: sans-serif; margin: 0; padding: 0; }
a { color: #9db8f5; text-decoration: none; }
b { color: #ffffff; }
input.q { font-size: 15px; padding: 9px; width: 420px; background: #23252f;
          color: #ffffff; border: 1px solid #3a3d4d; }
input.s { font-size: 13px; padding: 9px; background: #23252f; color: #ffffff;
          border: 1px solid #3a3d4d; }
input.go { font-size: 15px; padding: 9px 16px; background: #5b7fe0; color: #ffffff;
           border: 1px solid #5b7fe0; }
input.del { font-size: 12px; padding: 4px 10px; background: #3a2226; color: #ff9c9c;
            border: 1px solid #5a3036; }
.wrap { text-align: center; padding-top: 50px; }
.clock { font-size: 64px; color: #ffffff; margin: 0; }
.date { font-size: 16px; color: #8b8fa3; margin-top: 4px; }
.hello { font-size: 22px; color: #c9cde0; margin-top: 26px; margin-bottom: 26px; }
table.tiles { margin-left: auto; margin-right: auto; margin-top: 44px; }
td.tile { background: #1e2029; border: 1px solid #2c2f3d; padding: 16px 22px;
          text-align: center; font-size: 15px; width: 120px; }
td.gap { width: 14px; }
td.vgap { height: 14px; }
.foot { color: #5c6075; font-size: 12px; margin-top: 46px; margin-bottom: 30px; }
table.col { margin-left: auto; margin-right: auto; width: 780px; }
td.logo { width: 56px; padding-top: 18px; padding-bottom: 12px; }
td.head { padding-top: 18px; padding-bottom: 12px; }
.meta { color: #8b8fa3; font-size: 13px; margin-top: 6px; margin-bottom: 16px; }
.res { margin-bottom: 22px; }
.t { font-size: 18px; }
.u { color: #6fbf8b; font-size: 13px; margin-top: 2px; }
.s { color: #b9bdd0; font-size: 14px; margin-top: 4px; }
.pager { margin-top: 10px; margin-bottom: 10px; font-size: 15px; }
.box { background: #1b1c24; border: 1px solid #2c2f3d; padding: 14px 18px; margin-bottom: 18px; }
.h2 { font-size: 17px; color: #ffffff; margin-top: 22px; margin-bottom: 8px; }
.note { color: #f0c674; font-size: 14px; margin-bottom: 12px; }
td.cell { padding: 6px 14px 6px 0; font-size: 14px; }
.tabs { color: #8b8fa3; font-size: 14px; margin-top: 2px; margin-bottom: 14px; }
.h3 { font-size: 13px; color: #8b8fa3; margin-top: 14px; margin-bottom: 10px; }
.err { color: #e8a0a0; font-size: 13px; margin-top: 4px; }
"""


def esc(text, quote=False):
    return escape(str(text), quote=quote)


def shell(title, body):
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{esc(title)}</title>'
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def header(q=""):
    return (f'<table class="col"><tr><td class="logo"><a href="{BASE}/">'
            f'<img src="{BASE}/logo.png" width="40" height="40"></a></td>'
            f'<td class="head"><form action="{BASE}/search" method="get">'
            f'<input class="q" type="text" name="q" value="{esc(q, True)}" size="40"> '
            f'<input class="go" type="submit" value="Search"></form></td></tr></table>')


# ---------------------------------------------------------------- home page
def load_links():
    path = Path(__file__).with_name("links.json")
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list) and data:
                return data
        except (OSError, ValueError):
            pass
    return DEFAULT_LINKS


def render_home():
    now = datetime.now()
    greeting = ("Good morning" if now.hour < 12 else
                "Good afternoon" if now.hour < 18 else "Good evening")
    rows = []
    links = load_links()
    for i in range(0, len(links), 4):
        row = ""
        for link in links[i:i + 4]:
            row += (f'<td class="tile"><a href="{esc(link.get("url", "#"), True)}">'
                    f'{esc(link.get("name", ""))}</a></td><td class="gap"></td>')
        rows.append(f"<tr>{row}</tr><tr><td class='vgap' colspan='8'></td></tr>")
    body = f"""<div class="wrap">
  <img src="{BASE}/logo.png" width="88" height="88" alt="Ember">
  <div class="clock">{now.strftime("%H:%M")}</div>
  <div class="date">{now.strftime("%A, %d %B %Y")}</div>
  <div class="hello">{greeting}.</div>
  <form action="{BASE}/search" method="get">
    <input class="q" type="text" name="q" size="40" placeholder="Search the web">
    <input class="go" type="submit" value="Search">
  </form>
  <table class="tiles">{"".join(rows)}</table>
  <div class="foot"><a href="{BASE}/index">Manage search index</a> &middot;
    tip: start a search with !w to open DuckDuckGo itself<br><br>
    Ember &middot; no JavaScript, no tracking, no Chrome</div>
</div>"""
    return shell("Start", body)


# -------------------------------------------------------------------- search
def result_html(title, url, snippet_html):
    shown = url.split("://", 1)[-1]
    if len(shown) > 90:
        shown = shown[:87] + "..."
    return (f'<div class="res"><a class="t" href="{esc(url, True)}">{esc(title)}</a>'
            f'<div class="u">{esc(shown)}</div><div class="s">{snippet_html}</div></div>')


def local_snippet(r):
    text = esc(r["snippet"] or r["description"] or "")
    return text.replace("\x02", "<b>").replace("\x03", "</b>")


def tabs(q, scope):
    qs = quote_plus(q)
    web = "<b>Web</b>" if scope == "web" else f'<a href="{BASE}/search?q={qs}">Web</a>'
    loc = ("<b>My index</b>" if scope == "local"
           else f'<a href="{BASE}/search?q={qs}&scope=local">My index</a>')
    return f'<div class="tabs">{web} &nbsp;&middot;&nbsp; {loc}</div>'


def render_search(q, page=1, scope="web"):
    q = q.strip()[:200]
    if scope == "local":
        return render_local(q, page)
    parts = [header(q), '<table class="col"><tr><td>', tabs(q, "web")]
    if not q:
        parts.append('<div class="meta">Type something to search.</div>')
    else:
        qs = quote_plus(q)
        total, local = engine.search(q, page=1, per_page=3)
        if total:
            parts.append('<div class="h3">FROM YOUR INDEX</div>')
            parts += [result_html(r["title"], r["url"], local_snippet(r)) for r in local]
            if total > 3:
                parts.append(f'<div class="meta"><a href="{BASE}/search?q={qs}&scope=local">'
                             f"All {total} matches in your index &raquo;</a></div>")
            parts.append('<div class="h3">FROM THE WEB</div>')
        out = websearch.web_search(q)
        if out["results"]:
            note = f'Results from {esc(out["provider"])}'
            if out["provider"] != "DuckDuckGo":
                note += " (DuckDuckGo wasn't available, see below)"
            parts.append(f'<div class="meta">{note}</div>')
            parts += [result_html(r["title"], r["url"], esc(r["snippet"])) for r in out["results"]]
            if out["errors"]:
                parts.append('<div class="err">' + "<br>".join(esc(e) for e in out["errors"])
                             + "</div>")
        else:
            problems = "<br>".join(esc(e) for e in out["errors"]) or "no details"
            parts.append(f'<div class="box">Couldn\'t get web results for <b>{esc(q)}</b> '
                         f'right now.<div class="err">{problems}</div></div>')
        parts.append(f'<div class="meta"><a href="{esc(WEB_SEARCH + qs, True)}">'
                     f"Open this search on DuckDuckGo</a> &middot; "
                     f'<a href="{BASE}/index">Manage index</a></div>')
    parts.append("</td></tr></table>")
    return shell(f"{q} - Ember Search" if q else "Ember Search", "".join(parts))


def render_local(q, page):
    per_page = 10
    parts = [header(q), '<table class="col"><tr><td>', tabs(q, "local")]
    if not q:
        parts.append('<div class="meta">Type something to search your index.</div>')
    else:
        qs = quote_plus(q)
        total, results = engine.search(q, page=page, per_page=per_page)
        if total == 0:
            info = engine.stats()
            if info["pages"] == 0:
                hint = (f'Your index is empty. <a href="{BASE}/index">Add a site to crawl</a> '
                        "and Ember will index it so you can search it here.")
            else:
                hint = (f'Nothing in your {info["pages"]} indexed pages matches that. '
                        f'<a href="{BASE}/index">Add more sites</a>.')
            parts.append(f'<div class="meta">No results for <b>{esc(q)}</b>. {hint}</div>')
        else:
            first = (page - 1) * per_page + 1
            parts.append(f'<div class="meta">{total} result{"s" if total != 1 else ""}'
                         f" &middot; showing {first}&ndash;{first + len(results) - 1}</div>")
            parts += [result_html(r["title"], r["url"], local_snippet(r)) for r in results]
            pages = (total + per_page - 1) // per_page
            nav = []
            if page > 1:
                nav.append(f'<a href="{BASE}/search?q={qs}&scope=local&p={page - 1}">&laquo; Previous</a>')
            if page < pages:
                nav.append(f'<a href="{BASE}/search?q={qs}&scope=local&p={page + 1}">Next &raquo;</a>')
            if nav:
                parts.append('<div class="pager">' + " &nbsp;&middot;&nbsp; ".join(nav) + "</div>")
        parts.append(f'<div class="meta"><a href="{BASE}/index">Manage index</a></div>')
    parts.append("</td></tr></table>")
    return shell(f"{q} - Ember Index" if q else "Ember Index", "".join(parts))


# ------------------------------------------------------------ index manager
def render_index():
    global _flash
    st = engine.crawl_status()
    info = engine.stats()
    tok = f'<input type="hidden" name="t" value="{TOKEN}">'
    parts = [header(), '<table class="col"><tr><td>',
             '<div class="h2">Search index</div>']
    if _flash:
        parts.append(f'<div class="note">{esc(_flash)}</div>')
        _flash = ""

    if st["running"]:
        parts.append(
            f'<div class="box">Crawling <b>{esc(st["seed"])}</b><br>'
            f'<span class="meta">{st["crawled"]} pages indexed &middot; {st["queued"]} queued '
            f'&middot; {st["failed"]} skipped<br>Now: {esc(st["current"])}</span><br><br>'
            f'<a href="{BASE}/index">Refresh</a> &nbsp;'
            f'<form action="{BASE}/index/stop" method="post" style="display:inline">{tok}'
            f'<input class="del" type="submit" value="Stop crawl"></form></div>')
    elif st["note"]:
        parts.append(f'<div class="meta">Last crawl of {esc(st["seed"])}: {esc(st["note"])} '
                     f'{st["crawled"]} pages indexed, {st["failed"]} skipped.</div>')

    parts.append(
        f'<div class="box"><form action="{BASE}/index/add" method="post">{tok}'
        'Add a site to your index<br><br>'
        '<input class="q" type="text" name="url" size="36" placeholder="https://example.com"><br><br>'
        'Max pages <input class="s" type="text" name="max" value="100" size="4"> &nbsp;'
        'Depth <input class="s" type="text" name="depth" value="2" size="2"> &nbsp;'
        '<input class="go" type="submit" value="Crawl site">'
        '<div class="meta">Stays on the site you enter, obeys robots.txt, waits 1s between '
        'pages, and never crawls local/private addresses.</div></form></div>')

    parts.append(f'<div class="h2">{info["pages"]} pages indexed</div>')
    if info["hosts"]:
        rows = ""
        for host, n in info["hosts"]:
            rows += (f'<tr><td class="cell">{esc(host)}</td><td class="cell">{n}</td>'
                     f'<td class="cell"><form action="{BASE}/index/remove" method="post">{tok}'
                     f'<input type="hidden" name="host" value="{esc(host, True)}">'
                     f'<input class="del" type="submit" value="Remove"></form></td></tr>')
        parts.append(f"<table>{rows}</table>")
    parts.append("</td></tr></table>")
    return shell("Search index - Ember", "".join(parts))


# ------------------------------------------------------------------- handler
def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    def _host_ok(self):
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self.send_error(403, "Bad Host header")
            return False
        return True

    def _send(self, body, ctype="text/html; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path == "/logo.png":
            try:
                self._send(Path(__file__).with_name("logo.png").read_bytes(), "image/png")
            except OSError:
                self.send_error(404)
        elif url.path in ("/", "/index.html"):
            self._send(render_home().encode("utf-8"))
        elif url.path == "/search":
            q = params.get("q", [""])[0]
            page = _int(params.get("p", ["1"])[0], 1, 1, 1000)
            scope = "local" if params.get("scope", [""])[0] == "local" else "web"
            self._send(render_search(q, page, scope).encode("utf-8"))
        elif url.path == "/index":
            self._send(render_index().encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self):
        global _flash
        if not self._host_ok():
            return
        length = _int(self.headers.get("Content-Length"), 0, 0, 1 << 30)
        if length > 4096:
            self.send_error(413)
            return
        raw = self.rfile.read(length).decode("utf-8", "replace")
        data = {k: v[0] for k, v in parse_qs(raw).items()}
        if data.get("t") != TOKEN:
            self.send_error(403, "Bad token")
            return
        path = urlparse(self.path).path
        if path == "/index/add":
            ok, _flash = engine.start_crawl(
                data.get("url", ""),
                max_pages=_int(data.get("max"), 100, 1, 2000),
                max_depth=_int(data.get("depth"), 2, 0, 4))
        elif path == "/index/stop":
            engine.stop_crawl()
            _flash = "Stopping the crawl..."
        elif path == "/index/remove":
            n = engine.remove_host(data.get("host", ""))
            _flash = f"Removed {n} pages."
        else:
            self.send_error(404)
            return
        self.send_response(303)
        self.send_header("Location", f"{BASE}/index")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass  # keep the terminal quiet


def start_in_thread():
    """Start the server in the background. Returns False if the port is already
    in use (e.g. homeserver.py is already running)."""
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Ember server running at {BASE}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
