"""Deterministic local date, time, and duration input with explicit suggestions."""

import re
from datetime import UTC, date, datetime, time, timedelta, timezone

from dayline.errors import DaylineError

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTH = "(?:" + "|".join(month + "|" + month[:3] for month in MONTHS) + ")"
WEEKDAY = "(?:" + "|".join(day + "|" + day[:3] for day in WEEKDAYS) + ")"
CLOCK = r"(?:\d{1,2}(?::\d{2}(?::\d{2})?)?\s*[ap]m|\d{1,2}:\d{2}(?::\d{2})?|noon|midnight)"
CALENDAR_DATE = (
    rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s*{MONTH}|{MONTH}\s*\d{{1,2}})(?:,?\s+\d{{4}})?"
)
DETECTED = re.compile(
    rf"\b(?:(?:{WEEKDAY}\s+)?{CALENDAR_DATE}|today|tomorrow|yesterday|"
    rf"(?:next\s+)?{WEEKDAY})(?:\s+(?:at\s+)?{CLOCK})?(?:\s+(?:HKT|UTC|GMT))?\b|\b{CLOCK}\b",
    re.IGNORECASE,
)


def parse_time(value: str) -> time:
    text = value.strip().lower()
    if text in ("noon", "midnight"):
        return time(12 if text == "noon" else 0)
    match = re.fullmatch(r"(\d{1,4})(?::(\d{2})(?::(\d{2}))?)?\s*([ap]m)?", text)
    if not match:
        raise DaylineError("Use a time such as 9am, 14:30, or 0930.")
    hour, minute, second, suffix = match.groups()
    if len(hour) > 2 and minute is None:
        hour, minute = hour[:-2], hour[-2:]
    hour, minute, second = int(hour), int(minute or 0), int(second or 0)
    if suffix:
        if not 1 <= hour <= 12:
            raise DaylineError("AM/PM hours must be between 1 and 12.")
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    try:
        return time(hour, minute, second)
    except ValueError as exc:
        raise DaylineError("Use an hour from 0 to 23 and minutes from 0 to 59.") from exc


def parse_date(value: str, *, today: date, reference: date | None = None) -> date:
    text = " ".join(value.strip().lower().replace(",", " ").split())
    if text in ("today", "tomorrow", "yesterday"):
        return today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[text])
    match = re.fullmatch(rf"(next\s+)?({WEEKDAY})", text)
    if match:
        weekday = next(i for i, name in enumerate(WEEKDAYS) if name.startswith(match[2]))
        days = (weekday - today.weekday()) % 7
        return today + timedelta(days=days or (7 if match[1] else 0))
    weekday = re.match(rf"({WEEKDAY})\s+", text)
    if weekday:
        text = text[weekday.end() :]
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            result = date.fromisoformat(text)
        else:
            match = re.fullmatch(
                rf"(?:(\d{{1,2}})\s*({MONTH})|({MONTH})\s*(\d{{1,2}}))(?:\s+(\d{{4}}))?", text
            )
            if not match:
                raise ValueError
            day, month, other_month, other_day, year = match.groups()
            number = next(
                i + 1 for i, name in enumerate(MONTHS) if name.startswith(month or other_month)
            )
            result = date(int(year or (reference or today).year), number, int(day or other_day))
        if weekday and not WEEKDAYS[result.weekday()].startswith(weekday[1]):
            raise DaylineError("The weekday does not match that date.")
        return result
    except ValueError as exc:
        raise DaylineError(
            "Use a date such as 2026-10-06, 6 Oct, tomorrow, or next Tuesday."
        ) from exc


def parse_duration(value: str) -> timedelta:
    text = value.strip().lower()
    if re.fullmatch(r"\d+:\d{2}", text):
        hours, minutes = map(int, text.split(":"))
        if minutes >= 60:
            raise DaylineError("Duration minutes must be less than 60.")
        seconds = (hours * 60 + minutes) * 60
    else:
        parts = list(
            re.finditer(r"(\d+(?:\.\d+)?)\s*(d(?:ays?)?|h(?:ours?)?|m(?:in(?:utes?)?)?)", text)
        )
        if not parts or re.sub(r"\s+", "", "".join(part[0] for part in parts)) != re.sub(
            r"\s+", "", text
        ):
            raise DaylineError("Use a duration such as 50m, 1h 30m, or 1d.")
        seconds = sum(
            float(part[1]) * {"d": 86400, "h": 3600, "m": 60}[part[2][0]] for part in parts
        )
    if seconds <= 0:
        raise DaylineError("Use a positive duration.")
    try:
        return timedelta(seconds=seconds)
    except OverflowError as exc:
        raise DaylineError("That duration is too large.") from exc


def parse_schedule(
    value: str, *, now: datetime | None = None, reference: date | None = None
) -> str | None:
    text = value.strip()
    if not text:
        return None
    now = (now or datetime.now()).astimezone()
    reference = reference or now.date()
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?", text
    ):
        try:
            return (
                date.fromisoformat(text).isoformat()
                if len(text) == 10
                else datetime.fromisoformat(text).astimezone().isoformat()
            )
        except ValueError as exc:
            raise DaylineError("That date or time is invalid.") from exc
    if text.lower().startswith("in "):
        return duration_end(now.isoformat(), text[3:])
    try:
        clock = parse_time(text)
    except DaylineError:
        clock = None
    if clock is not None:
        return datetime.combine(reference, clock).astimezone().isoformat()
    match = re.fullmatch(
        rf"(.*?)\s*(?:\bat\s+)?({CLOCK})(?:\s+(HKT|UTC|GMT))?", text, re.IGNORECASE
    )
    if match:
        day = (
            parse_date(match[1], today=now.date(), reference=reference)
            if match[1].strip()
            else reference
        )
        zone = (
            timezone(timedelta(hours=8))
            if (match[3] or "").upper() == "HKT"
            else UTC
            if match[3]
            else None
        )
        return datetime.combine(day, parse_time(match[2]), tzinfo=zone).astimezone().isoformat()
    return parse_date(text, today=now.date(), reference=reference).isoformat()


def duration_end(start: str, value: str) -> str:
    duration = parse_duration(value)
    if len(start) == 10:
        if duration.total_seconds() % 86400:
            raise DaylineError("All-day durations need whole days, such as 1d or 2d.")
        try:
            return (date.fromisoformat(start) + duration).isoformat()
        except OverflowError as exc:
            raise DaylineError("That end date is too far away.") from exc
    try:
        return (datetime.fromisoformat(start).astimezone(UTC) + duration).astimezone().isoformat()
    except OverflowError as exc:
        raise DaylineError("That end date is too far away.") from exc


def detect_schedules(
    text: str, *, now: datetime, reference: date | None = None
) -> list[tuple[str, str]]:
    """Return suggestions only; ignore URLs and retain distinct dates from the text."""
    urls = [match.span() for match in re.finditer(r"https?://\S+", text)]
    found = {}
    for match in DETECTED.finditer(text):
        if any(start < match.end() and end > match.start() for start, end in urls):
            continue
        try:
            value = parse_schedule(match[0], now=now, reference=reference)
        except DaylineError:
            continue
        found.setdefault(value, match[0])
    return [(text, value) for value, text in list(found.items())[:3]]
