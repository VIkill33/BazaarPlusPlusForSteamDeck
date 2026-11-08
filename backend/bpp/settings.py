import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


MAX_LAUNCH_OPTIONS_LENGTH = 16384
DEFAULT_PANEL_FONT_SIZE = "medium"
PANEL_FONT_SIZES = frozenset(("small", "medium", "large"))


@dataclass(frozen=True)
class LaunchOptionsBackup:
    original: str
    managed: str


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


class LaunchOptionsBackupStore:
    def __init__(self, settings_dir: Path) -> None:
        self._path = settings_dir / "launch-options.json"

    def save(self, original: str, managed: str) -> None:
        if (
            len(original) > MAX_LAUNCH_OPTIONS_LENGTH
            or len(managed) > MAX_LAUNCH_OPTIONS_LENGTH
        ):
            raise RuntimeError("Steam 启动参数过长")
        _write_json_atomic(
            self._path,
            {"original": original, "managed": managed},
        )

    def get(self) -> Optional[LaunchOptionsBackup]:
        try:
            value = json.loads(self._path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        original = value.get("original")
        managed = value.get("managed")
        if isinstance(original, str) and isinstance(managed, str):
            return LaunchOptionsBackup(original=original, managed=managed)
        return None

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


class PanelFontSizeStore:
    def __init__(self, settings_dir: Path) -> None:
        self._path = settings_dir / "font-size.json"

    def get(self) -> str:
        try:
            value = json.loads(self._path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_PANEL_FONT_SIZE
        if not isinstance(value, dict):
            return DEFAULT_PANEL_FONT_SIZE
        preset = value.get("preset")
        if isinstance(preset, str) and preset in PANEL_FONT_SIZES:
            return preset
        return DEFAULT_PANEL_FONT_SIZE

    def save(self, preset: str) -> str:
        if preset not in PANEL_FONT_SIZES:
            raise RuntimeError("无效的面板字号设置")
        _write_json_atomic(self._path, {"preset": preset})
        return preset
