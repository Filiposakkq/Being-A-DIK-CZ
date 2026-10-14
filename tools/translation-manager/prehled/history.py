"""historie.csv: the progress log, and completion estimates computed from it.

historie.csv columns:  datum;prelozeno;celkem;procenta;korekce;korekce_procenta
Existing rows are never edited except the newest one of the running session (a session keeps
refreshing "its" row while the translator works, exactly as the original tool did).
"""
from datetime import date, datetime, timedelta

from .util import WriteFailed, read_rows, write_csv

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
        out["reason"] = (f"Zatím málo dat: historie pokrývá {span} dní na {days_with_data} různých dnech "
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
