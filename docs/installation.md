# Installation and desktop integration

Dayline runs on a native Linux Wayland desktop with layer-shell support. The
verified setup uses Hyprland, a native Thunderbird 156 installation, TbSync and
its EAS provider, GTK 4, PyGObject, and gtk4-layer-shell. SwayNC supplies desktop
notifications. Thunderbird/TbSync must already show the calendars and personal
To Do lists; Dayline does not provision accounts or store Microsoft credentials.
Flatpak/Snap Thunderbird native messaging is not covered by this setup.

## System dependencies

Install Python 3.11 or newer and uv. The desktop also needs the distribution's
PyGObject, GTK 4, and gtk4-layer-shell packages, including the GI typelibs. On
Arch Linux these UI packages are `python-gobject`, `gtk4`, and `gtk4-layer-shell`.
Use the system Python and enable system site packages in the virtual environment
so it can import GI. The bridge and diagnostic CLI need only Python's standard
library; GTK is imported only by the UI.
Agent access additionally needs the optional `mcp` extra; see
[MCP setup](agent-access.md).

## Install from a checkout

Keep the checkout and its environment at a stable location:

```sh
uv venv --python /usr/bin/python3 --system-site-packages
uv sync --frozen
uv run --frozen dayline install-bridge
uv run --frozen dayline install-desktop
```

Install the generated XPI in Thunderbird, then select sources and read a snapshot
using [bridge setup](account-setup.md). The Sources page provides the same source
selection controls. Personal sources can supply calendars and tasks; school
sources supply calendars only. School calendars need an explicit Allow edits
selection; keep subscribed timetables read-only regardless of provider flags.

## Install a built wheel

Build a wheel with `uv build` from a checkout, or use a wheel from a trusted
distribution. A user-local environment can run it independently of the checkout:

```sh
uv venv --python /usr/bin/python3 --system-site-packages ~/.local/share/dayline/venv
uv pip install --python ~/.local/share/dayline/venv/bin/python /path/to/dayline.whl
~/.local/share/dayline/venv/bin/dayline install-bridge
~/.local/share/dayline/venv/bin/dayline install-desktop
```

Replace the wheel placeholder with the actual versioned filename. The wheel
contains the bridge JSON/JavaScript and GTK stylesheet. Source archives also
include the documentation, integration examples, tests, and development lockfile.
Do not move or delete the environment after installation: both generated
launchers use that environment's Python. Reinstall the wheel and rerun the two
installation commands after moving an environment. Reinstall the XPI in
Thunderbird when its code changes; restarting Python alone does not update it.

## Launchers and startup

`install-desktop` creates these user-local files:

- `$XDG_DATA_HOME/dayline/dayline`: a stable launcher for the installed environment.
- `$XDG_DATA_HOME/applications/io.github.wusitee.Dayline.desktop`: an application
  menu entry that toggles the full window.

The default data directory is `~/.local/share`. Add `--autostart` to also create
`$XDG_CONFIG_HOME/autostart/io.github.wusitee.Dayline.desktop` (default
`~/.config/autostart`), which starts the widget at login. Running the installer
again updates its generated files and leaves source/reminder settings intact.
Omitting `--autostart` does not remove a previously installed startup entry.
Remove that entry to disable it.

Hyprland can instead use the [configuration examples](../examples). Choose one
startup method: an XDG autostart entry needs a desktop-session autostart runner;
Hyprland's explicit startup hook works without one. Replace `DAYLINE` in the
examples with the absolute installed launcher path or the environment's
`bin/dayline`. Quote paths containing spaces for that configuration format.
The examples keep `Super+N` assigned to SwayNC, use `Super+A` for the full window,
and `Super+T` or the Waybar button for the compact widget. Merge the Waybar module
and CSS into the existing configuration; the icon needs Symbols Nerd Font.

```sh
~/.local/share/dayline/dayline ui
~/.local/share/dayline/dayline ui toggle
~/.local/share/dayline/dayline ui toggle-widget
~/.local/share/dayline/dayline ui quit
```

## Verify and troubleshoot

Run `dayline sources` and `dayline read` using the installed launcher. Confirm a
real timetable occurrence and tasks from each selected personal list. Open both
GTK views, a read-only item, and a writable editor. For a controlled saved test
item, distinguish Thunderbird's local acceptance from successful TbSync/Microsoft
synchronization; see [editing](editing.md). Enable reminders separately in the
alarm menu and test notification delivery and Open task/event; see
[reminders](reminders.md) for duplicate alerts and catch-up behavior.

When Thunderbird is closed, a selection-matching saved snapshot remains viewable.
The displayed read time is local snapshot freshness, not Microsoft sync time.
Provider failures preserve the last complete cache and show an explicit error.
The bridge reconnects when Thunderbird returns. Keep it running for current
completion, deletion, and alarm changes.

If GTK imports fail, recreate the environment with the system Python and
`--system-site-packages`, then check the GI packages above. If the widget is
missing, check Wayland/layer-shell support and `ui toggle-widget`. If the bridge
is unavailable after moving/upgrading an environment, rerun `install-bridge`;
check the enabled XPI and native-host registration as described in
[bridge troubleshooting](account-setup.md#troubleshooting-and-removal).

To uninstall, quit Dayline, remove its generated application/startup entry and
the configured Hyprland/Waybar lines, and follow bridge removal in the setup
guide. Remove the installation environment only after disabling its launchers.
Saved selections, snapshots, and reminder history can be retained or removed
from the Dayline XDG config/cache directories. Keep Thunderbird/TbSync account
data intact.
