from collections.abc import Callable
from dataclasses import dataclass

from valkit.mac_apps.model import (
    App,
    Channel,
    Entry,
    Inventory,
    Manifest,
    manifest_from_entries,
)
from valkit.mac_apps.plan import removals
from valkit.mac_apps.runner import CommandError, Runner


@dataclass(frozen=True)
class Outcome:
    entry: Entry
    error: str | None
    """None when the application is gone."""


@dataclass(frozen=True)
class Result:
    outcomes: list[Outcome]
    state: Manifest
    """The manifest to save: the current one plus every entry whose removal failed."""

    @property
    def failed(self) -> list[Outcome]:
        return [outcome for outcome in self.outcomes if outcome.error is not None]


def apply(
    previous: Manifest | None,
    current: Manifest,
    scan: Callable[[], Inventory],
    run: Runner,
) -> Result:
    """Remove each entry that was in the previous applied manifest and is missing now.

    Scans only when something is to be removed, so a run with no removals is fast.
    """
    pending = removals(previous, current)
    outcomes: list[Outcome] = []
    if pending:
        inventory = scan()
        outcomes = [Outcome(entry, remove(entry, inventory, run)) for entry in pending]
    failed = [outcome.entry for outcome in outcomes if outcome.error is not None]
    return Result(
        outcomes=outcomes, state=manifest_from_entries(current.entries() + failed, current.dock)
    )


def remove(entry: Entry, inventory: Inventory, run: Runner) -> str | None:
    """Remove one entry. Returns None when the application is gone, else the reason."""
    try:
        match entry.channel:
            case Channel.CASK:
                foreign = inventory.foreign_casks.get(entry.key)
                if foreign:
                    paths = ", ".join(str(path) for path in foreign)
                    return (
                        f"{paths} holds an app the cask does not name, which uninstalling"
                        f" would delete; move it aside, run `brew uninstall --force --zap"
                        f" --cask {entry.key}`, and move it back"
                    )
                if entry.key in inventory.casks:
                    run(["brew", "uninstall", "--zap", "--cask", entry.key])
                return None
            case Channel.MAS:
                targets = _targets(entry, inventory)
                if targets:
                    # mas 5.2.0 refuses to uninstall without root.
                    run(["sudo", "mas", "uninstall", entry.key])
                return _still_installed(targets)
            case Channel.MANUAL:
                return _remove_manual(entry, inventory, run)
            case Channel.NIX | Channel.SYSTEM:
                return f"{entry.channel} apps are never removed"
    except CommandError as error:
        return str(error)


def _remove_manual(entry: Entry, inventory: Inventory, run: Runner) -> str | None:
    targets = _targets(entry, inventory)
    if not targets:
        return None
    if len(targets) > 1:
        paths = ", ".join(str(app.path) for app in targets)
        return f"{len(targets)} copies installed ({paths}); remove them by hand"
    [target] = targets
    # Mole selects by name, not path: the first app whose display name or bundle file
    # name equals the argument. Removal proceeds only if that can be no other app.
    name = target.uninstall_name.casefold()
    namesakes = [
        app for app in inventory.apps if name in (app.name.casefold(), app.path.stem.casefold())
    ]
    if namesakes != [target]:
        paths = ", ".join(str(app.path) for app in namesakes if app is not target)
        return f"Mole could also select {paths}; remove {target.path} by hand"
    # Mole asks "Proceed? [y/N]", then for one key where end of input confirms. It
    # exits 0 even when it aborts, so the result is checked on disk.
    run(["mo", "uninstall", target.uninstall_name], stdin="y\n")
    return _still_installed(targets)


def _targets(entry: Entry, inventory: Inventory) -> list[App]:
    return [app for app in inventory.apps if app.channel == entry.channel and app.key == entry.key]


def _still_installed(targets: list[App]) -> str | None:
    left = [str(app.path) for app in targets if app.path.exists()]
    return f"still installed: {', '.join(left)}" if left else None
