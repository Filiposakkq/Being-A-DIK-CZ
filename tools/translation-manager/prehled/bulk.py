"""Bulk operations: category (episode) suggestions and global approval of identical lines.

Both only *propose*; nothing changes until the caller applies the reviewed result.
"""
import posixpath
import re
from collections import Counter, defaultdict

from . import rpy
from .seasons import ACTIVE_EPISODES, episodes_of, season_of
from .store import assign_label, valid_assign
from .util import norm_ws

EP_RE = re.compile(r"(?<![a-z0-9])(?:episode|ep)[ _-]?0*(\d{1,2})(?!\d)")
UPDATE_RE = re.compile(r"(?<![a-z0-9])update[ _-]?0*(\d{1,2})(?!\d)")
SEASON_RE = re.compile(r"(?<![a-z0-9])season[ _-]?0*(\d)(?!\d)")
# File stems that belong to the whole game, not to one episode.
SHARED_STEMS = {"header", "options", "screens", "gui", "common", "title_screens", "fonts_czech"}


def _posix(rel):
    return rel.replace("\\", "/").lower()


def episode_hint(n, rows):
    """Rough % for an episode from file names alone (kept from the original tool; display only)."""
    pat = re.compile(rf"(?<![a-z])(?:episode|ep)[ _-]?0*{n}(?!\d)")
    d = t = 0
    for r in rows:
        if pat.search(_posix(r.name)):
            d += r.done
            t += r.total
    return f"≈ {d / t * 100:.0f} %" if t else ""


def _signals(rel):
    p = _posix(rel)
    eps = sorted({int(m) for m in EP_RE.findall(p)})
    updates = sorted({int(m) for m in UPDATE_RE.findall(p)})
    seasons = sorted({int(m) for m in SEASON_RE.findall(p)})
    return eps, updates, seasons


def suggest(names, current, known_assign=None):
    """Propose an assignment for every file in `names`.

    current:      {file: assignment} what the translator has set (manual values are protected)
    known_assign: the whole project's assignments, used to learn folder conventions

    Returns one dict per file:
      name, current, suggested ('' = none), confidence (high|medium|low|none),
      state: new | same | conflict | ambiguous | unknown | keep
      reason, candidates, overwrite (True when applying would replace a manual value)
    """
    known = dict(known_assign if known_assign is not None else current)
    by_dir = defaultdict(Counter)
    for f, v in known.items():
        if v:
            by_dir[posixpath.dirname(_posix(f))][v] += 1

    out = []
    for name in names:
        cur = current.get(name, "")
        eps, updates, seasons = _signals(name)
        valid = [e for e in eps if e in ACTIVE_EPISODES]
        invalid = [e for e in eps if e not in ACTIVE_EPISODES]
        season_dirs = [s for s in seasons if episodes_of(s)]
        allowed = {e for s in season_dirs for e in episodes_of(s)}
        sug, conf, reason, cands = "", "none", "", []
        season_conflict = False
        note = ""
        if invalid:
            note = f" (číslo epizody {', '.join(map(str, invalid))} v cestě není v aktivním rozsahu 1–{max(ACTIVE_EPISODES)})"

        if len(valid) == 1:
            ep = valid[0]
            sug, conf = f"ep:{ep}", "high"
            reason = f"Název nebo složka obsahuje „ep{ep}“."
            if allowed and ep not in allowed:
                conf, season_conflict = "low", True
                reason = (f"Cesta obsahuje epizodu {ep} (sezóna {season_of(ep)}), ale leží ve složce sezóny "
                          f"{', '.join(map(str, season_dirs))}.")
        elif len(valid) > 1:
            cands = [f"ep:{e}" for e in valid]
            in_season = [e for e in valid if not allowed or e in allowed]
            if len(in_season) == 1 and allowed:
                sug, conf = f"ep:{in_season[0]}", "medium"
                reason = f"V cestě je více epizod ({', '.join(map(str, valid))}); složka sezóny vybírá epizodu {in_season[0]}."
            else:
                reason = f"Nejednoznačné: cesta obsahuje více epizod ({', '.join(map(str, valid))})."
        elif len(updates) == 1 and updates[0] in ACTIVE_EPISODES:
            ep = updates[0]
            sug, conf = f"ep:{ep}", "medium"
            reason = f"Soubor „update{ep}“ odpovídá epizodě {ep} (konvence tohoto projektu)."
            if allowed and ep not in allowed:
                conf, season_conflict = "low", True
                reason += " Složka sezóny s tím ale nesedí."
        else:
            d = posixpath.dirname(_posix(name))
            sib = by_dir.get(d)
            stem = posixpath.splitext(posixpath.basename(_posix(name)))[0]
            if sib and len(sib) == 1 and next(iter(sib)):
                sug, conf = next(iter(sib)), "medium"
                reason = f"Ostatní soubory ve stejné složce jsou zařazené jako „{assign_label(sug)}“."
            elif stem in SHARED_STEMS:
                sug, conf = "gen", "medium"
                reason = "Název odpovídá souborům celé hry (hlavička, nastavení, obrazovky)."
            elif sib and len(sib) > 1:
                cands = [k for k, _ in sib.most_common()]
                reason = "Soubory ve stejné složce jsou zařazené do různých epizod."
            elif allowed:
                reason = (f"Složka patří do sezóny {', '.join(map(str, season_dirs))} (epizody "
                          f"{min(allowed)}–{max(allowed)}), konkrétní epizodu z cesty nelze určit.")
            else:
                reason = "Nelze odvodit z názvu ani ze složky." + note
        if sug and not valid_assign(sug):
            sug, conf = "", "none"

        if not sug and not cands:
            state = "keep" if cur else "unknown"
        elif not sug:
            state = "keep" if cur else "ambiguous"
        elif season_conflict:
            state = "conflict"
        elif cur and cur == sug:
            state = "same"
        elif cur:
            state = "conflict"
            reason += f" Ručně je nastaveno „{assign_label(cur)}“."
        else:
            state = "new"
        out.append({"name": name, "current": cur, "suggested": sug, "confidence": conf,
                    "state": state, "reason": reason, "candidates": cands,
                    "overwrite": bool(cur and sug and cur != sug)})
    return out


