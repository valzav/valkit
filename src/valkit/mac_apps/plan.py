from dataclasses import dataclass

from valkit.mac_apps.layout import Layout, check_layout, format_layout
from valkit.mac_apps.model import Channel, Entry, Inventory, Manifest

_ORDER = [Channel.CASK, Channel.MAS, Channel.MANUAL]
"""Channel order in reports, the same as in the manifest."""


@dataclass(frozen=True)
class Plan:
    remove: list[Entry]
    """In the previous applied manifest, missing from the current one, still installed."""
    missing: list[Entry]
    """Declared but not installed."""
    undeclared: list[Entry]
    """Installed but not declared. Reported, never removed."""
    layout: Layout


def removals(previous: Manifest | None, current: Manifest) -> list[Entry]:
    """Entries in the previous applied manifest and missing from the current one.

    With no previous manifest, on the first run, nothing is removed.
    """
    if previous is None:
        return []
    return [entry for entry in previous.entries() if entry.key not in current.keys(entry.channel)]


def installed(inventory: Inventory) -> list[Entry]:
    """Installed cask, App Store, and manual applications in manifest terms."""
    apps = sorted(
        (app for app in inventory.apps if app.channel in (Channel.MAS, Channel.MANUAL)),
        key=lambda app: (_ORDER.index(app.channel), app.name.lower()),
    )
    return [
        *(Entry(Channel.CASK, token, token) for token in sorted(inventory.casks)),
        # An app with no known key cannot be declared; "-" keeps it in the report.
        *(Entry(app.channel, app.key or "-", app.name) for app in apps),
    ]


def make_plan(previous: Manifest | None, current: Manifest, inventory: Inventory) -> Plan:
    present = installed(inventory)
    present_keys = {(entry.channel, entry.key) for entry in present}
    return Plan(
        remove=[
            entry
            for entry in removals(previous, current)
            if (entry.channel, entry.key) in present_keys
        ],
        missing=[
            entry for entry in current.entries() if (entry.channel, entry.key) not in present_keys
        ],
        undeclared=[entry for entry in present if entry.key not in current.keys(entry.channel)],
        layout=check_layout(current, inventory),
    )


def format_plan(plan: Plan) -> str:
    def group(title: str, entries: list[Entry], with_url: bool = False) -> list[str]:
        lines = [f"{title} ({len(entries)}):"]
        for entry in entries:
            name = "" if entry.name == entry.key else f"  {entry.name}"
            url = f"  {entry.url}" if with_url and entry.url else ""
            lines.append(f"  {entry.channel.value:<6}  {entry.key}{name}{url}")
        return lines

    return "\n".join(
        [
            *group("apply will remove", plan.remove),
            "",
            *group("declared, not installed", plan.missing, with_url=True),
            "",
            *group("installed, not declared", plan.undeclared),
            "",
            format_layout(plan.layout),
        ]
    )
