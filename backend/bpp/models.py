from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Release:
    version: str
    installer_url: str
    sha256: Optional[str] = None


@dataclass(frozen=True)
class PluginStatus:
    game_found: bool
    game_path: Optional[str]
    game_running: bool
    installed: bool
    installed_version: Optional[str]


@dataclass(frozen=True)
class LatestRelease:
    version: str
    update_available: bool


def normalize_version(version: str) -> str:
    if version.casefold().endswith(".prod"):
        return version[:-5]
    return version
