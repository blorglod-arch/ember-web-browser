"""
Ember vault: encrypted local password storage.

- Master password -> key via scrypt (memory-hard, slow to brute force)
- Data encrypted + authenticated with Fernet (AES-128-CBC + HMAC-SHA256)
- Stored at ~/.ember/vault.json (file mode 600), written atomically with a .bak copy
- Nothing is ever sent over the network

Requires:  pip install cryptography
"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import string
import time
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from appdata import DATA_DIR

VAULT_FILE = DATA_DIR / "vault.json"
N, R, P = 2 ** 15, 8, 1          # scrypt cost (about 32 MB RAM, ~100 ms)
MAX_N = 2 ** 20                  # refuse absurd values from a tampered file


class VaultError(Exception):
    pass


class WrongPassword(VaultError):
    pass


def _derive(master, kdf):
    raw = hashlib.scrypt(master.encode("utf-8"), salt=kdf["salt"], n=kdf["n"],
                         r=kdf["r"], p=kdf["p"], maxmem=256 * 1024 * 1024, dklen=32)
    return base64.urlsafe_b64encode(raw)


def host_of(text):
    """'https://www.example.com/login' or 'example.com' -> 'example.com'"""
    text = (text or "").strip().lower()
    if not text:
        return ""
    if "://" not in text:
        text = "//" + text
    try:
        host = urlparse(text).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def generate_password(length=20, symbols=True):
    length = max(8, min(int(length), 128))
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if symbols:
        pools.append("!@#$%^&*()-_=+[]{};:,.?")
    chars = "".join(pools)
    while True:  # retry until every character class is present
        pw = "".join(secrets.choice(chars) for _ in range(length))
        if all(any(c in pool for c in pw) for pool in pools):
            return pw


class Vault:
    def __init__(self, path=VAULT_FILE):
        self.path = Path(path)
        self.entries = []
        self._key = None
        self._kdf = None

    # ---- state ----
    @property
    def unlocked(self):
        return self._key is not None

    def exists(self):
        return self.path.exists()

    def lock(self):
        self._key = None
        self._kdf = None
        self.entries = []

    # ---- create / unlock ----
    def create(self, master):
        if self.exists():
            raise VaultError("A vault already exists.")
        self._kdf = {"salt": os.urandom(16), "n": N, "r": R, "p": P}
        self._key = _derive(master, self._kdf)
        self.entries = []
        self.save()

    def unlock(self, master):
        try:
            blob = json.loads(self.path.read_text())
            kdf = {"salt": base64.b64decode(blob["salt"]), "n": int(blob["n"]),
                   "r": int(blob["r"]), "p": int(blob["p"])}
            if not (2 <= kdf["n"] <= MAX_N) or kdf["r"] > 32 or kdf["p"] > 8:
                raise VaultError("Vault settings look invalid.")
            key = _derive(master, kdf)
            data = Fernet(key).decrypt(blob["data"].encode())
            entries = json.loads(data)
        except InvalidToken:
            raise WrongPassword("Wrong master password.")
        except (OSError, ValueError, KeyError, TypeError):
            raise VaultError("The vault file is unreadable or corrupted.")
        self._kdf, self._key, self.entries = kdf, key, entries

    def change_master(self, new_master):
        if not self.unlocked:
            raise VaultError("Vault is locked.")
        self._kdf = {"salt": os.urandom(16), "n": N, "r": R, "p": P}
        self._key = _derive(new_master, self._kdf)
        self.save()

    # ---- persistence ----
    def save(self):
        if not self.unlocked:
            raise VaultError("Vault is locked.")
        blob = {
            "version": 1,
            "kdf": "scrypt",
            "salt": base64.b64encode(self._kdf["salt"]).decode(),
            "n": self._kdf["n"], "r": self._kdf["r"], "p": self._kdf["p"],
            "data": Fernet(self._key).encrypt(json.dumps(self.entries).encode()).decode(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(blob, f)
            f.flush()
            os.fsync(f.fileno())
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".bak"))
        os.replace(tmp, self.path)

    # ---- entries ----
    def add(self, site, username, password, notes=""):
        entry = {"id": secrets.token_hex(8), "site": site.strip(),
                 "username": username, "password": password, "notes": notes,
                 "updated": int(time.time())}
        self.entries.append(entry)
        self.save()
        return entry

    def update(self, entry_id, **fields):
        for e in self.entries:
            if e["id"] == entry_id:
                e.update(fields)
                e["updated"] = int(time.time())
                self.save()
                return e
        raise VaultError("Entry not found.")

    def delete(self, entry_id):
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        self.save()

    def find_for_url(self, url):
        host = host_of(url)
        if not host:
            return []
        out = []
        for e in self.entries:
            eh = host_of(e["site"])
            if eh and (host == eh or host.endswith("." + eh)):
                out.append(e)
        return out
