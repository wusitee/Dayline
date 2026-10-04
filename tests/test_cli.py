import json
import stat
import subprocess
from pathlib import Path

from dayline.cli import main
from dayline.config import Config


def test_school_tasks_rejected_before_bridge_access(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["select", "--source-id", "school", "--role", "school", "--tasks"]) == 1
    assert "Only personal" in capsys.readouterr().err
    assert Config.load().sources == {}


def test_selection_checks_source_capability_and_preserves_other_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        "dayline.cli.request",
        lambda *args, **kwargs: {
            "sources": [
                {"id": "calendar", "events": True, "tasks": False, "disabled": False},
                {"id": "todo", "events": False, "tasks": True, "disabled": False},
            ]
        },
    )
    assert main(["select", "--source-id", "calendar", "--role", "school", "--events"]) == 0
    assert main(["select", "--source-id", "todo", "--role", "personal", "--tasks"]) == 0
    assert main(["select", "--source-id", "calendar", "--role", "personal", "--tasks"]) == 1
    assert Config.load().sources["calendar"]["role"] == "school"
    assert main(["unselect", "--source-id", "calendar"]) == 0
    assert list(Config.load().sources) == ["todo"]


def test_desktop_install_uses_current_environment_and_opt_in_autostart(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data with spaces"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config(task_reminders=True)
    config.save()
    assert main(["install-desktop"]) == 0
    installed = json.loads(capsys.readouterr().out)
    launcher = Path(installed["launcher"])
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o700
    version = subprocess.run(
        [str(launcher), "--version"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert version.stdout.startswith("Dayline ")
    assert not (tmp_path / "config/autostart").exists()
    assert main(["install-desktop", "--autostart"]) == 0
    autostart = json.loads(capsys.readouterr().out)
    assert autostart["launcher"] == installed["launcher"]
    assert " ui start\n" in Path(autostart["autostart"]).read_text()
    assert " ui toggle\n" in Path(installed["application"]).read_text()
    assert Config.load() == config
