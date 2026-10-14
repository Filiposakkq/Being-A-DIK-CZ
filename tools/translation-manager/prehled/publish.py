"""Publishing progress.json to the website repository — preview first, publish only on confirmation.

Generating the data (export.py) and publishing it are separate steps:

  plan(...)     read-only. Describes exactly what would happen: repository, branch, target file,
                what changes, the git commands, warnings (e.g. "push to main deploys the site").
  publish(...)  runs only with the token returned by plan() *and* the confirmed branch name.
                If the data or the repository changed after the preview, it refuses.

Safety properties:
  * nothing is pushed without publish(); there is no "push on exit" any more;
  * only the one data file is added and committed (other changes in the repo are untouched);
  * `git pull --ff-only` (no rebase / autostash) so the repo's working tree is never rewritten;
  * the file is written atomically and re-read to verify it;
  * when the push fails, the local commit and the file are rolled back, so a failed publish
    leaves the repository as it was.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from .util import WriteFailed, atomic_write_bytes

NOWIN = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
COMMIT_MESSAGE = "chore(translation): update progress data"
PROTECTED_BRANCHES = ("main", "master")


class PublishError(Exception):
    pass


def _git(repo, *args, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    cmd = ["git", *(["-C", str(repo)] if repo else []), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, **NOWIN)
    except FileNotFoundError:
        raise PublishError("Git není nainstalovaný nebo není v PATH (https://git-scm.com).") from None
    except subprocess.TimeoutExpired:
        raise PublishError("Git neodpověděl včas (přihlášení? síť?).") from None


def _tail(r):
    return (r.stderr or r.stdout or "").strip()[-300:]


def default_clone_dir(spec):
    name = spec.rstrip("/").split("/")[-1].removesuffix(".git") or "repo"
    return Path.home() / ".progress-web" / name


def repo_url(spec):
    spec = spec.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", spec) and not re.match(r"^[A-Za-z]:", spec):
        return f"https://github.com/{spec}.git"
    if re.match(r"^(https?://|git@|file:)", spec):
        return spec
    return None


def locate_repo(spec):
    """(path, url): a local folder if there is one, or the default clone folder and the URL to clone."""
    p = Path(spec).expanduser()
    if p.is_dir():
        return p, None
    url = repo_url(spec)
    if url is None:
        return None, None
    return default_clone_dir(url), url


def clean_target(rel):
    """Validate the target path inside the repository (relative, no '..', a .json file)."""
    rel = str(rel).replace("\\", "/").strip()
    pp = PurePosixPath(rel)
    if not rel or pp.is_absolute() or ".." in pp.parts or re.match(r"^[A-Za-z]:", rel) or pp.suffix.lower() != ".json":
        raise PublishError(f"Neplatná cesta k souboru v repozitáři: {rel!r} (musí být relativní cesta k .json).")
    return str(pp)


def canonical(data):
    """Content identity for the confirmation token: the data without its timestamp."""
    d = dict(data)
    d.pop("updated", None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def _summ(d):
    try:
        return {"translation": d["translation"]["percent"], "proofreading": d["proofreading"]["percent"],
                "updated": d.get("updated")}
    except (KeyError, TypeError):
        return None


def plan(web, data, text):
    """Read-only description of a publish. `web` is the config's web section, `text` the JSON text."""
    if not web.get("repo"):
        raise PublishError("Web není nastavený – vyplň repozitář v Nastavení.")
    target = clean_target(web.get("path", ""))
    path, url = locate_repo(web["repo"])
    if path is None:
        raise PublishError(f"Repozitář „{web['repo']}“ není složka ani adresa GitHubu.")
    info = {"repo": web["repo"], "repo_path": str(path), "url": url, "target": target,
            "will_clone": url is not None and not (path / ".git").is_dir(),
            "branch": "", "remote": "", "upstream": "", "dirty": [], "current": None,
            "changed": True, "blockers": [], "warnings": [], "commands": [],
            "new": _summ(data)}
    info["token"] = hashlib.sha256((canonical(data) + "|" + str(path) + "|" + target).encode()).hexdigest()[:16]
    if info["will_clone"]:
        info["warnings"].append("Repozitář ještě není stažený. Při publikování se naklonuje z "
                                f"{url} a data se pošlou do jeho výchozí větve (obvykle main = ostrý web).")
        info["commands"] = [f"git clone {url} \"{path}\"", f"zapsat {target}", f"git add -- {target}",
                            f"git commit -m \"{COMMIT_MESSAGE}\" -- {target}", "git push"]
        return info
    if not (path / ".git").exists():
        raise PublishError(f"Složka není git repozitář: {path}")
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0:
        raise PublishError("Git repozitář nelze přečíst: " + _tail(branch))
    info["branch"] = branch.stdout.strip()
    if info["branch"] == "HEAD":
        info["blockers"].append("Repozitář je v detached HEAD – přepni se na větev.")
    up = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode == 0:
        info["upstream"] = up.stdout.strip()
    else:
        info["blockers"].append(f"Větev {info['branch']} nemá nastavenou vzdálenou větev (upstream) – push by nikam nesměřoval.")
    rem = _git(path, "remote", "get-url", "origin")
    info["remote"] = rem.stdout.strip() if rem.returncode == 0 else ""
    st = _git(path, "status", "--porcelain")
    if st.returncode == 0:
        info["dirty"] = [l[3:] for l in st.stdout.splitlines() if l[3:].replace("\\", "/") != target][:20]
    f = path / target
    if f.is_file():
        try:
            cur = json.loads(f.read_text(encoding="utf-8-sig"))
            info["current"] = _summ(cur)
            info["changed"] = canonical(cur) != canonical(data)
        except (OSError, ValueError):
            info["warnings"].append("Stávající soubor v repozitáři nejde přečíst; bude přepsán.")
    else:
        info["warnings"].append("Soubor v repozitáři zatím neexistuje, bude vytvořen.")
    if info["branch"] in PROTECTED_BRANCHES:
        info["warnings"].append(f"Push do větve {info['branch']} nasadí web na ostro (Cloudflare Workers).")
    if info["dirty"]:
        info["warnings"].append(f"V repozitáři jsou i jiné neuložené změny ({len(info['dirty'])}); publikování se jich nedotkne.")
    if not info["changed"]:
        info["warnings"].append("Publikovaná data se od aktuálních neliší (kromě času) – není co publikovat.")
    info["commands"] = ["git pull --ff-only", f"zapsat {target}", f"git add -- {target}",
                        f"git commit -m \"{COMMIT_MESSAGE}\" -- {target}", "git push"]
    return info


