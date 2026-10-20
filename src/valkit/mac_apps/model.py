from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Channel(StrEnum):
    CASK = "cask"
    MAS = "mas"
    MANUAL = "manual"
    NIX = "nix"
    SYSTEM = "system"


MANAGED = frozenset({Channel.CASK, Channel.MAS, Channel.MANUAL})
"""Channels the manifest declares. Nix and system apps are listed but never touched."""


@dataclass(frozen=True)
class App:
    name: str
    path: Path
    bundle_id: str
    channel: Channel
    key: str | None
    """The manifest key: cask token, App Store ID, or bundle ID. None if unknown."""
    size: int | None
    """Bundle size in bytes, None when Mole could not measure it."""
    size_display: str
    uninstall_name: str
    """The name `mo uninstall` accepts, exactly as Mole printed it."""


@dataclass(frozen=True)
class Inventory:
    apps: list[App]
    casks: frozenset[str]
    """Every installed cask token, including casks that install no app."""
    foreign_casks: dict[str, tuple[Path, ...]]
    """Casks whose app target holds an app the cask does not name, to those targets.
    Removing such a cask would delete the other app."""


@dataclass(frozen=True)
class ManualApp:
    bundle_id: str
    url: str
    dir: str
    """The directory the app must be installed in."""


@dataclass(frozen=True)
class Entry:
    """One manifest entry, or one installed application in manifest terms."""

    channel: Channel
    key: str
    """Cask token, App Store ID, or bundle ID."""
    name: str
    url: str | None = None
    """Download URL of a manual entry."""
    dir: str | None = None
    """The directory a cask or manual app must be installed in. None for App Store
    apps, which Apple always installs in /Applications."""


@dataclass(frozen=True)
class Manifest:
    casks: dict[str, str]
    """Cask token to the directory its apps must be installed in."""
    mas: dict[str, int]
    """Name to App Store ID."""
    manual: dict[str, ManualApp]
    """Name to bundle ID, download URL, and directory."""
    dock: tuple[str, ...] = ()
    """Absolute paths of the Dock's application tiles."""

    def declares(self, app: App) -> bool:
        return app.channel in MANAGED and app.key in self.keys(app.channel)

    def keys(self, channel: Channel) -> set[str]:
        return {entry.key for entry in self.entries() if entry.channel == channel}

    def entries(self) -> list[Entry]:
        return [
            *(
                Entry(Channel.CASK, token, token, dir=directory)
                for token, directory in sorted(self.casks.items())
            ),
            *(Entry(Channel.MAS, str(app_id), name) for name, app_id in self.mas.items()),
            *(
                Entry(Channel.MANUAL, app.bundle_id, name, app.url, app.dir)
                for name, app in self.manual.items()
            ),
        ]


def manifest_from_entries(entries: list[Entry], dock: tuple[str, ...] = ()) -> Manifest:
    return Manifest(
        casks={entry.key: entry.dir or "" for entry in entries if entry.channel == Channel.CASK},
        mas={entry.name: int(entry.key) for entry in entries if entry.channel == Channel.MAS},
        manual={
            entry.name: ManualApp(bundle_id=entry.key, url=entry.url or "", dir=entry.dir or "")
            for entry in entries
            if entry.channel == Channel.MANUAL
        },
        dock=dock,
    )
