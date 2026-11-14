"""Forgiving date/time parsing for slash command inputs."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_date(text: str, today: date) -> date:
    t = text.strip().lower()
    if t in ("today", "tonight"):
        return today
    if t in ("tomorrow", "tmrw"):
        return today + timedelta(days=1)
    if t[:3] in _WEEKDAYS and t.isalpha():
        target = _WEEKDAYS.index(t[:3])
        delta = (target - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", t)  # DD/MM, current or next year
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        try:
            cand = date(today.year, mo, d)
        except ValueError:
            raise ValueError("Invalid date")
        return cand if cand >= today else date(today.year + 1, mo, d)
    raise ValueError("Use YYYY-MM-DD, DD/MM, 'today', 'tomorrow' or a weekday like 'fri'.")


def parse_time(text: str) -> time:
    t = text.strip().lower().replace(".", "").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        raise ValueError("Use a time like 20:30, 8pm or 8:30pm.")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if not 1 <= h <= 12:
            raise ValueError("Hour must be 1-12 with am/pm.")
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59:
        raise ValueError("That isn't a valid time.")
    return time(h, mi)


def to_timestamp(date_text: str, time_text: str, tz_name: str) -> int:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    d = parse_date(date_text, now.date())
    t = parse_time(time_text)
    return int(datetime.combine(d, t, tzinfo=tz).timestamp())
