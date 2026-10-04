"""Native editor values and patches; unchanged fields stay with the provider."""

from datetime import date, datetime

from dayline.errors import DaylineError


def entry_date(value: str | None) -> str:
    if not value:
        return ""
    if len(value) == 10:
        return value
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")


def parse_entry_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value).astimezone().isoformat()
    except ValueError as exc:
        raise DaylineError("Use YYYY-MM-DD or YYYY-MM-DD HH:MM for dates and times.") from exc


def editor_values(item: dict) -> dict[str, str]:
    keys = (
        ("title", "start", "end", "location", "description")
        if item["kind"] == "event"
        else ("title", "start", "due", "description")
    )
    values = {key: item.get(key) or "" for key in keys}
    for key in ("start", "end", "due"):
        if key in values:
            values[key] = entry_date(values[key])
    values["reminder"] = entry_date(next(iter(item.get("alarms", [])), None))
    return values


def editor_changes(previous: dict[str, str], entered: dict[str, str]) -> dict:
    if not entered.get("title", "").strip():
        raise DaylineError("Give the item a title.")
    changes = {key: value for key, value in entered.items() if value != previous.get(key)}
    for key in ("start", "end", "due", "reminder"):
        if key in changes:
            changes[key] = parse_entry_date(changes[key])
    return changes
