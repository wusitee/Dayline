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
