import argparse
import json
import sys
from datetime import date

from dayline import __version__
from dayline.bridge import cached_snapshot, install_bridge, request, snapshot
from dayline.config import Config, check_selection
from dayline.errors import DaylineError


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Dayline Thunderbird calendar bridge")
    root.add_argument("--version", action="version", version=f"Dayline {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "install-bridge", help="Build the XPI and register the native messaging host"
    )
    commands.add_parser("sources", help="List Thunderbird source metadata without reading items")
    select = commands.add_parser("select", help="Include a calendar or personal To Do list")
    select.add_argument("--source-id", required=True)
    select.add_argument("--role", required=True, choices=("personal", "school"))
    select.add_argument("--events", action="store_true")
    select.add_argument("--tasks", action="store_true")
    unselect = commands.add_parser("unselect", help="Remove a source from Dayline")
    unselect.add_argument("--source-id", required=True)
    commands.add_parser("selection", help="Show local source selection")
    read = commands.add_parser(
        "read", help="Read selected events and personal tasks into the cache"
    )
    read.add_argument("--start", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    read.add_argument("--days", type=int, default=7)
    commands.add_parser("cached", help="Read the saved snapshot without contacting Thunderbird")
    ui = commands.add_parser("ui", help="Run the agenda, or control its running instance")
    ui.add_argument(
        "action",
        nargs="?",
        default="start",
        choices=("start", "toggle", "toggle-widget", "show", "hide", "quit"),
        help="start the widget, toggle/show/hide the panel, toggle the widget, or quit",
    )
    return root


def run(args: argparse.Namespace) -> object:
    if args.command == "install-bridge":
        return install_bridge()
    if args.command == "sources":
        return request("sources")
    config = Config.load()
    if args.command == "selection":
        return {"sources": config.sources}
    if args.command == "select":
        options = {"role": args.role, "events": args.events, "tasks": args.tasks}
        # Reject invalid roles before contacting Thunderbird.
        check_selection(options)
        sources = {s["id"]: s for s in request("sources")["sources"]}
        source = sources.get(args.source_id)
        if source is None:
            raise DaylineError("Source not found in Thunderbird; run 'dayline sources'.")
        check_selection(options, source)
        config.sources[args.source_id] = options
        config.save()
        return {"sources": config.sources}
    if args.command == "unselect":
        config.sources.pop(args.source_id, None)
        config.save()
        return {"sources": config.sources}
    if args.command == "cached":
        data = cached_snapshot(config)
        if data is None:
            raise DaylineError(
                "No snapshot matches the current source selection; run 'dayline read'."
            )
        return data
    if not config.sources:
        raise DaylineError("Run 'dayline sources', then 'dayline select' before reading calendars.")
    return snapshot(config, args.start or date.today(), args.days)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "ui":
        try:
            # Imported lazily: GTK is optional for the bridge and its diagnostics.
            from dayline.ui.app import run as run_ui
        except (ImportError, ValueError, OSError) as exc:
            print(f"dayline: GTK 4 and gtk4-layer-shell are required: {exc}", file=sys.stderr)
            return 1
        try:
            return run_ui(args.action)
        except DaylineError as exc:
            print(f"dayline: {exc}", file=sys.stderr)
            return 1
    try:
        output = run(args)
    except DaylineError as exc:
        print(f"dayline: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print(
            "dayline: Cannot access local Dayline files; check filesystem permissions.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
