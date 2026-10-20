import json
import plistlib
import re
import unicodedata
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, cast

from valkit.mac_apps.model import App, Channel, Inventory
from valkit.mac_apps.runner import CommandError, Runner

NIX_STORE = Path("/nix/store")

# Mole skips these: home-manager and nix-darwin link store apps here, and Mole does
# not descend into a symlinked folder.
NIX_APP_DIRS = (
    Path.home() / "Applications" / "Home Manager Apps",
    Path("/Applications/Nix Apps"),
)

# Mole prints sizes in decimal units, for example "1.23GB", "45.6MB", "12KB". An app
# missing from its size cache (every app on the first run) shows "--".
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)$")
_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}


def parse_size(text: str) -> int | None:
    match = _SIZE.match(text.strip())
    if match is None:
        return None
    return round(float(match.group(1)) * _UNITS[match.group(2)])


def format_size(size: int) -> str:
    """The same decimal format Mole uses, so measured and cached sizes look alike."""
    if size >= 10**9:
        return f"{size / 10**9:.2f}GB"
    if size >= 10**6:
        return f"{size / 10**6:.1f}MB"
    if size >= 10**3:
        return f"{round(size / 10**3)}KB"
    return f"{size}B"


def scan(
    run: Runner, nix_store: Path = NIX_STORE, nix_app_dirs: tuple[Path, ...] = NIX_APP_DIRS
) -> Inventory:
    """Every installed application: Mole's scan plus the nix-linked apps it skips."""
    # Mole switches this command to JSON when its output is not a terminal.
    data: Any = json.loads(run(["mo", "uninstall", "--list"]))
    if not isinstance(data, list):
        raise ValueError("mo uninstall --list did not return a JSON list")
    casks = installed_casks(run)
    apps = [
        _app(cast(dict[str, str], entry), casks.owners, run, nix_store)
        for entry in cast(list[Any], data)
    ]
    seen = {app.path for app in apps}
    apps.extend(_nix_app(path, run) for path in _bundles(nix_app_dirs) if path not in seen)
    return Inventory(apps=apps, casks=casks.tokens, foreign_casks=casks.foreign)


@dataclass(frozen=True)
class Casks:
    tokens: frozenset[str]
    """Every installed cask token."""
    owners: dict[str, str]
    """Each cask app's path, or bundle name when brew gives no path, to its token."""
    foreign: dict[str, tuple[Path, ...]]
    """Casks whose app target holds an app the cask does not name, to those targets."""


def installed_casks(run: Runner) -> Casks:
    """The installed casks and the apps they own.

    Taken from brew itself: Mole's own cask detection misses casks whose app updates
    itself. brew records only the path it installed an app to, not which app, so a
    stale record can point at another app of the same name. A cask owns the app at its
    target only when its own uninstall or zap steps name that app's bundle ID.
    """
    data: Any = json.loads(run(["brew", "info", "--installed", "--cask", "--json=v2"]))
    casks = cast(list[dict[str, Any]], data["casks"])
    owners: dict[str, str] = {}
    foreign: dict[str, tuple[Path, ...]] = {}
    for cask in casks:
        token = cast(str, cask["token"])
        artifacts = cast(list[Any], cask["artifacts"])
        named = _cleanup_strings(artifacts)
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            fields = cast(dict[str, Any], artifact)
            target = fields.get("target")
            if "app" in fields and isinstance(target, str) and _foreign(Path(target), named):
                foreign[token] = (*foreign.get(token, ()), Path(target))
            elif "app" in fields:
                if isinstance(target, str):
                    owners[target] = token
                for item in cast(list[Any], fields["app"]):
                    if isinstance(item, str):
                        owners[item] = token
                    elif isinstance(item, dict):
                        target = cast(dict[str, Any], item).get("target")
                        if isinstance(target, str):
                            owners[Path(target).name] = token
            # A cask that installs a .pkg names no app, only the package receipts its
            # uninstall removes. The receipts list the bundles.
            for package in _package_ids(fields.get("uninstall")):
                for name in _package_apps(package, run):
                    owners[name] = token
    return Casks(
        tokens=frozenset(cast(str, cask["token"]) for cask in casks),
        owners=owners,
        foreign=foreign,
    )


def _cleanup_strings(artifacts: list[Any]) -> list[str]:
    """Every string in a cask's uninstall and zap steps, lowercased."""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.append(value.lower())
        elif isinstance(value, list):
            for item in cast(list[Any], value):
                walk(item)
        elif isinstance(value, dict):
            for item in cast(dict[str, Any], value).values():
                walk(item)

    for artifact in artifacts:
        if isinstance(artifact, dict):
            fields = cast(dict[str, Any], artifact)
            walk([fields.get("uninstall"), fields.get("zap")])
    return found


