"""Session labelling for intraday strategies.

An intraday strategy needs to know three things a plain bar index cannot
answer: which trading session a bar belongs to, how far into that session
it is, and whether some intraday window (an ICT killzone, a London open)
has already closed.

Everything here works in **session-relative seconds** — `(local_seconds -
session_open) % 86400`. That one change of coordinates makes a session
monotonic from 0 to its length even when it wraps midnight, so window
membership and "has this window finished yet" become plain comparisons
instead of a nest of wrap cases. The engine never handles a raw wall
clock.

Pure pandas over the bars DataFrame; no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from app.strategies.schemas import SessionSpec

DAY = 86_400


def _seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


@dataclass(frozen=True, slots=True)
class Sessions:
    """Per-bar session context, aligned to the bars DataFrame's index.

    `sid` is the session's opening local date, so every bar of an
    overnight session shares one label. Bars outside any session get
    `in_session=False` and are excluded from windows and from trading.
    """

    sid: pd.Series          # session id (opening local date), object dtype
    rel: pd.Series          # seconds since the session opened, 0..DAY
    in_session: pd.Series   # bool
    last_of_session: pd.Series  # bool — final in-session bar, forced flat here
    length: int             # session length in seconds
    open_seconds: int       # session open as seconds past local midnight

    def window_mask(self, start: time, end: time) -> pd.Series:
        """Bars inside an intraday window, in session-relative terms."""
        lo, hi = self.rel_bounds(start, end)
        return self.in_session & (self.rel >= lo) & (self.rel < hi)

    def after_window(self, start: time, end: time) -> pd.Series:
        """Bars at or past the window's close — when its extremes are known.

        This is the no-lookahead gate: a range high is not readable until
        the range has finished forming.
        """
        _, hi = self.rel_bounds(start, end)
        return self.in_session & (self.rel >= hi)

    def since(self, t: time) -> pd.Series:
        """Bars at or past a local time, within their own session."""
        return self.in_session & (self.rel >= (_seconds(t) - self.open_seconds) % DAY)

    def rel_bounds(self, start: time, end: time) -> tuple[int, int]:
        """Window bounds as seconds since session open, `lo < hi`."""
        open_s = self.open_seconds
        lo = (_seconds(start) - open_s) % DAY
        hi = (_seconds(end) - open_s) % DAY
        # A window ending exactly at the session open reads as 0 after the
        # modulo; it means "runs to the end of the session", not "empty".
        if hi <= lo:
            hi += DAY
        return lo, hi


def build_sessions(ts: pd.Series, spec: SessionSpec) -> Sessions:
    """Label every bar with its session, given the session's wall clock."""
    stamps = pd.to_datetime(ts)
    # A naive column is read as UTC rather than as local time: the bars
    # feed stores UTC, and silently reinterpreting it as the session's own
    # zone would shift every window by the offset.
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize("UTC")
    local = stamps.dt.tz_convert(spec.zone)

    open_s = _seconds(spec.open)
    close_s = _seconds(spec.close)
    length = (close_s - open_s) % DAY or DAY  # equal times ⇒ 24h session

    secs = local.dt.hour * 3600 + local.dt.minute * 60 + local.dt.second
    rel = (secs - open_s) % DAY
    in_session = rel < length

    # The session is named for the date it opened. Bars past midnight have
    # rolled the local date forward, so roll it back by the elapsed time.
    opened_at = local - pd.to_timedelta(rel, unit="s")
    sid = opened_at.dt.date

    # Forced flat happens on the last bar that is still inside the session,
    # which is also the last bar of that sid — a session with a data gap at
    # its close still gets flattened rather than leaking into the next day.
    ordinal = sid.where(in_session)
    last_of_session = in_session & (ordinal != ordinal.shift(-1))

    return Sessions(
        sid=sid,
        rel=rel,
        in_session=in_session,
        last_of_session=last_of_session.fillna(False).astype(bool),
        length=length,
        open_seconds=open_s,
    )


def window_extreme(
    df: pd.DataFrame, sessions: Sessions, start: time, end: time, side: str
) -> pd.Series:
    """High or low of an intraday window, broadcast across its session.

    NaN until the window closes, so a condition cannot read a range that
    is still forming. NaN too for a session whose window has no bars at
    all — a strategy should stand aside on a session it cannot measure,
    not trade off a neighbouring day's level.
    """
    mask = sessions.window_mask(start, end)
    col = "high" if side == "high" else "low"
    grouped = df.loc[mask].groupby(sessions.sid[mask], sort=False)[col]
    per_session = grouped.max() if side == "high" else grouped.min()

    values = sessions.sid.map(per_session).astype(float)
    return values.where(sessions.after_window(start, end))
