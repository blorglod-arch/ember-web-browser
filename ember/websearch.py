"""
Ember web search (standard library only).

Fetches real web results and hands them to Ember's own results page:
  1. DuckDuckGo HTML   (html.duckduckgo.com)
  2. DuckDuckGo Lite   (lite.duckduckgo.com)  - used if #1 fails
  3. Wikipedia search API                      - last-resort fallback

Ads are dropped, DuckDuckGo's tracking redirects are unwrapped, and results are
cached for 10 minutes. Your query is sent to those sites, nothing else is.

Diagnose from a terminal:
    python3 websearch.py hello world
    python3 websearch.py --raw hello world      (also shows the raw reply)
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
API_UA = "Ember/1.0 (personal lightweight browser)"
CACHE_TTL = 600
TOTAL_BUDGET = 14          # seconds, across all providers
_cache = {}


class SearchError(Exception):
    pass


def _get(url, timeout, accept="text/html", ua=BROWSER_UA):
    """Returns (status, text). Raises SearchError with a readable reason."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": accept + ",*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(2_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, data.decode(charset, "replace")
    except urllib.error.HTTPError as e:
        raise SearchError(f"HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise SearchError(f"network error: {getattr(e, 'reason', e)}")


# ------------------------------------------------------------- DuckDuckGo
def clean_url(href):
    """Unwrap DuckDuckGo's redirect links; return '' for ads / unusable links."""
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    p = urllib.parse.urlparse(href)
    if p.netloc.endswith("duckduckgo.com"):
        if p.path.startswith("/l/"):
            href = urllib.parse.parse_qs(p.query).get("uddg", [""])[0]
        else:
            return ""                      # y.js (ads) and other internal links
    if not href.lower().startswith(("http://", "https://")):
        return ""                          # also blocks javascript: and data: links
    return href


class DDGParser(HTMLParser):
    """Handles both the HTML and Lite layouts of DuckDuckGo's result pages."""
    TITLE = ("result__a", "result-link")
    SNIPPET = ("result__snippet", "result-snippet")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._cur = None
        self._cap = None       # "title" | "snippet" while collecting text
        self._tag = None
        self._depth = 0
        self._buf = []

    def _begin(self, kind, tag):
        self._cap, self._tag, self._depth, self._buf = kind, tag, 1, []

    def handle_starttag(self, tag, attrs):
        if self._cap:
            if tag == self._tag:
                self._depth += 1
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "a" and any(c in classes for c in self.TITLE):
            self._cur = {"title": "", "url": clean_url(a.get("href")), "snippet": ""}
            self.results.append(self._cur)
            self._begin("title", tag)
        elif self._cur is not None and any(c in classes for c in self.SNIPPET):
            self._begin("snippet", tag)

    def handle_endtag(self, tag):
        if self._cap and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
                if self._cap == "title" or not self._cur["snippet"]:
                    self._cur[self._cap] = text
                self._cap = None

    def handle_data(self, data):
        if self._cap:
            self._buf.append(data)


def _finish(results):
    seen, out = set(), []
    for r in results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            r["title"] = r["title"] or r["url"]
            out.append(r)
    return out


def _parse_ddg(body, status):
    parser = DDGParser()
    parser.feed(body)
    parser.close()
    results = _finish(parser.results)
    if results:
        return results
    if re.search(r"anomaly|captcha|unusual traffic|challenge", body, re.I):
        raise SearchError("DuckDuckGo is showing a captcha / rate limit for this "
                          "address - try again in a few minutes")
    if re.search(r"no\s+results", body, re.I):
        return []
    raise SearchError(f"couldn't find results in DuckDuckGo's page (HTTP {status}, "
                      f"{len(body)} bytes) - its layout may have changed")


def _ddg(url, timeout):
    status, body = _get(url, timeout)
    if status == 202:
        raise SearchError("DuckDuckGo is rate limiting this address (HTTP 202) - "
                          "try again in a few minutes")
    return _parse_ddg(body, status)


def ddg_html(q, timeout):
    return _ddg("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q), timeout)


def ddg_lite(q, timeout):
    return _ddg("https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(q), timeout)


# -------------------------------------------------------------- Wikipedia
def wikipedia(q, timeout):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": q,
        "srlimit": 10, "format": "json", "utf8": 1})
    _, body = _get(url, timeout, "application/json", ua=API_UA)
    try:
        items = json.loads(body)["query"]["search"]
    except (ValueError, KeyError, TypeError):
        raise SearchError("unexpected reply from Wikipedia")
    out = []
    for it in items:
        title = it.get("title", "")
        snippet = html.unescape(re.sub(r"<[^>]+>", "", it.get("snippet", "")))
        out.append({"title": title, "snippet": snippet,
                    "url": "https://en.wikipedia.org/wiki/"
                           + urllib.parse.quote(title.replace(" ", "_"))})
    return out


PROVIDERS = [("DuckDuckGo", ddg_html), ("DuckDuckGo Lite", ddg_lite), ("Wikipedia", wikipedia)]


# ------------------------------------------------------------- public API
def web_search(q, timeout=7):
    """Returns {"provider": name|None, "results": [...], "errors": [str, ...]}."""
    q = (q or "").strip()
    key = q.lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    errors, deadline = [], time.time() + TOTAL_BUDGET
    for name, fn in PROVIDERS:
        remaining = deadline - time.time()
        if remaining < 1:
            errors.append(f"{name}: skipped (out of time)")
            continue
        try:
            results = fn(q, min(timeout, remaining))
        except SearchError as e:
            errors.append(f"{name}: {e}")
            continue
        except Exception as e:                       # never let a parser bug kill the page
            errors.append(f"{name}: unexpected {type(e).__name__}: {e}")
            continue
        if results:
            out = {"provider": name, "results": results, "errors": errors}
            if len(_cache) > 200:
                _cache.clear()
            _cache[key] = (time.time(), out)
            return out
        errors.append(f"{name}: no results")
    return {"provider": None, "results": [], "errors": errors}


# -------------------------------------------------------------------- CLI
if __name__ == "__main__":
    args = sys.argv[1:]
    raw = "--raw" in args
    query = " ".join(a for a in args if a != "--raw")
    if not query:
        sys.exit("usage: python3 websearch.py [--raw] your search words")
    if raw:
        try:
            status, body = _get("https://html.duckduckgo.com/html/?q="
                                + urllib.parse.quote_plus(query), 8)
            print(f"[raw] HTTP {status}, {len(body)} bytes\n{body[:1500]}\n[/raw]\n")
        except SearchError as e:
            print(f"[raw] failed: {e}\n")
    out = web_search(query)
    print("provider:", out["provider"])
    for e in out["errors"]:
        print("  problem:", e)
    for i, r in enumerate(out["results"], 1):
        print(f"\n{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:160]}")
    if not out["results"]:
        print("\nNo results.")
