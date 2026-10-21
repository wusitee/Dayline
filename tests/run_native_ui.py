"""Run native GTK checks on a private, invisible Wayland desktop."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    for command in ("sway", "dbus-run-session"):
        if not shutil.which(command):
            print(f"Native UI checks require {command}.", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory(prefix="dayline-ui-") as temporary:
        root = Path(temporary)
        env = os.environ.copy()
        for name in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "WAYLAND_SOCKET",
            "SWAYSOCK",
            "HYPRLAND_INSTANCE_SIGNATURE",
            "DBUS_SESSION_BUS_ADDRESS",
            "DBUS_SESSION_BUS_PID",
        ):
            env.pop(name, None)
        for name, directory in (
            ("XDG_RUNTIME_DIR", "runtime"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
        ):
            path = root / directory
            path.mkdir(mode=0o700)
            env[name] = str(path)
        env.update(
            WLR_BACKENDS="headless",
            WLR_HEADLESS_OUTPUTS="1",
            WLR_RENDERER="pixman",
            GDK_BACKEND="wayland",
            GSK_RENDERER="cairo",
            GTK_A11Y="none",
            XDG_CURRENT_DESKTOP="sway",
            XDG_SESSION_DESKTOP="sway",
            XDG_SESSION_TYPE="wayland",
            # Prevent D-Bus autolaunch before dbus-run-session creates the test bus.
            DBUS_SESSION_BUS_ADDRESS=f"unix:path={root / 'unused-bus'}",
        )
        config = root / "sway.conf"
        config.write_text(
            "output HEADLESS-1 resolution 1500x900\ndefault_border none\nxwayland disable\n"
        )
        portals = root / "config" / "xdg-desktop-portal"
        portals.mkdir()
        (portals / "portals.conf").write_text("[preferred]\ndefault=none\n")
        runtime = root / "runtime"
        with (root / "sway.log").open("w+") as log:
            compositor = subprocess.Popen(
                ["sway", "--config", str(config)], env=env, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 10
                while compositor.poll() is None and time.monotonic() < deadline:
                    display = next((p for p in runtime.glob("wayland-*") if p.is_socket()), None)
                    if display is not None:
                        env["WAYLAND_DISPLAY"] = str(display)
                        env["DAYLINE_TEST_WAYLAND_DISPLAY"] = str(display)
                        return subprocess.run(
                            [
                                "dbus-run-session",
                                "--",
                                sys.executable,
                                "-m",
                                "pytest",
                                str(Path(__file__).with_name("native_ui.py")),
                                *sys.argv[1:],
                            ],
                            env=env,
                        ).returncode
                    time.sleep(0.05)
                log.seek(0)
                print("Headless compositor failed to start:\n" + log.read(), file=sys.stderr)
                return 1
            finally:
                compositor.terminate()
                try:
                    compositor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait()


if __name__ == "__main__":
    sys.exit(main())
