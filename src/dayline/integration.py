"""Install desktop launchers for the current Python environment, without root."""

import shlex
import sys
from pathlib import Path

from dayline.config import xdg_directory

DESKTOP_ID = "io.github.wusitee.Dayline.desktop"


def install_desktop(*, autostart: bool = False) -> dict:
    data = xdg_directory("XDG_DATA_HOME", ".local/share")
    directory = data / "dayline"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    launcher = directory / "dayline"
    launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m dayline "$@"\n')
    launcher.chmod(0o700)
    # Exec quoting precedes Desktop Entry string escaping; percent is a field code.
    quoted = (
        '"'
        + "".join("\\" + char if char in '\\"`$' else char for char in str(launcher)).replace(
            "%", "%%"
        )
        + '"'
    )
    executable = quoted.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")

    def entry(path: Path, action: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Dayline\n"
            "Comment=Calendar and personal tasks\n"
            f"Exec=/bin/sh {executable} ui {action}\n"
            "Icon=x-office-calendar\n"
            "Terminal=false\n"
            "Categories=Office;Calendar;\n"
        )

    application = data / "applications" / DESKTOP_ID
    entry(application, "toggle")
    result = {"launcher": str(launcher), "application": str(application)}
    if autostart:
        startup = xdg_directory("XDG_CONFIG_HOME", ".config") / "autostart" / DESKTOP_ID
        entry(startup, "start")
        result["autostart"] = str(startup)
    return result
