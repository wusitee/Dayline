"""Search across tasks and a wide window of events, independent of GTK."""

import re
from datetime import date, datetime, timedelta

from dayline.agenda import due, event_bounds, local_datetime, visible_items

# Each bridge read accepts two ranges of up to 35 days: pair one past and one future chunk.
CHUNK_DAYS = 35
SEARCH_READS = 11


def search_reads(today: date) -> list[list[tuple[date, date]]]:
    """Bridge reads covering the search window, nearest dates first."""
    chunk = timedelta(days=CHUNK_DAYS)
    return [
        [
            (today + chunk * index, today + chunk * (index + 1)),
            (today - chunk * (index + 1), today - chunk * index),
        ]
        for index in range(SEARCH_READS)
    ]


def search_window(today: date) -> tuple[date, date]:
    """The first and last day whose events are searched."""
    span = timedelta(days=CHUNK_DAYS * SEARCH_READS)
    return today - span, today + span - timedelta(days=1)


def query_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def matches(item: dict, words: list[str], source: str) -> bool:
    """Every word appears in the title, location, notes, or source name, in any order."""
    fields = (item.get("title"), item.get("location"), item.get("description"), source)
    text = "\n".join(value for value in fields if value).casefold()
    return all(word in text for word in words)


def _task_order(item: dict) -> tuple:
    value = due(item)
    if item.get("completed"):
        # Recently completed first; tasks without a completion date last.
        completed = item.get("completed_at")
        return (2, -local_datetime(completed).timestamp() if completed else 0)
    if value is None:
        return (1, item["title"].casefold())
    return (0, local_datetime(item["due"]), item["title"].casefold())


def search(items: list[dict], sources: dict[str, str], query: str, now: datetime) -> dict:
    """Return matching open and completed tasks and upcoming/past events for a query.

    sources maps source IDs to names. Events that are still running count as upcoming.
    Matching occurrences of a recurring event collapse into one result: the nearest
    upcoming occurrence, or the latest past one, with the number of matching occurrences.
    """
    results: dict = {"tasks": [], "completed": [], "upcoming": [], "past": []}
    words = query_words(query)
    if not words:
        return results
    series: dict[tuple, list[dict]] = {}
    for item in visible_items({"items": items}, include_completed=True):
        if not matches(item, words, sources.get(item["source_id"], "")):
            continue
        if item["kind"] == "task":
            results["completed" if item.get("completed") else "tasks"].append(item)
        elif item.get("start"):
            recurring = item.get("recurring") or item.get("recurrence_id")
            key = (item["source_id"], item["uid"]) if recurring else (id(item),)
            series.setdefault(key, []).append(item)
    results["tasks"].sort(key=_task_order)
    results["completed"].sort(key=_task_order)
    for occurrences in series.values():
        occurrences.sort(key=lambda item: event_bounds(item)[0])
        upcoming = [item for item in occurrences if event_bounds(item)[1] > now]
        if upcoming:
            results["upcoming"].append((upcoming[0], len(occurrences)))
        else:
            results["past"].append((occurrences[-1], len(occurrences)))
    results["upcoming"].sort(key=lambda result: (event_bounds(result[0])[0], result[0]["title"]))
    results["past"].sort(key=lambda result: event_bounds(result[0])[0], reverse=True)
    return results