def apply_assignments(store, items):
    """Apply reviewed assignments in one undoable step.

    items: [{name, value, overwrite}] — a manual value is only replaced when overwrite is True.
    Returns {applied, skipped:[(name, reason)]}.
    """
    applied, skipped = [], []

    def go():
        for it in items:
            name, v = it["name"], it.get("value", "")
            if not valid_assign(v):
                skipped.append((name, "neplatné zařazení"))
                continue
            cur = store.assign.get(name, "")
            if cur == v:
                continue
            if cur and not it.get("overwrite"):
                skipped.append((name, "má ručně nastavené zařazení (přepsání nebylo potvrzeno)"))
                continue
            if v:
                store.assign[name] = v
            else:
                store.assign.pop(name, None)
            applied.append(name)
    store.change(f"Zařazení souborů ({len(items)})", ("assign",), go)
    return {"applied": applied, "skipped": skipped}


# ---------------------------------------------------------------- global approval

SCOPES = ("occurrence", "file", "project")


def approval_candidates(project, rel, line, scope="project", same_speaker=True):
    """Find lines that are identical to the chosen pending line and could be approved together.

    A match needs the same normalized source *and* translation. Everything else about the
    context is shown and decides the default checkbox:
      - a different speaker is unchecked (the same words can mean something else),
      - empty translations can never be approved,
      - lines that look like untranslated English are unchecked,
      - already approved lines are listed but not selectable.
    Returns {reference, scope, items:[...], counts}.
    """
    if scope not in SCOPES:
        raise ValueError("neznámý rozsah")
    ref = next((e for e in project.entries(rel) if e.line == line), None)
    if ref is None or not ref.pending:
        raise ValueError("Řádek není mezi nepřeloženými.")
    src, tgt = norm_ws(ref.source), norm_ws(ref.target)
    approved = project.store.approved
    files = [rel] if scope in ("occurrence", "file") else sorted(project.files, key=str.lower)
    items = []
    for f in files:
        done = approved.get(f, ())
        for e in project.entries(f):
            if not e.pending or norm_ws(e.source) != src or norm_ws(e.target) != tgt:
                continue
            if scope == "occurrence" and e.line != line:
                continue
            already = e.key in done
            same_who = norm_ws(e.who) == norm_ws(ref.who)
            reasons = []
            selectable, default = True, True
            if already:
                selectable = default = False
                reasons.append("už schváleno")
            if e.category == rpy.K_EMPTY:
                selectable = default = False
                reasons.append("prázdný překlad nelze schválit")
            if not same_who and same_speaker:
                default = False
                reasons.append(f"jiný mluvčí („{e.who or '—'}“ místo „{ref.who or '—'}“)")
            if e.category == rpy.K_ENGLISH and default:
                default = False
                reasons.append("vypadá jako nepřeložená angličtina")
            if e is ref:
                default = selectable
            items.append({"file": f, "line": e.line, "block": e.block, "who": e.who,
                          "text": e.target, "kind": rpy.KIND_CODE[e.category],
                          "key": [e.block, norm_ws(e.source)], "approved": already,
                          "selectable": selectable, "selected": default, "notes": reasons,
                          "is_reference": e is ref})
    return {"reference": {"file": rel, "line": line, "text": ref.target, "who": ref.who},
            "scope": scope, "items": items,
            "counts": {"total": len(items), "selected": sum(1 for i in items if i["selected"]),
                       "files": len({i["file"] for i in items})}}


