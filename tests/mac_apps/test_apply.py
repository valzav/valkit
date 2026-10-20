from pathlib import Path

from tests.mac_apps.conftest import FakeMac
from valkit.mac_apps.apply import Result, apply
from valkit.mac_apps.model import Channel, Inventory, Manifest, ManualApp
from valkit.mac_apps.plan import format_plan, make_plan
from valkit.mac_apps.state import load_state, save_state

APPS = "/Applications"
PRINTER = ManualApp(bundle_id="com.example.printer", url="https://example.com/printer", dir=APPS)


def manifest(
    casks: tuple[str, ...] = (),
    mas: dict[str, int] | None = None,
    manual: dict[str, ManualApp] | None = None,
) -> Manifest:
    return Manifest(casks=dict.fromkeys(casks, APPS), mas=mas or {}, manual=manual or {})


FULL = manifest(
    casks=("example-browser", "example-cli"),
    mas={"Example Notes": 123456789},
    manual={"Example Printer": PRINTER},
)


def install_all(mac: FakeMac) -> dict[str, Path]:
    return {
        "browser": mac.add("Example Browser", "com.example.browser", cask="example-browser"),
        "notes": mac.add("Example Notes", "com.example.notes", app_store_id="123456789"),
        "printer": mac.add("Example Printer", "com.example.printer"),
        "stray": mac.add("Example Stray", "com.example.stray"),
    }


def run_apply(mac: FakeMac, previous: Manifest | None, current: Manifest) -> Result:
    return apply(previous, current, mac.scan, mac.run)


def test_first_run_removes_nothing(mac: FakeMac) -> None:
    paths = install_all(mac)

    result = run_apply(mac, None, manifest())

    assert result.outcomes == []
    assert mac.calls == []
    assert all(path.exists() for path in paths.values())


def test_no_removals_skips_the_scan(mac: FakeMac) -> None:
    def scan() -> Inventory:
        raise AssertionError("scanned with nothing to remove")

    result = apply(FULL, FULL, scan, mac.run)

    assert result.outcomes == []
    assert result.state == FULL


def test_each_channel_removes_a_deleted_entry(mac: FakeMac) -> None:
    paths = install_all(mac)
    mac.add_cask_without_app("example-cli")

    result = run_apply(mac, FULL, manifest())

    assert [(o.entry.channel, o.entry.key, o.error) for o in result.outcomes] == [
        (Channel.CASK, "example-browser", None),
        (Channel.CASK, "example-cli", None),
        (Channel.MAS, "123456789", None),
        (Channel.MANUAL, "com.example.printer", None),
    ]
    assert mac.calls == [
        ["brew", "uninstall", "--zap", "--cask", "example-browser"],
        ["brew", "uninstall", "--zap", "--cask", "example-cli"],
        ["sudo", "mas", "uninstall", "123456789"],
        ["mo", "uninstall", "Example Printer"],
    ]
    assert not paths["browser"].exists()
    assert not paths["notes"].exists()
    assert not paths["printer"].exists()
    assert result.state == manifest()


def test_undeclared_app_is_never_removed(mac: FakeMac) -> None:
    paths = install_all(mac)

    run_apply(mac, FULL, manifest())

    assert paths["stray"].exists()
    assert all("Example Stray" not in call for call in mac.calls)


def test_kept_entry_is_not_removed(mac: FakeMac) -> None:
    paths = install_all(mac)

    result = run_apply(mac, FULL, manifest(casks=("example-browser", "example-cli")))

    assert paths["browser"].exists()
    assert {o.entry.key for o in result.outcomes} == {
        "123456789",
        "com.example.printer",
    }


def test_entry_already_gone_is_dropped(mac: FakeMac) -> None:
    result = run_apply(mac, FULL, manifest())

    assert mac.calls == []
    assert result.failed == []
    assert result.state == manifest()


def test_cask_over_another_app_is_not_zapped(mac: FakeMac) -> None:
    chat = mac.add(
        "Example Chat",
        "com.example.desktopchat",
        cask="example-chat",
        cask_zap="~/Library/Preferences/com.example.chat.plist",
    )

    result = run_apply(mac, manifest(casks=("example-chat",)), manifest())

    [failure] = result.failed
    assert failure.error is not None and str(chat) in failure.error
    assert mac.calls == []
    assert chat.exists()
    assert result.state == manifest(casks=("example-chat",))


def test_failed_removal_stays_in_state(mac: FakeMac) -> None:
    paths = install_all(mac)
    mac.failing.add("123456789")

    result = run_apply(mac, FULL, manifest(casks=("example-browser", "example-cli")))

    [failure] = result.failed
    assert failure.entry.key == "123456789"
    assert failure.error is not None and "synthetic failure" in failure.error
    assert paths["notes"].exists()
    assert result.state == manifest(
        casks=("example-browser", "example-cli"), mas={"Example Notes": 123456789}
    )


def test_silent_mole_abort_is_a_failure(mac: FakeMac) -> None:
    paths = install_all(mac)
    mac.inert.add("Example Printer")

    result = run_apply(mac, FULL, manifest())

    [failure] = result.failed
    assert failure.error == f"still installed: {paths['printer']}"
    assert result.state.manual == {"Example Printer": PRINTER}


def test_manual_removal_skipped_when_mole_could_pick_another_app(mac: FakeMac) -> None:
    paths = install_all(mac)
    other = mac.add("Example Printer", "com.example.other-printer", folder="Other")

    result = run_apply(mac, FULL, manifest(casks=("example-browser",), mas=FULL.mas))

    [failure] = result.failed
    assert failure.entry.key == "com.example.printer"
    assert failure.error is not None and str(other) in failure.error
    assert all(call[:2] != ["mo", "uninstall"] for call in mac.calls)
    assert paths["printer"].exists() and other.exists()


def test_plan_groups(mac: FakeMac) -> None:
    install_all(mac)
    mac.add("Example Chat", "com.example.chat", app_store_id="555")
    mac.add("Safari", "com.apple.Safari")
    previous = manifest(casks=("example-browser", "example-old"), mas=FULL.mas)
    current = manifest(
        casks=("example-editor",),
        mas=FULL.mas,
        manual={
            "Example Printer": PRINTER,
            "Example Scanner": ManualApp("com.example.scanner", "https://example.com/scan", APPS),
        },
    )

    plan = make_plan(previous, current, mac.scan())

    assert [(e.channel, e.key) for e in plan.remove] == [(Channel.CASK, "example-browser")]
    assert [(e.channel, e.key, e.url) for e in plan.missing] == [
        (Channel.CASK, "example-editor", None),
        (Channel.MANUAL, "com.example.scanner", "https://example.com/scan"),
    ]
    assert [(e.channel, e.key) for e in plan.undeclared] == [
        (Channel.CASK, "example-browser"),
        (Channel.MAS, "555"),
        (Channel.MANUAL, "com.example.stray"),
    ]
    text = format_plan(plan)
    assert "apply will remove (1):" in text
    assert "https://example.com/scan" in text


def test_plan_on_first_run_removes_nothing(mac: FakeMac) -> None:
    install_all(mac)

    assert make_plan(None, manifest(), mac.scan()).remove == []


def test_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "applied.json"

    assert load_state(path) is None
    save_state(FULL, path)

    assert load_state(path) == FULL
    assert [entry.name for entry in path.parent.iterdir()] == ["applied.json"]
