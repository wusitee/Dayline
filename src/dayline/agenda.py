"""Agenda layout and grouping, independent of GTK so it can be tested headlessly."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# Zero- and short-duration events still need a readable block in the time grid.
MIN_LAYOUT_MINUTES = 30


def is_date_only(value: str) -> bool:
    return len(value) == 10


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min).astimezone()


def local_datetime(value: str) -> datetime:
    """Return an aware local datetime; date-only values become local midnight."""
    if is_date_only(value):
        return day_start(date.fromisoformat(value))
    return datetime.fromisoformat(value).astimezone()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def visible_items(data: dict, *, include_completed: bool = False) -> list[dict]:
    """Deduplicate items; omit cancelled items and, by default, completed tasks."""
    seen = set()
    items = []
    for item in data.get("items", []):
        key = (item["source_id"], item["uid"], item.get("recurrence_id"), item.get("start"))
        if (
            key in seen
            or item.get("cancelled")
            or (item.get("completed") and not include_completed)
        ):
            continue
        seen.add(key)
        items.append(item)
    return items


def events(data: dict) -> list[dict]:
    return [item for item in visible_items(data) if item["kind"] == "event" and item.get("start")]


def tasks(data: dict, *, include_completed: bool = False) -> list[dict]:
    return [
        item
        for item in visible_items(data, include_completed=include_completed)
        if item["kind"] == "task"
    ]


def is_all_day(item: dict) -> bool:
    return is_date_only(item["start"])


def event_bounds(item: dict) -> tuple[datetime, datetime]:
    start = local_datetime(item["start"])
    if item.get("end"):
        end = local_datetime(item["end"])
    else:
        end = start + timedelta(days=1) if is_all_day(item) else start
    return start, max(start, end)


def covers(data: dict, first: date, last: date) -> bool:
    """Whether the snapshot's read ranges include every day in [first, last)."""
    lower, upper = day_start(first), day_start(last)
    ranges = sorted(
        (local_datetime(r["start"]), local_datetime(r["end"])) for r in data.get("ranges", [])
    )
    position = lower
    for start, end in ranges:
        if start > position:
            break
        position = max(position, end)
        if position >= upper:
            return True
    return False


@dataclass
class Segment:
    """A timed event clipped to one day, in minutes from local midnight."""

    item: dict
    day: int
    start: float
    end: float
    lane: int = 0
    lanes: int = 1


def _wall_minutes(moment: datetime) -> float:
    # Wall-clock position, matching the hour labels on daylight-saving transition days.
    local = moment.astimezone()
    return local.hour * 60 + local.minute + local.second / 60


def week_segments(data: dict, first: date, days: int = 7) -> list[Segment]:
    """Clip timed events to local days and give overlapping events separate lanes."""
    segments = []
    for item in events(data):
        if is_all_day(item):
            continue
        start, end = event_bounds(item)
        for day in range(days):
            lower = day_start(first + timedelta(days=day))
            upper = day_start(first + timedelta(days=day + 1))
            # A zero-duration event belongs to the day containing its start.
            if start >= upper or (end <= lower and not start == end == lower):
                continue
            a = 0.0 if start <= lower else _wall_minutes(start)
            b = 1440.0 if end >= upper else _wall_minutes(end)
            # A repeated autumn hour can put the wall-clock end before the start.
            segments.append(Segment(item, day, a, max(a, b)))
    for day in range(days):
        cluster: list[Segment] = []
        cluster_end = -1.0
        ordered = sorted((s for s in segments if s.day == day), key=lambda s: (s.start, -s.end))
        for segment in ordered:
            # Events that overlap, directly or through a chain, share one set of lanes.
            if cluster and segment.start >= cluster_end:
                _assign_lanes(cluster)
                cluster = []
            if not cluster:
                cluster_end = -1.0
            cluster.append(segment)
            cluster_end = max(cluster_end, layout_end(segment))
        _assign_lanes(cluster)
    return segments


def layout_end(segment: Segment) -> float:
    return max(segment.end, min(1440, segment.start + MIN_LAYOUT_MINUTES))


def _assign_lanes(cluster: list[Segment]) -> None:
    ends: list[float] = []
    for segment in cluster:
        lane = next((i for i, end in enumerate(ends) if end <= segment.start), len(ends))
        if lane == len(ends):
            ends.append(0)
        ends[lane] = layout_end(segment)
        segment.lane = lane
    for segment in cluster:
        segment.lanes = len(ends)


@dataclass
class Span:
    """An all-day event clipped to the visible days; last is inclusive."""

    item: dict
    first: int
    last: int
    row: int = 0


