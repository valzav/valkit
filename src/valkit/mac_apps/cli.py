import argparse
import sys
from pathlib import Path

from valkit.mac_apps.apply import Result, apply
from valkit.mac_apps.layout import check_layout, format_layout
from valkit.mac_apps.manifest import ManifestError, parse_manifest
from valkit.mac_apps.model import MANAGED, App, Manifest
from valkit.mac_apps.plan import format_plan, make_plan
from valkit.mac_apps.runner import CommandError, run
from valkit.mac_apps.scan import scan
from valkit.mac_apps.state import load_state, save_state


def read_manifest(source: str) -> Manifest:
    text = sys.stdin.read() if source == "-" else Path(source).expanduser().read_text()
    return parse_manifest(text)


def status(app: App, manifest: Manifest) -> str:
    if app.channel not in MANAGED:
        return "-"
    return "declared" if manifest.declares(app) else "undeclared"


def format_list(apps: list[App], manifest: Manifest | None) -> str:
    """A table sorted by size, largest first; unmeasured apps go last."""
    ordered = sorted(apps, key=lambda app: (app.size is None, -(app.size or 0), app.name.lower()))
    header = ["NAME", "CHANNEL", *(["STATUS"] if manifest else []), "SIZE", "KEY"]
    rows = [
        [
            app.name,
            app.channel.value,
            *([status(app, manifest)] if manifest else []),
            app.size_display,
            app.key or "-",
        ]
        for app in ordered
    ]
    widths = [max(len(row[column]) for row in [header, *rows]) for column in range(len(header))]
    size_column = header.index("SIZE")

    def line(row: list[str]) -> str:
        cells = [
            cell.rjust(width) if column == size_column else cell.ljust(width)
            for column, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        return "  ".join(cells).rstrip()

    return "\n".join(line(row) for row in [header, *rows])


def format_result(result: Result, first_run: bool) -> str:
    if first_run:
        return "first run: recorded the manifest, removed nothing"
    if not result.outcomes:
        return "nothing to remove"
    lines: list[str] = []
    for outcome in result.outcomes:
        entry = outcome.entry
        name = "" if entry.name == entry.key else f" ({entry.name})"
        verdict = "removed" if outcome.error is None else f"FAILED: {outcome.error}"
        lines.append(f"{entry.channel.value} {entry.key}{name}: {verdict}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mac-apps",
        description=(
            "List installed Mac applications and remove the ones deleted from a manifest."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser(
        "list", help="show installed applications with channel and size"
    )
    list_parser.add_argument(
        "--manifest",
        metavar="FILE",
        help="manifest JSON file, or - for standard input; adds the STATUS column",
    )
    for name, help_text in [
        (
            "plan",
            "show what apply would remove, what is missing, undeclared, or misplaced,"
            " and Dock tiles with no app",
        ),
        (
            "apply",
            "remove the applications deleted from the manifest since the last apply,"
            " then fail if an app or Dock tile is misplaced",
        ),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--manifest",
            metavar="FILE",
            required=True,
            help="manifest JSON file, or - for standard input",
        )
    args = parser.parse_args()

    try:
        match args.command:
            case "list":
                manifest = read_manifest(args.manifest) if args.manifest else None
                print(format_list(scan(run).apps, manifest))
            case "plan":
                manifest = read_manifest(args.manifest)
                print(format_plan(make_plan(load_state(), manifest, scan(run))))
            case "apply":
                manifest = read_manifest(args.manifest)
                previous = load_state()
                result = apply(previous, manifest, lambda: scan(run), run)
                save_state(result.state)
                print(format_result(result, first_run=previous is None))
                # Scanned after the removals, so a removed app is not reported.
                layout = check_layout(manifest, scan(run))
                if not layout.ok:
                    print(format_layout(layout))
                if result.failed or not layout.ok:
                    sys.exit(1)
            case _:
                parser.error(f"unknown command {args.command}")
    except (CommandError, ManifestError, OSError, ValueError) as error:
        sys.exit(f"mac-apps: {error}")
