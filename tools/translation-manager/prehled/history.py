"""historie.csv: the progress log, and completion estimates computed from it.

historie.csv columns:  datum;prelozeno;celkem;procenta;korekce;korekce_procenta
Existing rows are never edited except the newest one of the running session (a session keeps
refreshing "its" row while the translator works, exactly as the original tool did).
"""
from datetime import date, datetime, timedelta

from .util import read_rows, write_csv

HEADER = ["datum", "prelozeno", "celkem", "procenta", "korekce", "korekce_procenta"]
STAMP_FORMAT = "%Y-%m-%d %H:%M"

# Estimate requirements — deliberately conservative.
MIN_SPAN_DAYS = 7        # history must cover at least a week
MIN_DAYS_WITH_DATA = 3   # ... on at least three different days
WINDOW_DAYS = 28         # pace is measured over the most recent four weeks
HORIZON_DAYS = 365 * 5   # further than this is not a forecast, it is noise


def _num(s):
    return float(str(s).replace(",", "."))


class History:
    def __init__(self, path, backup_dir=None):
        self.path = path
        self.backup_dir = backup_dir
        self.session_row = False   # did this session already add / adopt a row?

    # ------------------------------------------------------------ reading
    def rows(self):
        """Raw rows without header (padded to the full width)."""
        raw = read_rows(self.path)[1:]
        return [r + [""] * (len(HEADER) - len(r)) for r in raw]

    def points(self):
        """[(datetime, translated, total, proofread)] for every parsable row, oldest first."""
        out = []
        for r in self.rows():
            try:
                out.append((datetime.strptime(r[0], STAMP_FORMAT), int(float(_num(r[1]))),
                            int(float(_num(r[2]))), int(float(_num(r[4]))) if r[4] != "" else 0))
            except (ValueError, IndexError):
                continue
        return out

    def chart_points(self):
        """[(datetime, translation %, proofreading %)] — what the website chart plots."""
        out = []
        for r in self.rows():
            try:
                ts = datetime.strptime(r[0], STAMP_FORMAT)
                out.append((ts, _num(r[3]), _num(r[5]) if r[5] != "" else 0.0))
            except (ValueError, IndexError):
                continue
        return out

    # ------------------------------------------------------------ writing
    def record(self, stamp, t_done, total, tpct, c_done, cpct):
        """Log the current state. Appends one row per session (and only when something changed),
        afterwards the session's own row is updated. Returns True when the file was written."""
        body = self.rows()
        entry = [stamp, str(t_done), str(total), f"{tpct:.1f}", str(c_done), f"{cpct:.1f}"]
        if body and body[-1][1:3] + [body[-1][4]] == entry[1:3] + [entry[4]]:
            return False                               # nothing changed since the last row
        if self.session_row and body:
            body[-1] = entry
        else:
            body.append(entry)
            self.session_row = True
        write_csv(self.path, [HEADER] + body, self.backup_dir)
        return True


# ---------------------------------------------------------------- estimates

def daily_series(points):
    """Last record of every calendar day: [(date, translated, total)] oldest first."""
    by_day = {}
    for ts, done, total, _corr in points:
        by_day[ts.date()] = (done, total)
    return [(d, v[0], v[1]) for d, v in sorted(by_day.items())]


def _value_at(series, day):
    """Translated count on `day` (step function: last known value on or before it)."""
    val = None
    for d, done, _t in series:
        if d <= day:
            val = done
        else:
            break
    return val


def estimate(points, done_now, total_now, today=None, key=None):
    """Projected completion of the *remaining* work from the recent pace.

    Returns a dict. status is 'ok' only when the history supports a forecast; otherwise it names
    the reason and no date is given. Nothing is extrapolated from a handful of hours of data.
    """
    today = today or date.today()
    remaining = max(0, total_now - done_now)
    out = {"status": "insufficient_data", "remaining": remaining, "pace_per_day": None,
           "eta": None, "eta_early": None, "eta_late": None, "confidence": None,
           "basis_days": 0, "days_with_data": 0, "reason": ""}
    if remaining == 0:
        out.update(status="complete", reason="Vše je přeloženo.")
        return out
    series = daily_series(points)
    if not series:
        out["reason"] = "Historie je prázdná – odhad zatím nejde spočítat."
        return out
    window_start = today - timedelta(days=WINDOW_DAYS)
    in_window = [s for s in series if s[0] >= window_start]
    # baseline: last known value before the window, else the oldest record we have
    before = [s for s in series if s[0] < window_start]
    base = before[-1] if before else series[0]
    used = ([base] if base not in in_window else []) + in_window
    days_with_data = len({s[0] for s in used})
    span = (today - base[0]).days
    out["basis_days"], out["days_with_data"] = span, days_with_data
    if span < MIN_SPAN_DAYS or days_with_data < MIN_DAYS_WITH_DATA:
        covers = "jen jeden den" if span < 1 else f"{span} dní"
        out["reason"] = (f"Zatím málo dat: historie pokrývá {covers}, záznamy jsou z {days_with_data} dnů "
                         f"(potřeba alespoň {MIN_SPAN_DAYS} dní a {MIN_DAYS_WITH_DATA} dnů se záznamem).")
        return out
    net = done_now - base[1]
    if net <= 0:
        out.update(status="no_progress", reason="V posledních týdnech nepřibyly žádné přeložené řádky – termín nelze odhadnout.")
        return out
    pace = net / max(span, 1)
    out["pace_per_day"] = round(pace, 1)

    def eta_for(rate):
        days = remaining / rate
        return None if days > HORIZON_DAYS else today + timedelta(days=int(round(days)))

    out["eta"] = eta_for(pace)
    # spread: pace of each full week inside the window
    weekly, d = [], base[0]
    while d + timedelta(days=7) <= today:
        a, b = _value_at(series, d), _value_at(series, d + timedelta(days=7))
        if a is not None and b is not None:
            weekly.append(max(0, b - a) / 7)
        d += timedelta(days=7)
    if len(weekly) >= 3:
        best, worst = max(weekly), min(weekly)
        out["eta_early"] = eta_for(best) if best > 0 else None
        out["eta_late"] = eta_for(worst) if worst > 0 else None
    mean = sum(weekly) / len(weekly) if weekly else 0
    spread = (max(weekly) - min(weekly)) / mean if mean else 9
    if span >= 28 and len(weekly) >= 3 and spread < 1.0:
        out["confidence"] = "high"
    elif span >= 14:
        out["confidence"] = "medium"
    else:
        out["confidence"] = "low"
    if out["eta"] is None:
        out.update(status="too_far", reason="Při současném tempu by dokončení trvalo víc než 5 let – datum se neuvádí.")
        return out
    out["status"] = "ok"
    out["reason"] = (f"Tempo {pace:.0f} řádků/den za posledních {span} dní"
                     f" ({days_with_data} dnů se záznamem). Odhad se mění s tempem práce.")
    return out


