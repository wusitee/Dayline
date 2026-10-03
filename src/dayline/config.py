import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dayline.errors import DaylineError


def xdg_directory(variable: str, fallback: str) -> Path:
    value = Path(os.environ.get(variable, ""))
    return value if value.is_absolute() else Path.home() / fallback


def config_path() -> Path:
    return xdg_directory("XDG_CONFIG_HOME", ".config") / "dayline" / "config.json"


def cache_directory() -> Path:
    return xdg_directory("XDG_CACHE_HOME", ".cache") / "dayline"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class Config:
    # Thunderbird calendar IDs, selected explicitly; no account credentials.
    sources: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(config_path().read_text())
        except FileNotFoundError:
            return cls()
        except (ValueError, OSError) as exc:
            raise DaylineError("Cannot read Dayline configuration; check config.json.") from exc
        sources = data.get("sources") if isinstance(data, dict) else None
        if not isinstance(sources, dict):
            raise DaylineError("Dayline configuration must contain a sources object.")
        for uid, selection in sources.items():
            if (
                not isinstance(uid, str)
                or not uid
                or not isinstance(selection, dict)
                or selection.get("role") not in ("personal", "school")
                or type(selection.get("events")) is not bool
                or type(selection.get("tasks")) is not bool
                or (selection["role"] == "school" and selection["tasks"])
            ):
                raise DaylineError("Invalid source selection; school sources cannot supply tasks.")
        return cls(sources)

    def save(self) -> None:
        write_json(config_path(), {"sources": self.sources})
