# Ember

A small, fast, Dillo-style web browser written in Python. No JavaScript, no tracking, and links always open **inside** Ember, never in Chrome or any other browser.

Ember (formerly *Pillo*) comes with its own start page, a built-in search engine, and an encrypted password manager.

## Features

- **Lightweight rendering** with [tkinterweb](https://pypi.org/project/tkinterweb/) (Tkhtml). Plain HTML and CSS only, no JavaScript.
- **Modern dark UI** with a flat toolbar, address bar and status bar.
- **Custom start page** served locally at `http://127.0.0.1:8080/`, with a clock, greeting, search box and shortcut tiles.
- **Search built in**
  - Web results from DuckDuckGo, shown on Ember's own page with ads removed. It falls back to DuckDuckGo Lite, then Wikipedia.
  - A personal index: crawl sites you care about and search them offline-style, with ranked results and highlighted snippets.
- **Password manager** with a master password, generator, search, clipboard auto-clear, idle auto-lock and best-effort autofill.
- **Own icon and dock entry** so it doesn't show up as "tk".

## Requirements

- Python 3.9 or newer, with Tk (`tkinter`)
- `tkinterweb` and `cryptography` (pip packages)
- Linux, macOS or Windows (developed and tested on Linux)

On Debian/Ubuntu, install Tk if it's missing:

```
sudo apt install python3-tk
```

## Install

Put all the files from this folder together, then install the two packages:

```
pip install tkinterweb cryptography
```

If pip refuses on a system-managed Python, add `--break-system-packages`, or use a virtual environment:

```
python3 -m venv .venv
. .venv/bin/activate
pip install tkinterweb cryptography
```

## Run

```
python3 ember.py
```

Open a specific address straight away:

```
python3 ember.py https://example.com
```

To get the Ember name and flame icon in your dock and app menu (instead of the generic "tk" gear), run this once, then restart Ember:

```
python3 ember.py --install
```

Run `--install` again if you ever move the folder. If the dock still shows the old icon, log out and back in once.

## Using Ember

### Address bar

| You type | What happens |
| --- | --- |
| `example.com` or `https://example.com` | Opens that page |
| `some words` | Searches the web, plus your own index |
| `!w some words` | Opens DuckDuckGo Lite directly |

### Keyboard shortcuts

| Keys | Action |
| --- | --- |
| Ctrl+L | Focus the address bar |
| Alt+Left / Alt+Right | Back / forward |
| F5 | Reload |
| Esc | Stop loading |
| Ctrl+Shift+P | Open the password manager |
| Ctrl+Shift+F | Autofill the login on this page |
| Ctrl+Q | Quit |

### Start page

The start page shows shortcut tiles. To use your own, create a `links.json` next to `homeserver.py`:

```json
[
  {"name": "Wikipedia", "url": "https://en.wikipedia.org"},
  {"name": "Hacker News", "url": "https://news.ycombinator.com"}
]
```

### Search

Searching shows web results first. If your personal index has matches, they appear on top under **From your index**, and the **My index** tab shows all of them.

**Building your own index:** open the start page, click **Manage search index**, enter a site address, and click **Crawl site**. You can set the maximum number of pages and how deep to follow links. The crawler:

- stays on the site you entered
- obeys `robots.txt`
- waits 1 second between pages
- refuses local and private network addresses

You can also crawl and search from a terminal:

```
python3 engine.py crawl https://example.com --depth 2 --max 200
python3 engine.py search some words
python3 engine.py stats
```

Because the crawler reads plain HTML, sites that need JavaScript to show their content will index thinly.

### Password manager

Click **Keys** in the toolbar (or press Ctrl+Shift+P). The first time, you create a master password of at least 10 characters. **It can't be recovered if you forget it.**

- Add, edit, delete and search logins, with a built-in password generator.
- Copy a username or password. Copied passwords are cleared from the clipboard after 30 seconds.
- The vault locks itself after 5 minutes of inactivity.
- **Autofill** is best-effort. If Ember can't fill a page's form, it copies the password to the clipboard and shows the username in the status bar.

## Files

| File | Purpose |
| --- | --- |
| `ember.py` | The browser window and toolbar. **Start here.** |
| `homeserver.py` | Local server for the start page, search pages and index manager |
| `websearch.py` | Web search (DuckDuckGo, DuckDuckGo Lite, Wikipedia fallback) |
| `engine.py` | Crawler, SQLite full-text index and ranked search |
| `vault.py` | Encrypted password storage |
| `passmanager.py` | Password manager windows and autofill |
| `appdata.py` | Data folder location (and migration from the old `~/.pillo`) |
| `logo.png`, `logo-64.png`, `logo.svg` | The Ember logo and icons |

Ember starts the local server itself, so `python3 ember.py` is the only command you need.

## Your data

Everything Ember stores lives in `~/.ember/`:

- `vault.json`: your encrypted logins (with a `.bak` copy of the previous save)
- `index.db`: your personal search index

If you used the old Pillo name, the first run moves `~/.pillo` to `~/.ember` automatically, so your logins and index carry over.

## Security notes

- **Vault:** the master password is turned into a key with scrypt, and the data is encrypted and authenticated with Fernet. The file is stored with owner-only permissions. Nothing is sent over the network.
- **Local server:** it listens only on `127.0.0.1`, checks the `Host` header, and requires a per-session token for crawl, stop and remove actions, so other websites can't trigger them.
- **Crawler:** it won't fetch localhost or private-network addresses, including through redirects.
- **Privacy:** your search words are sent to DuckDuckGo (or Wikipedia if DuckDuckGo is unavailable). Nothing else leaves your machine except the pages you visit and the sites you crawl.

## Troubleshooting

**The start page or search looks old or wrong.** An older copy of Ember or its server may still be running and holding port 8080. Stop everything and start fresh:

```
pkill -f ember.py; pkill -f homeserver.py
python3 ember.py
```

**Web results are missing or an error box appears.** DuckDuckGo sometimes shows a captcha or changes its page layout. Check what's happening from a terminal:

```
python3 websearch.py hello world
python3 websearch.py --raw hello world
```

The first command shows which provider answered and any problems. The second also prints the raw reply, which helps fix the parser if the layout changed.

**`ModuleNotFoundError: tkinterweb` or `cryptography`.** Install the packages as shown in [Install](#install).

**`ModuleNotFoundError: tkinter`.** Install Tk for your system (on Debian/Ubuntu: `sudo apt install python3-tk`).

## Limitations

- No JavaScript, so web apps and sites that depend on it won't work fully.
- Rendering is by Tkhtml, an older engine with limited modern CSS support. Many sites will look plain.
- No tabs, bookmarks or downloads yet.
- Ember can't offer to save a password when you submit a login form. Add logins in the password manager.
- The search engine only indexes sites you crawl. The web results come from DuckDuckGo.

## Under the hood

Ember is written entirely in Python and uses only the standard library plus `tkinterweb` and `cryptography`. Underneath, it relies on Tcl/Tk and Tkhtml for the window and page rendering, SQLite for the search index, and OpenSSL for encryption.