def all_day_spans(data: dict, first: date, days: int = 7) -> list[Span]:
    spans = []
    for item in events(data):
        if not is_all_day(item):
            continue
        start, end = event_bounds(item)
        # All-day end dates are exclusive.
        a = max(0, (start.date() - first).days)
        b = min(days - 1, (end.date() - first).days - 1)
        if a <= b:
            spans.append(Span(item, a, b))
    spans.sort(key=lambda s: (s.first, -(s.last - s.first), s.item["title"].casefold()))
    row_ends: list[int] = []
    for span in spans:
        row = next((i for i, last in enumerate(row_ends) if last < span.first), len(row_ends))
        if row == len(row_ends):
            row_ends.append(span.last)
        row_ends[row] = span.last
        span.row = row
    return spans


def due(item: dict) -> tuple[date, datetime | None] | None:
    """Return a task's due date and, when meaningful, its due time.

    Microsoft To Do due dates arrive as timestamps at local midnight; treat those
    as date-only so a task due today is not reported overdue all day.
    """
    if not item.get("due"):
        return None
    moment = local_datetime(item["due"])
    if is_date_only(item["due"]) or moment.time() == time.min:
        return moment.date(), None
    return moment.date(), moment


def is_overdue(item: dict, now: datetime) -> bool:
    value = due(item)
    return value is not None and (
        value[0] < now.date() or (value[1] is not None and value[1] < now)
    )


def task_groups(data: dict, now: datetime) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"overdue": [], "today": [], "upcoming": [], "undated": []}
    today = now.date()
    for item in tasks(data):
        value = due(item)
        if value is None:
            groups["undated"].append(item)
        elif is_overdue(item, now):
            groups["overdue"].append(item)
        elif value[0] == today:
            groups["today"].append(item)
        else:
            groups["upcoming"].append(item)
    for name, items in groups.items():
        items.sort(
            key=lambda item: (
                () if name == "undated" else (local_datetime(item["due"]),),
                item["title"].casefold(),
            )
        )
    return groups


def upcoming_events(data: dict, now: datetime, days: int = 7) -> list[dict]:
    """Current and future events, ending after now and starting within the horizon."""
    horizon = day_start(now.date() + timedelta(days=days))
    items = []
    for item in events(data):
        start, end = event_bounds(item)
        if (end > now or start >= now) and start < horizon:
            items.append(item)
    return sorted(items, key=lambda item: (event_bounds(item)[0], item["title"].casefold()))


def day_events(data: dict, day: date) -> list[dict]:
    lower, upper = day_start(day), day_start(day + timedelta(days=1))
    items = []
    for item in events(data):
        start, end = event_bounds(item)
        if start < upper and (end > lower or start == end == lower):
            items.append(item)
    return sorted(
        items,
        key=lambda item: (not is_all_day(item), event_bounds(item)[0], item["title"].casefold()),
    )


def relative_day(day: date, today: date) -> str:
    offset = (day - today).days
    if offset in (-1, 0, 1):
        return {-1: "Yesterday", 0: "Today", 1: "Tomorrow"}[offset]
    return f"In {offset} days" if offset > 0 else f"{-offset} days ago"


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    if day == today - timedelta(days=1):
        return "Yesterday"
    label = f"{day:%a} {day.day} {day:%b}"
    return label if day.year == today.year else f"{label} {day.year}"


def time_range(item: dict, today: date) -> str:
    start, end = event_bounds(item)
    if is_all_day(item):
        last = end.date() - timedelta(days=1)
        if last <= start.date():
            return f"{day_label(start.date(), today)} · All day"
        return f"{day_label(start.date(), today)} – {day_label(last, today)} · All day"
    if start == end:
        return f"{day_label(start.date(), today)} · {start:%H:%M}"
    if end.date() == start.date() or end == day_start(start.date() + timedelta(days=1)):
        return f"{day_label(start.date(), today)} · {start:%H:%M}–{end:%H:%M}"
    first, last = day_label(start.date(), today), day_label(end.date(), today)
    return f"{first} {start:%H:%M} – {last} {end:%H:%M}"


def week_title(first: date) -> str:
    last = first + timedelta(days=6)
    if first.year != last.year:
        return f"{first.day} {first:%B %Y} – {last.day} {last:%B %Y}"
    if first.month != last.month:
        return f"{first.day} {first:%B} – {last.day} {last:%B %Y}"
    return f"{first.day}–{last.day} {last:%B %Y}"


def due_label(item: dict, today: date) -> str:
    value = due(item)
    if value is None:
        return "No due date"
    day, moment = value
    label = day_label(day, today)
    if abs((day - today).days) <= 1:
        label = label.lower()
    return f"Due {label} {moment:%H:%M}" if moment else f"Due {label}"


def timestamp_label(value: str, today: date) -> str:
    moment = local_datetime(value)
    if moment.date() == today:
        return f"{moment:%H:%M}"
    return f"{day_label(moment.date(), today)} {moment:%H:%M}"


