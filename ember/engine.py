"""
Ember search engine: a small personal search engine (standard library only).

  crawler  -> fetches pages politely (robots.txt, delay, per-crawl page cap)
  index    -> SQLite FTS5 with stemming, stored at ~/.ember/index.db
  search   -> BM25 ranking (title > description > body) with highlighted snippets

It only knows the sites YOU crawl, so it is a personal search engine, not a
replacement for a web-scale one.

Command line:
    python3 engine.py crawl https://example.com --depth 2 --max 200
    python3 engine.py search some words
    python3 engine.py stats
"""
import ipaddress
import re
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import deque
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from appdata import DATA_DIR

DB_PATH = DATA_DIR / "index.db"
USER_AGENT = "EmberBot/1.0 (personal search engine)"
MAX_BYTES = 1_500_000
MAX_BODY_CHARS = 200_000
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip",
            ".gz", ".tar", ".xz", ".7z", ".mp3", ".mp4", ".mkv", ".avi", ".webm",
            ".exe", ".iso", ".dmg", ".deb", ".rpm", ".apk", ".css", ".js", ".woff",
            ".woff2", ".ttf", ".xml", ".json")


# ------------------------------------------------------------------ database
def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS pages("
                "id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, "
                "host TEXT NOT NULL, fetched INTEGER NOT NULL)")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
                "title, description, body, tokenize='porter unicode61')")
    return con


def save_page(con, url, title, description, body):
    host = urlparse(url).hostname or ""
    row = con.execute("SELECT id FROM pages WHERE url=?", (url,)).fetchone()
    if row:
        pid = row[0]
        con.execute("UPDATE pages SET fetched=? WHERE id=?", (int(time.time()), pid))
        con.execute("DELETE FROM docs WHERE rowid=?", (pid,))
    else:
        pid = con.execute("INSERT INTO pages(url, host, fetched) VALUES(?,?,?)",
                          (url, host, int(time.time()))).lastrowid
    con.execute("INSERT INTO docs(rowid, title, description, body) VALUES(?,?,?,?)",
                (pid, title, description, body))
    con.commit()


def remove_host(host, db_path=DB_PATH):
    with closing(connect(db_path)) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM pages WHERE host=?", (host,))]
        for pid in ids:
            con.execute("DELETE FROM docs WHERE rowid=?", (pid,))
        con.execute("DELETE FROM pages WHERE host=?", (host,))
        con.commit()
    return len(ids)


def stats(db_path=DB_PATH):
    with closing(connect(db_path)) as con:
        total = con.execute("SELECT count(*) FROM pages").fetchone()[0]
        hosts = con.execute("SELECT host, count(*) FROM pages GROUP BY host "
                            "ORDER BY 2 DESC, 1 LIMIT 50").fetchall()
    return {"pages": total, "hosts": hosts}


# -------------------------------------------------------------------- search
def make_query(text):
    tokens = re.findall(r"\w+", text.lower())[:12]
    if not tokens:
        return None
    parts = [f'"{t}"' for t in tokens]
    parts[-1] += "*"                      # prefix match on the last word
    return " ".join(parts)


def search(text, page=1, per_page=10, db_path=DB_PATH):
    """Returns (total, results). Snippet highlights use \\x02 ... \\x03 markers."""
    query = make_query(text)
    if not query:
        return 0, []
    with closing(connect(db_path)) as con:
        total = con.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                            (query,)).fetchone()[0]
        rows = con.execute(
            "SELECT p.url, p.host, docs.title, docs.description, "
            "snippet(docs, 2, char(2), char(3), ' \u2026 ', 30) "
            "FROM docs JOIN pages p ON p.id = docs.rowid "
            "WHERE docs MATCH ? ORDER BY bm25(docs, 8.0, 2.0, 1.0) LIMIT ? OFFSET ?",
            (query, per_page, max(0, page - 1) * per_page)).fetchall()
    results = [{"url": u, "host": h, "title": t or u, "description": d, "snippet": s}
               for u, h, t, d, s in rows]
    return total, results


