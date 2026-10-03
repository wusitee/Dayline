import json
import stat

import pytest

from dayline.config import Config, config_path
from dayline.errors import DaylineError


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_source_selection_persists_privately():
    config = Config(
        {
            "outlook-tasks": {"role": "personal", "events": False, "tasks": True},
            "hku-timetable": {"role": "school", "events": True, "tasks": False},
        }
    )
    assert Config.load().sources == {}
    config.save()
    assert Config.load() == config
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"sources": []},
        {"sources": {"school": {"role": "school", "events": True, "tasks": True}}},
        {"sources": {"personal": {"role": "personal", "events": 1, "tasks": False}}},
    ],
)
def test_invalid_configuration_is_not_silently_used(data):
    config_path().parent.mkdir()
    config_path().write_text(json.dumps(data))
    with pytest.raises(DaylineError):
        Config.load()


def test_relative_xdg_path_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert config_path() == tmp_path / ".config/dayline/config.json"
