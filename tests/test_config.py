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


def test_selection_merge_keeps_unedited_disabled_and_missing_sources():
    from dayline.config import merge_selection

    school = {"role": "school", "events": True, "tasks": False}
    tasks = {"role": "personal", "events": False, "tasks": True}
    current = {"disabled": tasks, "missing": school, "removed": school}
    sources = {
        "disabled": {
            "id": "disabled",
            "name": "Old list",
            "disabled": True,
            "events": False,
            "tasks": True,
        },
        "new": {
            "id": "new",
            "name": "Timetable",
            "disabled": False,
            "events": True,
            "tasks": False,
        },
        "removed": {
            "id": "removed",
            "name": "Holidays",
            "disabled": False,
            "events": True,
            "tasks": False,
        },
    }
    # Only edited sources are validated; a disabled, unedited selection survives.
    merged = merge_selection(current, {"new": school, "removed": None}, sources)
    assert merged == {"disabled": tasks, "missing": school, "new": school}
    with pytest.raises(DaylineError, match="Timetable: Only personal"):
        merge_selection(current, {"new": {**school, "tasks": True}}, sources)
    # Re-saving a disabled source with different options is a new selection.
    with pytest.raises(DaylineError, match="Old list: Enable"):
        merge_selection(current, {"disabled": {**tasks, "role": "personal"}}, sources)