def _foreign(target: Path, named: list[str]) -> bool:
    """Whether the cask's app target holds an app the cask does not name. An empty
    target is not foreign: some apps move themselves elsewhere on first launch."""
    if not target.exists():
        return False
    bundle_id = _bundle_id(target)
    return bundle_id is None or not _names(bundle_id.lower(), named)


def _names(bundle_id: str, named: list[str]) -> bool:
    if any(bundle_id in text for text in named):
        return True
    # Zap paths often glob over versioned IDs: app.example.v*.plist names app.example.v4.
    # Only a glob with a literal reverse-DNS prefix counts; `*.slack` would name anything.
    for text in named:
        for part in text.split("/"):
            literal = re.split(r"[*?\[]", part, maxsplit=1)[0]
            if literal == part or "." not in literal.rstrip("."):
                continue
            suffix = part.rsplit(".", 1)[-1]
            if fnmatchcase(bundle_id, part) or fnmatchcase(f"{bundle_id}.{suffix}", part):
                return True
    return False


def _package_ids(uninstall: Any) -> list[str]:
    if not isinstance(uninstall, list):
        return []
    ids: list[str] = []
    for step in cast(list[Any], uninstall):
        if not isinstance(step, dict):
            continue
        value = cast(dict[str, Any], step).get("pkgutil")
        values = cast(list[Any], value) if isinstance(value, list) else [value]
        ids.extend(item for item in values if isinstance(item, str))
    return ids


def _package_apps(package: str, run: Runner) -> list[str]:
    """Bundle names of the apps a package receipt installed, outermost bundles only."""
    try:
        files = run(["pkgutil", "--files", package]).splitlines()
    except CommandError:
        # No such receipt on this Mac, or a pattern brew matches but pkgutil cannot.
        return []
    return [Path(file).name for file in files if file.endswith(".app") and ".app/" not in file]


def _app(entry: dict[str, str], casks: dict[str, str], run: Runner, nix_store: Path) -> App:
    path = Path(entry["path"])
    bundle_id = entry["bundle_id"]
    channel, key = _classify(path, bundle_id, casks, run, nix_store)
    size = parse_size(entry["size"])
    if size is None and entry["size"] == "--":
        size = _measure(path, run)
    return App(
        name=_visible(entry["name"]),
        path=path,
        bundle_id=bundle_id,
        channel=channel,
        key=key,
        size=size,
        size_display=format_size(size) if size is not None else entry["size"],
        uninstall_name=entry["uninstall_name"],
    )


def _classify(
    path: Path, bundle_id: str, casks: dict[str, str], run: Runner, nix_store: Path
) -> tuple[Channel, str | None]:
    known_bundle_id = None if bundle_id == "unknown" else bundle_id
    if path.resolve().is_relative_to(nix_store):
        return Channel.NIX, known_bundle_id
    # Checked before Homebrew and Apple: Xcode and Apple's iWork apps come from the App Store.
    if (path / "Contents" / "_MASReceipt" / "receipt").exists():
        return Channel.MAS, _app_store_id(path, run)
    token = casks.get(str(path)) or casks.get(path.name)
    if token is not None:
        return Channel.CASK, token
    if bundle_id.startswith("com.apple."):
        return Channel.SYSTEM, known_bundle_id
    return Channel.MANUAL, known_bundle_id


def _nix_app(path: Path, run: Runner) -> App:
    bundle_id = _bundle_id(path)
    size = _measure(path, run)
    return App(
        name=path.stem,
        path=path,
        bundle_id=bundle_id or "unknown",
        channel=Channel.NIX,
        key=bundle_id,
        size=size,
        size_display=format_size(size) if size is not None else "--",
        uninstall_name=path.stem,
    )


def _bundles(directories: tuple[Path, ...]) -> list[Path]:
    return sorted(
        path for directory in directories if directory.is_dir() for path in directory.glob("*.app")
    )


def _bundle_id(path: Path) -> str | None:
    try:
        with (path / "Contents" / "Info.plist").open("rb") as file:
            info: Any = plistlib.load(file)
    except OSError, plistlib.InvalidFileException:
        return None
    value = cast(dict[str, Any], info).get("CFBundleIdentifier") if isinstance(info, dict) else None
    return value if isinstance(value, str) else None


def _measure(path: Path, run: Runner) -> int | None:
    # -H follows a symlink given on the command line (nix-linked apps are one) and no
    # other, so the store bundle is measured without walking links inside it.
    output = run(["du", "-skH", str(path)]).split()
    return int(output[0]) * 1024 if output and output[0].isdigit() else None


def _app_store_id(path: Path, run: Runner) -> str | None:
    output = run(["mdls", "-raw", "-name", "kMDItemAppStoreAdamID", str(path)]).strip()
    return output if output.isdigit() else None


def _visible(name: str) -> str:
    """Drops invisible format characters; some apps name themselves with a leading LRM."""
    return "".join(char for char in name if unicodedata.category(char) != "Cf")
