"""Public progress data (progress.json, schema 2) — the single source of truth for the website.

Definitions (identical for the overall figure, seasons and episodes):
  - A "line" is one translation unit (see rpy.py); translated = done / total as in progress.csv.
  - Overall = every scanned file of the project, including shared ('Obecné') and unassigned files.
  - An episode / season = only the files assigned to its episodes ('Epizoda N' in prirazeni.csv).
  - overall = sum(episodes) + general + unassigned, which validate() checks before writing.
  - Season 3 is 'planned': it has no files, no figures and never enters any percentage.

The file deliberately contains no file names or paths. Keys of schema 1 (title, updated,
translation, proofreading, files, episodes[n,status,percent,files], history) are unchanged,
so an older website keeps working.
"""
import json
import re
from datetime import datetime

from . import history as hist
from .project import STATUS_LABELS, file_status, totals_of
from .seasons import ACTIVE_EPISODES, SEASONS, season_of
from .store import ep_of
from .util import WriteFailed, atomic_write_text

SCHEMA = 2


def pct(done, total):
    return round(done / total * 100, 1) if total else None


def block(done, total):
    return {"done": done, "total": total, "percent": pct(done, total)}


def _accumulate(rows):
    return (sum(r.done for r in rows), sum(r.total for r in rows), sum(r.corr for r in rows),
            len(rows), sum(1 for r in rows if r.todo == 0), sum(1 for r in rows if r.corr >= r.total))


def _group(rows, store):
    groups = {"general": [], "unassigned": []}
    eps = {n: [] for n in ACTIVE_EPISODES}
    for r in rows:
        v = store.assign.get(r.name, "")
        n = ep_of(v)
        if n in eps:
            eps[n].append(r)
        elif v == "gen":
            groups["general"].append(r)
        else:
            groups["unassigned"].append(r)
    return eps, groups


def stats_for(rows, store):
    """Structured statistics used by both the exporter and the manager's overview."""
    eps_rows, groups = _group(rows, store)
    episodes = []
    for n in ACTIVE_EPISODES:
        d, t, c, nf, nf_done, nf_proof = _accumulate(eps_rows[n])
        episodes.append({"n": n, "season": season_of(n), "status": store.episodes.get(n, "none"),
                         "translation": block(d, t), "proofreading": block(c, t),
                         "files": nf, "files_done": nf_done, "files_proofread": nf_proof})
    seasons = []
    for s in SEASONS:
        if s["status"] != "active":
            seasons.append({"n": s["n"], "status": s["status"]})
            continue
        mine = [e for e in episodes if e["season"] == s["n"]]
        d = sum(e["translation"]["done"] for e in mine)
        t = sum(e["translation"]["total"] for e in mine)
        c = sum(e["proofreading"]["done"] for e in mine)
        seasons.append({"n": s["n"], "status": "active", "episodes": list(s["episodes"]),
                        "translation": block(d, t), "proofreading": block(c, t),
                        "files": sum(e["files"] for e in mine),
                        "files_done": sum(e["files_done"] for e in mine),
                        "episodes_done": sum(1 for e in mine if e["status"] == "done"),
                        "episodes_total": len(mine)})
    out = {}
    for key, rs in groups.items():
        d, t, c, nf, nf_done, _p = _accumulate(rs)
        out[key] = {"translation": block(d, t), "proofreading": block(c, t), "files": nf}
    return {"episodes": episodes, "seasons": seasons, **out}


def build_progress(rows, store, history, title="", now=None, today=None):
    """The public progress.json as a dict."""
    t_done, total, c_done, tpct, cpct = totals_of(rows)
    counts = {k: 0 for k in STATUS_LABELS}
    for r in rows:
        counts[file_status(r.done, r.todo, r.total, r.corr)] += 1
    st = stats_for(rows, store)

    by_day = {}
    for ts, t, c in history.chart_points():
        by_day[ts.strftime("%Y-%m-%d")] = (t, c)      # last record of each day
    chart = [{"date": d, "translation": v[0], "proofreading": v[1]}
             for d, v in sorted(by_day.items())][-180:]

    est = hist.estimate(history.points(), t_done, total, today=today)

    def iso(d):
        return d.isoformat() if d else None
    estimate = {"status": est["status"], "remaining": est["remaining"],
                "pace_per_day": est["pace_per_day"], "eta": iso(est["eta"]),
                "eta_early": iso(est["eta_early"]), "eta_late": iso(est["eta_late"]),
                "confidence": est["confidence"], "basis_days": est["basis_days"],
                "days_with_data": est["days_with_data"]}

    episodes = []
    for e in st["episodes"]:                 # schema 1 keys first, then the schema 2 additions
        item = {"n": e["n"], "status": e["status"]}
        if e["files"]:
            item["percent"] = e["translation"]["percent"]
            item["files"] = e["files"]
        item.update(season=e["season"], translation=e["translation"], proofreading=e["proofreading"],
                    files_done=e["files_done"], files_total=e["files"],
                    files_proofread=e["files_proofread"])
        episodes.append(item)
    return {
        "schema": SCHEMA,
        "title": title or "",
        "updated": (now or datetime.now().astimezone()).isoformat(timespec="minutes"),
        "translation": block(t_done, total),
        "proofreading": block(c_done, total),
        "files": dict(counts, total=len(rows)),
        "scope": {"seasons": [s["n"] for s in SEASONS if s["status"] == "active"],
                  "episodes": list(ACTIVE_EPISODES),
                  "planned_seasons": [s["n"] for s in SEASONS if s["status"] == "planned"]},
        "seasons": st["seasons"],
        "episodes": episodes,
        "general": st["general"],
        "unassigned": st["unassigned"],
        "estimate": estimate,
        "history": chart,
    }