def status(data: dict | None, *, saved: bool, error: str | None, today: date) -> list[str]:
    """Describe why the displayed snapshot may be stale or incomplete."""
    if data is None:
        return [error] if error else []
    read = timestamp_label(data["generated_at"], today)
    warnings = []
    if error:
        warnings.append(f"{error} Showing data read at {read}.")
    elif saved:
        warnings.append(f"Showing the saved snapshot from {read}, not a live read.")
    names = {source["id"]: source["name"] for source in data.get("sources", [])}
    for failure in data.get("errors", []):
        name = names.get(failure["source_id"], "A selected source")
        warnings.append(f"{name} could not be read; its items are missing. {failure['message']}")
    if data.get("offline"):
        warnings.append("Thunderbird is offline; items reflect its local copy.")
    return warnings


def day_agenda(data: dict, day: date, now: datetime) -> tuple[list[dict], list[dict]]:
    """Events and tasks for the compact widget's selected day.

    Today lists events that have not ended, plus overdue tasks; other days list
    all of their events and the unfinished tasks due on them.
    """
    if day == now.date():
        # Finished events drop off today.
        items = [item for item in day_events(data, day) if event_bounds(item)[1] >= now]
        groups = task_groups(data, now)
        return items, groups["overdue"] + groups["today"]
    due_today = [item for item in tasks(data) if (value := due(item)) and value[0] == day]
    due_today.sort(key=lambda item: (local_datetime(item["due"]), item["title"].casefold()))
    return day_events(data, day), due_today


def upcoming_task_days(data: dict, day: date, days: int = 4) -> dict[date, list[dict]]:
    """Unfinished tasks due in the next days after the widget's selected day."""
    groups: dict[date, list[dict]] = {}
    for item in tasks(data):
        value = due(item)
        if value and day < value[0] <= day + timedelta(days=days):
            groups.setdefault(value[0], []).append(item)
    return {
        day: sorted(items, key=lambda item: (local_datetime(item["due"]), item["title"].casefold()))
        for day, items in sorted(groups.items())
    }


def agenda_days(data: dict, first: date) -> list[date]:
    """Loaded event dates from the anchor onward, plus every unfinished task's due date."""
    days = {
        first + timedelta(days=i)
        for i in range(7)
        if covers(data, first + timedelta(days=i), first + timedelta(days=i + 1))
    }
    days.update(value[0] for item in tasks(data) if (value := due(item)))
    candidates = set()
    for window in data.get("ranges", []):
        day = max(first, local_datetime(window["start"]).date())
        end = local_datetime(window["end"])
        while day_start(day) < end:
            candidates.add(day)
            day += timedelta(days=1)
    days.update(day for day in candidates if day_events(data, day))
    return sorted(days)


def day_schedule(data: dict, day: date, *, include_completed: bool = False) -> list[dict]:
    """Events and due tasks, with completed tasks last when included."""
    items = day_events(data, day)
    items.extend(
        item
        for item in tasks(data, include_completed=include_completed)
        if (value := due(item)) and value[0] == day
    )
    lower = day_start(day)

    def position(item):
        if item["kind"] == "task":
            moment = due(item)[1]
        else:
            moment = None if is_all_day(item) else max(lower, event_bounds(item)[0])
        return (
            bool(item.get("completed")),
            moment is not None,
            moment or lower,
            item["title"].casefold(),
        )

    return sorted(items, key=position)


def schedule_time(item: dict, day: date) -> str:
    """Local time for an agenda row, clipping overnight events to the shown day."""
    if item["kind"] == "task":
        value = due(item)
        if value is None:
            return "No due date"
        moment = value[1]
        return f"{moment:%H:%M}" if moment else "All day"
    if is_all_day(item):
        return "All day"
    lower, upper = day_start(day), day_start(day + timedelta(days=1))
    start, end = event_bounds(item)
    start, end = max(lower, start), min(upper, end)
    if start == end:
        return f"{start:%H:%M}"
    last = "24:00" if end == upper else f"{end:%H:%M}"
    return f"{start:%H:%M}–{last}"


_URL = re.compile(r"https?://[^\s<>\"']+")


def _markup_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def link_markup(text: str) -> str:
    """Escape plain text for Pango markup, turning http(s) URLs into links."""
    parts = []
    position = 0
    for match in _URL.finditer(text):
        url = match.group().rstrip(".,;:!?)]")
        parts.append(_markup_escape(text[position : match.start()]))
        parts.append(f'<a href="{_markup_escape(url)}">{_markup_escape(url)}</a>')
        position = match.start() + len(url)
    parts.append(_markup_escape(text[position:]))
    return "".join(parts)
