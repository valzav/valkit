from dataclasses import dataclass
from pathlib import Path

from valkit.mac_apps.model import App, Inventory, Manifest

APP_STORE_DIR = Path("/Applications")
"""Where Apple installs every App Store app."""


@dataclass(frozen=True)
class Misplaced:
    app: App
    expected: str
    """The directory the manifest declares, as written there."""


@dataclass(frozen=True)
class Layout:
    misplaced: list[Misplaced]
    """Copies of declared apps outside their declared directory, including the extra
    copy of an app installed twice."""
    dock_missing: list[str]
    """Dock tiles whose path holds no application."""

    @property
    def ok(self) -> bool:
        return not self.misplaced and not self.dock_missing


def check_layout(
    manifest: Manifest, inventory: Inventory, app_store_dir: Path = APP_STORE_DIR
) -> Layout:
    """Check that every declared app sits in its declared directory and that every Dock
    tile points at an installed application. Undeclared apps are not checked."""
    expected = {
        (entry.channel, entry.key): entry.dir or str(app_store_dir) for entry in manifest.entries()
    }
    misplaced: list[Misplaced] = []
    for app in inventory.apps:
        directory = expected.get((app.channel, app.key)) if app.key else None
        if directory is not None and _directory_of(app.path) != Path(directory).expanduser():
            misplaced.append(Misplaced(app, directory))
    misplaced.sort(key=lambda item: str(item.app.path))
    return Layout(
        misplaced=misplaced,
        dock_missing=[tile for tile in manifest.dock if not Path(tile).is_dir()],
    )


def _directory_of(path: Path) -> Path:
    """The directory Finder shows an app in. A `.localized` folder is a wrapper Finder
    hides behind a translated name; the App Store installs some apps in one, such as
    /Applications/Example.localized/Example.app."""
    parent = path.parent
    return parent.parent if parent.suffix == ".localized" else parent


def format_layout(layout: Layout) -> str:
    lines = [f"installed in the wrong directory ({len(layout.misplaced)}):"]
    for item in layout.misplaced:
        app = item.app
        lines.append(
            f"  {app.channel.value:<6}  {app.key}  {app.path}  expected in {item.expected}"
        )
    lines += ["", f"dock tiles with no app ({len(layout.dock_missing)}):"]
    lines += [f"  {tile}" for tile in layout.dock_missing]
    return "\n".join(lines)