def validate_progress(data):
    """Return a list of problems (empty = safe to write / publish)."""
    p = []
    if not isinstance(data, dict):
        return ["Data nejsou objekt."]
    for key in ("translation", "proofreading"):
        b = data.get(key)
        if not isinstance(b, dict) or not all(k in b for k in ("done", "total", "percent")):
            p.append(f"Chybí blok „{key}“.")
            continue
        if not (isinstance(b["done"], int) and isinstance(b["total"], int)) or b["done"] < 0 or b["done"] > b["total"]:
            p.append(f"{key}: neplatné hodnoty done/total ({b['done']}/{b['total']}).")
        if b["percent"] is not None and not (0 <= b["percent"] <= 100):
            p.append(f"{key}: procenta mimo rozsah ({b['percent']}).")
    eps, seasons = data.get("episodes"), data.get("seasons")
    if not isinstance(eps, list) or not isinstance(seasons, list):
        return p + ["Chybí seznam epizod nebo sezón."]
    nums = [e.get("n") for e in eps]
    if nums != list(ACTIVE_EPISODES):
        p.append(f"Epizody {nums} neodpovídají aktivnímu rozsahu {list(ACTIVE_EPISODES)}.")
    for e in eps:
        if e.get("season") != season_of(e.get("n")):
            p.append(f"Epizoda {e.get('n')} je v sezóně {e.get('season')}, správně {season_of(e.get('n'))}.")
        t = e.get("translation", {})
        if t.get("done", 0) > t.get("total", 0):
            p.append(f"Epizoda {e.get('n')}: přeloženo víc než celkem.")
    by_n = {s.get("n"): s for s in seasons}
    for s in SEASONS:
        got = by_n.get(s["n"])
        if got is None:
            p.append(f"Chybí sezóna {s['n']}.")
        elif got.get("status") != s["status"]:
            p.append(f"Sezóna {s['n']} má stav {got.get('status')}, správně {s['status']}.")
        elif s["status"] == "planned" and set(got) - {"n", "status"}:
            p.append(f"Plánovaná sezóna {s['n']} nesmí mít žádná čísla.")
    for s in seasons:
        if s.get("status") == "active":
            mine = [e for e in eps if e.get("season") == s["n"]]
            if sum(e["translation"]["done"] for e in mine) != s["translation"]["done"] \
                    or sum(e["translation"]["total"] for e in mine) != s["translation"]["total"]:
                p.append(f"Sezóna {s['n']}: součet epizod nesedí se sezónou.")
    try:
        parts_done = sum(e["translation"]["done"] for e in eps) + data["general"]["translation"]["done"] \
            + data["unassigned"]["translation"]["done"]
        parts_total = sum(e["translation"]["total"] for e in eps) + data["general"]["translation"]["total"] \
            + data["unassigned"]["translation"]["total"]
        if (parts_done, parts_total) != (data["translation"]["done"], data["translation"]["total"]):
            p.append(f"Součet epizod + obecné + nezařazené ({parts_done}/{parts_total}) nesedí s celkem "
                     f"({data['translation']['done']}/{data['translation']['total']}).")
    except (KeyError, TypeError):
        p.append("Chybí bloky general / unassigned.")
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return p + [f"Data nelze zapsat jako JSON: {e}"]
    if re.search(r"\.rpy\b", text):
        p.append("Veřejná data nesmí obsahovat názvy souborů (.rpy).")
    return p


def render(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def write_local(path, data, backup_dir=None):
    """Validate and write progress.json atomically. Raises ValueError (invalid) / WriteFailed."""
    problems = validate_progress(data)
    if problems:
        raise ValueError("Export neprošel kontrolou: " + "; ".join(problems))
    atomic_write_text(path, render(data), newline="\n", backup_dir=backup_dir)