# ---------------------------------------------------------------- weekly goals

def _daily(points, idx):
    """Last known value of every calendar day for column `idx` of a point (2 = total, 1 = translated, 3 = proofread)."""
    by_day = {}
    for p in points:
        by_day[p[0].date()] = p[idx]
    return sorted(by_day.items())


def _at(series, day):
    val = None
    for d, v in series:
        if d <= day:
            val = v
        else:
            break
    return val


def week_start(day):
    """Monday of the week of `day`."""
    return day - timedelta(days=day.weekday())


def weekly_deltas(series, today, weeks=4):
    """Lines added in each of the last `weeks` COMPLETE weeks (Mon-Sun) that the history covers: [int], oldest first."""
    out = []
    monday = week_start(today)
    for i in range(weeks, 0, -1):
        start = monday - timedelta(days=7 * i)
        a, b = _at(series, start - timedelta(days=1)), _at(series, start + timedelta(days=6))
        if a is None or b is None:
            continue
        out.append(max(0, b - a))
    return out


def auto_goal(deltas, remaining):
    """A goal a bit above the recent weekly pace (+10 %, rounded up to tens); None when there is too little history."""
    if len(deltas) < 2:
        return None
    avg = sum(deltas) / len(deltas)
    if avg <= 0:
        return None
    goal = max(10, -(-int(avg * 1.1 + 0.999) // 10) * 10)
    return max(1, min(goal, remaining)) if remaining > 0 else None


def goal_status(done, goal, today):
    days_left = 7 - today.weekday()                 # today included
    elapsed = (7 - days_left + 1) / 7
    if done >= goal:
        status = "met"
    elif done >= goal * elapsed * 0.9:
        status = "on_track"
    else:
        status = "behind"
    return {"status": status, "left": max(0, goal - done), "days_left": days_left,
            "needed_per_day": -(-max(0, goal - done) // max(1, days_left))}


def goals(points, remaining_translate, remaining_proof, cfg=None, today=None):
    """This week's progress against a goal, for translating and for proofreading.

    cfg = {"translate_per_week": N, "proofread_per_week": N}; 0 / missing = automatic (from the recent pace).
    Returns {"week_start", "translate": {...}, "proofread": {...}}; each part has done, goal (or None), auto, percent,
    status (met | on_track | behind | no_goal), left, needed_per_day, pace_per_week."""
    today = today or date.today()
    cfg = cfg or {}
    monday = week_start(today)
    out = {"week_start": monday.isoformat()}
    for key, idx, remaining, name in (("translate", 1, remaining_translate, "translate_per_week"),
                                       ("proofread", 3, remaining_proof, "proofread_per_week")):
        series = _daily(points, idx)
        base = _at(series, monday - timedelta(days=1))
        if base is None and series:
            base = series[0][1]
        now = series[-1][1] if series else 0
        done = max(0, now - base) if base is not None else 0
        deltas = weekly_deltas(series, today)
        pace = round(sum(deltas) / len(deltas)) if deltas else None
        manual = int(cfg.get(name, 0) or 0)
        goal = manual if manual > 0 else auto_goal(deltas, remaining)
        part = {"done": done, "goal": goal, "auto": manual <= 0, "pace_per_week": pace}
        if goal:
            part.update(goal_status(done, goal, today), percent=round(min(100, done / goal * 100), 1))
        else:
            part.update(status="no_goal", left=0, days_left=7 - today.weekday(), needed_per_day=0, percent=0)
        out[key] = part
    return out