def publish(web, data, text, token, confirmed_branch):
    """Run the publish. Raises PublishError (nothing or only a reverted state left behind)."""
    info = plan(web, data, text)
    if token != info["token"]:
        raise PublishError("Data nebo repozitář se od náhledu změnily – otevři náhled znovu.")
    if info["blockers"]:
        raise PublishError(" ".join(info["blockers"]))
    path, target = Path(info["repo_path"]), info["target"]
    log = []
    if info["will_clone"]:
        if confirmed_branch != "*clone*":
            raise PublishError("Klonování a publikování nebylo potvrzeno.")
        path.parent.mkdir(parents=True, exist_ok=True)
        r = _git(None, "clone", info["url"], str(path), timeout=600)
        if r.returncode != 0:
            raise PublishError("git clone selhal: " + _tail(r))
        log.append("Repozitář naklonován.")
        info = plan(web, data, text)
        if info["blockers"]:
            raise PublishError(" ".join(info["blockers"]))
    elif confirmed_branch != info["branch"]:
        raise PublishError(f"Potvrzená větev „{confirmed_branch}“ nesouhlasí s aktuální „{info['branch']}“.")
    if not info["changed"] and not info["will_clone"]:
        return {"ok": True, "message": "Beze změny – na webu je už aktuální stav.", "log": log}

    r = _git(path, "pull", "--ff-only", timeout=300)
    if r.returncode != 0:
        raise PublishError("git pull --ff-only selhal (nic se nezměnilo): " + _tail(r))
    dest = path / target
    before = dest.read_bytes() if dest.is_file() else None
    payload = text.encode("utf-8")
    try:
        json.loads(payload.decode("utf-8"))
        atomic_write_bytes(dest, payload)
        if json.loads(dest.read_text(encoding="utf-8")).get("schema") != data.get("schema"):
            raise PublishError("Zapsaný soubor neprošel kontrolou.")
    except (WriteFailed, ValueError) as e:
        _restore(dest, before)
        raise PublishError(f"Soubor v repozitáři nelze zapsat: {e}") from e
    except PublishError:
        _restore(dest, before)
        raise

    def rollback(sha=None):
        if sha:
            head = _git(path, "rev-parse", "HEAD").stdout.strip()
            if head == sha:
                _git(path, "reset", "--soft", "HEAD~1")
        _git(path, "reset", "-q", "--", target)
        _restore(dest, before)

    r = _git(path, "add", "--", target)
    if r.returncode != 0:
        rollback()
        raise PublishError("git add selhal: " + _tail(r))
    if _git(path, "diff", "--cached", "--quiet", "--", target).returncode == 0:
        rollback()
        return {"ok": True, "message": "Beze změny – na webu je už aktuální stav.", "log": log}
    r = _git(path, "commit", "-m", COMMIT_MESSAGE, "--", target)
    if r.returncode != 0:
        rollback()
        raise PublishError("git commit selhal (soubor vrácen do původního stavu): " + _tail(r))
    sha = _git(path, "rev-parse", "HEAD").stdout.strip()
    r = _git(path, "push", timeout=300)
    if r.returncode != 0:
        rollback(sha)
        raise PublishError("git push selhal. Lokální commit i soubor byly vráceny do původního stavu: " + _tail(r))
    return {"ok": True, "message": f"Publikováno do větve {info['branch'] or 'výchozí'} ({sha[:7]}).",
            "log": log, "commit": sha}


def _restore(dest, before):
    try:
        if before is None:
            if dest.exists():
                dest.unlink()
        else:
            atomic_write_bytes(dest, before)
    except OSError:
        pass
