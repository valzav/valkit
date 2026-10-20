import pytest

from tests.mac_apps.conftest import FakeMac
from valkit.mac_apps.layout import check_layout, format_layout
from valkit.mac_apps.manifest import manifest_json, parse_manifest
from valkit.mac_apps.model import Manifest, ManualApp


def layout_manifest(mac: FakeMac, dock: tuple[str, ...] = ()) -> Manifest:
    system = str(mac.root / "Applications")
    user = str(mac.root / "Home")
    return Manifest(
        casks={"example-browser": user, "example-drive": system},
        mas={"Example Notes": 123456789},
        manual={"Example Printer": ManualApp("com.example.printer", "https://example.com", user)},
        dock=dock,
    )


def test_every_app_in_its_directory(mac: FakeMac) -> None:
    browser = mac.add(
        "Example Browser", "com.example.browser", cask="example-browser", folder="Home"
    )
    mac.add("Example Drive", "com.example.drive", cask="example-drive")
    mac.add("Example Notes", "com.example.notes", app_store_id="123456789")
    mac.add("Example Printer", "com.example.printer", folder="Home")
    mac.add("Example Stray", "com.example.stray", folder="Elsewhere")

    layout = check_layout(
        layout_manifest(mac, dock=(str(browser),)),
        mac.scan(),
        mac.root / "Applications",
    )

    assert layout.ok


def test_misplaced_and_duplicate_copies_are_reported(mac: FakeMac) -> None:
    mac.add("Example Browser", "com.example.browser", cask="example-browser")
    mac.add("Example Notes", "com.example.notes", app_store_id="123456789", folder="Home")
    mac.add("Example Printer", "com.example.printer", folder="Home")
    extra = mac.add("Example Printer", "com.example.printer", folder="Applications")

    layout = check_layout(layout_manifest(mac), mac.scan(), mac.root / "Applications")

    assert [(item.app.key, item.app.path, item.expected) for item in layout.misplaced] == [
        (
            "example-browser",
            mac.root / "Applications" / "Example Browser.app",
            str(mac.root / "Home"),
        ),
        ("com.example.printer", extra, str(mac.root / "Home")),
        (
            "123456789",
            mac.root / "Home" / "Example Notes.app",
            str(mac.root / "Applications"),
        ),
    ]
    assert not layout.ok


def test_localized_wrapper_counts_as_its_parent(mac: FakeMac) -> None:
    mac.add(
        "Example Notes",
        "com.example.notes",
        app_store_id="123456789",
        folder="Applications/Example Notes.localized",
    )
    mac.add("Example Printer", "com.example.printer", folder="Elsewhere/Example.localized")

    layout = check_layout(layout_manifest(mac), mac.scan(), mac.root / "Applications")

    assert [item.app.key for item in layout.misplaced] == ["com.example.printer"]


def test_dock_tile_with_no_app(mac: FakeMac) -> None:
    mac.add("Example Browser", "com.example.browser", cask="example-browser")
    tile = str(mac.root / "Home" / "Example Browser.app")

    layout = check_layout(layout_manifest(mac, dock=(tile,)), mac.scan(), mac.root / "Applications")

    assert layout.dock_missing == [tile]
    assert f"dock tiles with no app (1):\n  {tile}" in format_layout(layout)


def test_tilde_directory_expands(mac: FakeMac, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(mac.root))
    mac.add("Example Browser", "com.example.browser", cask="example-browser", folder="Home")
    manifest = Manifest(casks={"example-browser": "~/Home"}, mas={}, manual={})

    assert check_layout(manifest, mac.scan()).ok


def test_manifest_json_round_trip(mac: FakeMac) -> None:
    manifest = layout_manifest(mac, dock=("/System/Applications/Mail.app",))

    assert parse_manifest(manifest_json(manifest)) == manifest
