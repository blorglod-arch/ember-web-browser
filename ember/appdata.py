"""
Where Ember keeps its data (~/.ember): the encrypted vault and the search index.

Ember used to be called Pillo. If an old ~/.pillo folder exists and ~/.ember
doesn't, it is moved over automatically so saved logins and your index carry on.
"""
from pathlib import Path

DATA_DIR = Path.home() / ".ember"
_OLD_DIR = Path.home() / ".pillo"

if _OLD_DIR.exists() and not DATA_DIR.exists():
    try:
        _OLD_DIR.rename(DATA_DIR)
    except OSError:
        DATA_DIR = _OLD_DIR          # couldn't move it: keep using the old folder