def apply_approvals(project, selections, on=True, label=None):
    """Approve / un-approve [{file, key:[block, source]}] in one undoable step.

    Each selection is re-checked against the current parse, so a file that changed since the
    preview cannot get a stale approval. Returns {changed, skipped}.
    """
    store = project.store
    skipped = []
    plan = defaultdict(set)
    for sel in selections:
        f, key = sel["file"], (str(sel["key"][0]), norm_ws(str(sel["key"][1])))
        if f not in project.files:
            skipped.append((f, "neznámý soubor"))
            continue
        if on:
            ent = next((e for e in project.entries(f) if e.pending and e.key == key), None)
            if ent is None:
                skipped.append((f, "řádek se mezitím změnil – obnov soubory"))
                continue
            if ent.category == rpy.K_EMPTY:
                skipped.append((f, "prázdný překlad nelze schválit"))
                continue
        plan[f].add(key)
    changed = 0

    def go():
        nonlocal changed
        for f, keys in plan.items():
            cur = set(store.approved.get(f, set()))
            new = (cur | keys) if on else (cur - keys)
            changed += len(new ^ cur)
            if new:
                store.approved[f] = new
            else:
                store.approved.pop(f, None)
    n = sum(len(k) for k in plan.values())
    store.change(label or (f"{'Schválení' if on else 'Zrušení schválení'} {n} řádků"), ("approved",), go)
    return {"changed": changed, "skipped": skipped}


# ---------------------------------------------------------------- approval by rule

RULES = {
    "symbols": "Jen znaky (…, ?!, čísla) – nic k překladu",
    "interjections": "Citoslovce (Hmm, Ah, Haha, Wow, Ugh…) – v češtině stejná",
    "names": "Jen jména ze Slovníku (mluvčí, termíny)",
}
INTERJECTIONS = {"hm", "hmm", "hmmm", "mm", "mmm", "mhm", "ah", "aha", "ahh", "oh", "ooh", "uh", "uhm", "um", "umm",
                 "ugh", "ha", "haha", "hahaha", "hehe", "heh", "hihi", "wow", "whoa", "yay", "ow", "ouch", "argh",
                 "eh", "huh", "shh", "psst", "ok", "okay", "ahem", "pfft", "tsk", "tss", "boo", "bam", "pow", "zzz"}
_WORDS = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def _plain(text):
    return re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", text.replace("\\n", " "))


def name_words(glossary):
    """Lower-case words of every speaker name and glossary term (both the English and the Czech side)."""
    out = set()
    for code, g in glossary.items():
        for part in (code, g.get("n", "")):
            out.update(w.lower() for w in _WORDS.findall(part))
    return out


def rule_candidates(project, glossary, rules, rels=None):
    """Pending lines that a simple rule says need no translation. Nothing is changed.

    Returns {items:[{file, line, key, who, text, rule, selectable, selected, notes}], counts}.
    `rels` limits the search to those files (None / empty = the whole project).
    An already approved line is listed but not selectable; an empty translation never qualifies."""
    rules = [r for r in rules if r in RULES]
    names = name_words(glossary) if "names" in rules else set()
    approved = project.store.approved
    items, per_rule = [], Counter()
    files = [f for f in (rels or []) if f in project.files] if rels else sorted(project.files, key=str.lower)
    for f in sorted(files, key=str.lower):
        done = approved.get(f, ())
        for e in project.entries(f):
            if not e.pending or e.category == rpy.K_EMPTY:
                continue
            text = e.target or ""
            words = [w.lower() for w in _WORDS.findall(_plain(text))]
            hit = None
            if "symbols" in rules and e.category == rpy.K_SYMBOLS:
                hit = "symbols"
            elif words and "interjections" in rules and all(w in INTERJECTIONS for w in words):
                hit = "interjections"
            elif words and "names" in rules and len(words) <= 4 and all(w in names for w in words):
                hit = "names"
            if not hit:
                continue
            already = e.key in done
            per_rule[hit] += 1
            items.append({"file": f, "line": e.line, "block": e.block, "who": e.who, "text": text, "rule": hit,
                          "key": [e.block, norm_ws(e.source)], "approved": already,
                          "selectable": not already, "selected": not already,
                          "notes": ["už schváleno"] if already else []})
    return {"items": items, "rules": RULES, "files": len(files),
            "counts": {"total": len(items), "selectable": sum(1 for i in items if i["selectable"]),
                       "by_rule": dict(per_rule)}}