# ------------------------------------------------------------------- fetching
def is_public_host(host):
    """False for localhost / private / link-local addresses (blocks SSRF)."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
        return all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except (OSError, ValueError):
        return False


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlparse(newurl)
        if p.scheme not in ("http", "https") or not is_public_host(p.hostname):
            raise urllib.error.URLError("redirect to a non-public address blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, allow_private=False, html_only=True, limit=MAX_BYTES):
    """Returns (final_url, text). Raises on errors / non-HTML / blocked hosts."""
    if not allow_private and not is_public_host(urlparse(url).hostname):
        raise ValueError("non-public host blocked")
    opener = urllib.request.build_opener() if allow_private \
        else urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"})
    with opener.open(req, timeout=12) as r:
        if html_only and "html" not in r.headers.get("Content-Type", "").lower():
            raise ValueError("not an HTML page")
        data = r.read(limit + 1)[:limit]
        charset = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), data.decode(charset, "replace")


class Robots:
    def __init__(self, allow_private=False):
        self.cache = {}
        self.allow_private = allow_private

    def allowed(self, url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self.cache.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                _, text = fetch(base + "/robots.txt", self.allow_private,
                                html_only=False, limit=200_000)
                rp.parse(text.splitlines())
            except Exception:
                rp.parse([])              # no robots.txt -> everything allowed
            self.cache[base] = rp
        return rp.can_fetch(USER_AGENT, url)


# -------------------------------------------------------------------- parsing
class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.links = []
        self.noindex = False
        self._text = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = (a.get("content") or "").strip()
            if name in ("description", "og:description") and not self.description:
                self.description = content
            elif name == "robots" and "noindex" in content.lower():
                self.noindex = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._text.append(data)

    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self._text)).strip()[:MAX_BODY_CHARS]


def normalize(url):
    try:
        url, _ = urldefrag((url or "").strip())
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        if p.path.lower().endswith(SKIP_EXT):
            return None
        for name in ("index.html", "index.htm"):      # /index.html == /
            if p.path.lower().endswith("/" + name):
                url = p._replace(path=p.path[:-len(name)]).geturl()
                break
        return url
    except ValueError:
        return None


def _canon_host(url):
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# -------------------------------------------------------------------- crawler
class Crawler:
    def __init__(self, db_path=DB_PATH, max_pages=100, max_depth=2, delay=1.0,
                 allow_private=False):
        self.db_path = db_path
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.allow_private = allow_private
        self.stop_flag = threading.Event()
        self.status = {"running": False, "seed": "", "current": "", "crawled": 0,
                       "failed": 0, "queued": 0, "note": ""}

    def crawl(self, seed, log=None):
        st = self.status
        st.update(running=True, seed=seed, crawled=0, failed=0, queued=1, note="")
        site = _canon_host(seed)
        robots = Robots(self.allow_private)
        queue, seen = deque([(seed, 0)]), {seed}
        try:
            with closing(connect(self.db_path)) as con:
                while queue and st["crawled"] < self.max_pages and not self.stop_flag.is_set():
                    url, depth = queue.popleft()
                    st.update(current=url, queued=len(queue))
                    try:
                        if not robots.allowed(url):
                            continue
                        final, html = fetch(url, self.allow_private)
                        parser = PageParser()
                        parser.feed(html)
                        parser.close()
                    except Exception as ex:
                        st["failed"] += 1
                        if log:
                            log(f"  skip {url}: {ex}")
                        continue
                    if not parser.noindex:
                        save_page(con, final, parser.title.strip() or final,
                                  parser.description, parser.text)
                        st["crawled"] += 1
                        if log:
                            log(f"  [{st['crawled']}] {final}")
                    if depth < self.max_depth:
                        for href in parser.links:
                            nxt = normalize(urljoin(final, href))
                            if (nxt and nxt not in seen and _canon_host(nxt) == site
                                    and len(seen) < 20000):
                                seen.add(nxt)
                                queue.append((nxt, depth + 1))
                    time.sleep(self.delay)
            st["note"] = "Stopped." if self.stop_flag.is_set() else "Finished."
        except Exception as ex:
            st["note"] = f"Crawl failed: {ex}"
        finally:
            st.update(running=False, current="", queued=0)


_crawler = None
_lock = threading.Lock()


def start_crawl(seed, max_pages=100, max_depth=2, delay=1.0, allow_private=False):
    """Start a background crawl. Returns (ok, message)."""
    global _crawler
    seed = (seed or "").strip()
    if seed and "://" not in seed:
        seed = "http://" + seed
    seed = normalize(seed)
    if not seed:
        return False, "That doesn't look like a valid http(s) address."
    with _lock:
        if _crawler and _crawler.status["running"]:
            return False, "A crawl is already running."
        _crawler = Crawler(max_pages=max_pages, max_depth=max_depth, delay=delay,
                           allow_private=allow_private)
        _crawler.status["running"] = True
        threading.Thread(target=_crawler.crawl, args=(seed,), daemon=True).start()
    return True, f"Started crawling {seed}"


def stop_crawl():
    if _crawler:
        _crawler.stop_flag.set()


def crawl_status():
    if _crawler:
        return dict(_crawler.status)
    return {"running": False, "seed": "", "current": "", "crawled": 0,
            "failed": 0, "queued": 0, "note": ""}


# ------------------------------------------------------------------------ CLI
def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Ember personal search engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl")
    c.add_argument("url")
    c.add_argument("--depth", type=int, default=2)
    c.add_argument("--max", type=int, default=100)
    c.add_argument("--delay", type=float, default=1.0)
    c.add_argument("--allow-private", action="store_true",
                   help="allow crawling localhost / LAN addresses")
    s = sub.add_parser("search")
    s.add_argument("terms", nargs="+")
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    if args.cmd == "crawl":
        seed = normalize(args.url if "://" in args.url else "http://" + args.url)
        if not seed:
            sys.exit("Invalid URL")
        crawler = Crawler(max_pages=args.max, max_depth=args.depth, delay=args.delay,
                          allow_private=args.allow_private)
        print(f"Crawling {seed} (max {args.max} pages, depth {args.depth}) ...")
        try:
            crawler.crawl(seed, log=print)
        except KeyboardInterrupt:
            crawler.stop_flag.set()
        print(crawler.status["note"], f"{crawler.status['crawled']} pages indexed,",
              f"{crawler.status['failed']} skipped/failed.")
    elif args.cmd == "search":
        total, results = search(" ".join(args.terms))
        print(f"{total} result(s)")
        for r in results:
            print(f"\n{r['title']}\n  {r['url']}\n  "
                  + r["snippet"].replace("\x02", "*").replace("\x03", "*"))
    else:
        info = stats()
        print(f"{info['pages']} pages indexed")
        for host, n in info["hosts"]:
            print(f"  {n:5d}  {host}")


if __name__ == "__main__":
    _main(sys.argv[1:])
