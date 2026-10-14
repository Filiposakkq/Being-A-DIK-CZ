"""Application settings, stored in one JSON file that does not depend on the working directory.

  Windows: %APPDATA%\\PrehledPrekladu\\config.json
  other:   ~/.config/prehled-prekladu/config.json
  override the folder with the PREHLED_CONFIG_DIR environment variable (used by the tests).

Holds: the remembered project folder, the editor, validation thresholds, UI preferences and the
website settings that used to live in a hand-edited web.json (see migrate_web_json).
The file never contains secrets: git authenticates through the user's own git credentials.
"""
import copy
import json
import os
import sys
from pathlib import Path

from .util import WriteFailed, atomic_write_text

DEFAULTS = {
    "version": 1,
    "project_dir": "",
    "skip_files": ["common.rpy", "fonts_czech.rpy"],
    "count_symbol_only_as_done": False,
    "editor": {"preferred": "auto", "custom": ""},     # auto | vscode | notepadpp | custom | system
    "validation": {
        "enabled": True,
        "show_info": False,
        "length": {"enabled": True, "min_source_chars": 12, "max_ratio": 2.2, "min_ratio": 0.45,
                   "min_extra_chars": 25, "min_missing_chars": 18},
    },
    "web": {"repo": "", "path": "web/progress.json", "title": "", "migrated_from": ""},
    "ui": {},
}


def config_dir():
    env = os.environ.get("PREHLED_CONFIG_DIR")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        return Path(base) / "PrehledPrekladu" if base else Path.home() / "PrehledPrekladu"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "prehled-prekladu"


def _merge(base, over):
    """Deep-merge `over` onto a copy of `base`, keeping only values of a compatible type;
    unknown keys of `over` are kept (a newer version may have written them)."""
    out = copy.deepcopy(base)
    if not isinstance(over, dict):
        return out
    for k, v in over.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        elif k not in out:
            out[k] = v
        elif isinstance(v, type(out[k])) or (isinstance(out[k], (int, float)) and isinstance(v, (int, float))
                                              and not isinstance(v, bool)):
            out[k] = v
    return out


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "config.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load_error = ""

    def load(self):
        self.load_error = ""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.data = _merge(DEFAULTS, raw)
        except FileNotFoundError:
            self.data = copy.deepcopy(DEFAULTS)
        except (OSError, ValueError) as e:
            # keep the broken file for inspection; run with defaults instead of crashing
            self.load_error = f"Nastavení nelze načíst ({e}); používám výchozí hodnoty."
            self.data = copy.deepcopy(DEFAULTS)
        return self

    def save(self):
        text = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.path, text, newline="\n", backup_dir=self.path.parent / "backups")

    def get(self, dotted, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted, value):
        parts = dotted.split(".")
        cur = self.data
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def update(self, patch):
        """Merge a (validated) patch dict and save."""
        self.data = _merge(self.data, patch)
        self.save()

    def public(self):
        return copy.deepcopy(self.data)


def migrate_web_json(cfg, data_dir):
    """Import the legacy web.json into the application config.

    Only fills settings that are still empty, never overwrites, never deletes web.json
    (the translator may want to keep it as a backup). The legacy keys `push` and
    `allow_main` are intentionally not migrated: publishing is now always confirmed by hand.
    Returns a short message when something was migrated, else ''.
    """
    legacy = Path(data_dir) / "web.json"
    if cfg.get("web.repo") or not legacy.is_file():
        return ""
    try:
        old = json.loads(legacy.read_text(encoding="utf-8-sig"))
        repo = str(old["repo"]).strip()
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if not repo:
        return ""
    cfg.set("web.repo", repo)
    if old.get("path"):
        cfg.set("web.path", str(old["path"]))
    if old.get("title"):
        cfg.set("web.title", str(old["title"]))
    cfg.set("web.migrated_from", str(legacy))
    cfg.save()
    return (f"Nastavení webu bylo převzato z {legacy.name} do aplikace. Soubor můžeš ponechat jako zálohu "
            "nebo smazat – aplikace ho už nepotřebuje. Publikování se teď vždy potvrzuje ručně.")
