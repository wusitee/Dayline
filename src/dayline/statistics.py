"""Task snapshot counts and focus history summaries in local calendar days."""

from datetime import datetime, timedelta

from dayline.agenda import due, is_overdue, local_datetime, tasks


def summarize(data: dict | None, sessions: list[dict], now: datetime, days: int) -> dict:
    today = now.date()
    daily = {
        (today - timedelta(days=offset)).isoformat(): {
            "day": today - timedelta(days=offset),
            "seconds": 0,
            "completed": 0,
        }
        for offset in reversed(range(days))
    }
    counts = {"open": 0, "overdue": 0, "due_today": 0, "completed": 0}
    sources = {source["id"]: source["name"] for source in (data or {}).get("sources", [])}
    lists = {}
    unknown = 0
    for item in tasks(data or {}, include_completed=True):
        group = lists.setdefault(
            item["source_id"],
            {"title": sources.get(item["source_id"], "To Do list"), "open": 0, "completed": 0},
        )
        if item.get("completed"):
            if not item.get("completed_at"):
                unknown += 1
            elif (day := local_datetime(item["completed_at"]).date().isoformat()) in daily:
                daily[day]["completed"] += 1
                counts["completed"] += 1
                group["completed"] += 1
        else:
            counts["open"] += 1
            group["open"] += 1
            counts["overdue"] += is_overdue(item, now)
            value = due(item)
            counts["due_today"] += value is not None and value[0] == today

    groups = {}
    session_count = 0
    for session in sessions:
        seconds = sum(session["days"].get(day, 0) for day in daily)
        if not seconds:
            continue
        session_count += 1
        group = groups.setdefault(
            session["key"], {"key": session["key"], "title": session["title"], "seconds": 0}
        )
        group["title"] = session["title"]
        group["seconds"] += seconds
        for day, values in daily.items():
            values["seconds"] += session["days"].get(day, 0)
    total = sum(day["seconds"] for day in daily.values())
    return {
        "tasks": counts,
        "focus": {
            "seconds": total,
            "sessions": session_count,
            "average": total / session_count if session_count else 0,
            "days": sum(day["seconds"] > 0 for day in daily.values()),
        },
        "daily": list(daily.values()),
        "by_task": sorted(groups.values(), key=lambda group: (-group["seconds"], group["title"])),
        "by_list": sorted(lists.values(), key=lambda group: group["title"].casefold()),
        "unknown_completions": unknown,
    }
