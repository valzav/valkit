import pytest

from tests.mac_apps.conftest import FakeMac
from valkit.mac_apps.model import Channel
from valkit.mac_apps.scan import format_size, parse_size


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.23GB", 1_230_000_000),
        ("45.6MB", 45_600_000),
        ("12KB", 12_000),
        ("500B", 500),
        ("--", None),
        ("N/A", None),
        ("N/A (Steam-managed)", None),
    ],
)
def test_parse_size(text: str, expected: int | None) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["1.23GB", "45.6MB", "12KB", "500B"])
def test_format_size_matches_mole(text: str) -> None:
    size = parse_size(text)
    assert size is not None
    assert format_size(size) == text


def test_channels_and_keys(mac: FakeMac) -> None:
    mac.add("Example Browser", "com.example.browser", cask="example-browser")
    mac.add("Example Notes", "com.example.notes", app_store_id="123456789")
    mac.add("Example Printer", "com.example.printer")
    mac.add("Example Editor", "org.example.editor", in_store=True)
    mac.add("Safari", "com.apple.Safari")
    mac.add("Pages", "com.apple.iWork.Pages", app_store_id="987654321")

    apps = {app.name: app for app in mac.scan().apps}

    assert (apps["Example Browser"].channel, apps["Example Browser"].key) == (
        Channel.CASK,
        "example-browser",
    )
    assert (apps["Example Notes"].channel, apps["Example Notes"].key) == (Channel.MAS, "123456789")
    assert (apps["Example Printer"].channel, apps["Example Printer"].key) == (
        Channel.MANUAL,
        "com.example.printer",
    )
    assert apps["Example Editor"].channel is Channel.NIX
    assert apps["Safari"].channel is Channel.SYSTEM
    # An Apple app with an App Store receipt belongs to the App Store channel.
    assert (apps["Pages"].channel, apps["Pages"].key) == (Channel.MAS, "987654321")


def test_cask_ownership_comes_from_brew_not_mole(mac: FakeMac) -> None:
    # Mole reports self-updating cask apps as plain apps.
    mac.add("Example Browser", "com.example.browser", cask="example-browser", mole_source="App")
    # And Mole's Homebrew label alone does not make an app a cask.
    mac.add("Example Tool", "com.example.tool", mole_source="Homebrew")

    apps = {app.name: app for app in mac.scan().apps}

    assert (apps["Example Browser"].channel, apps["Example Browser"].key) == (
        Channel.CASK,
        "example-browser",
    )
    assert apps["Example Tool"].channel is Channel.MANUAL


def test_cask_owns_only_an_app_it_names(mac: FakeMac) -> None:
    # A stale record: brew's target now holds another vendor's app of the same name.
    chat = mac.add(
        "Example Chat",
        "com.example.desktopchat",
        cask="example-chat",
        cask_zap="~/Library/Preferences/com.example.chat.plist",
    )
    mac.add(
        "Example Diff",
        "com.example.diff.v4",
        cask="example-diff",
        cask_zap="~/Library/Preferences/com.example.diff.v*.plist",
    )
    # A glob without a literal reverse-DNS prefix could match any app.
    mac.add("Example Mail", "com.example.mail", cask="example-mail", cask_zap="~/Library/*.mail")

    inventory = mac.scan()
    apps = {app.name: app for app in inventory.apps}

    assert (apps["Example Chat"].channel, apps["Example Chat"].key) == (
        Channel.MANUAL,
        "com.example.desktopchat",
    )
    assert (apps["Example Diff"].channel, apps["Example Diff"].key) == (
        Channel.CASK,
        "example-diff",
    )
    assert apps["Example Mail"].channel is Channel.MANUAL
    assert set(inventory.foreign_casks) == {"example-chat", "example-mail"}
    assert inventory.foreign_casks["example-chat"] == (chat,)


def test_receipt_wins_over_homebrew(mac: FakeMac) -> None:
    mac.add("Example Notes", "com.example.notes", cask="example-notes", app_store_id="123")

    [app] = mac.scan().apps

    assert (app.channel, app.key) == (Channel.MAS, "123")


def test_unknown_ids_have_no_key(mac: FakeMac) -> None:
    mac.add("Mystery", "unknown")
    mac.add("Unindexed", "com.example.unindexed", app_store_id="(null)")

    apps = {app.name: app for app in mac.scan().apps}

    assert apps["Mystery"].key is None
    assert (apps["Unindexed"].channel, apps["Unindexed"].key) == (Channel.MAS, None)


def test_uncached_size_is_measured(mac: FakeMac) -> None:
    mac.add("Fresh", "com.example.fresh", size="--", disk_kb=2048)

    [app] = mac.scan().apps

    assert (app.size, app.size_display) == (2048 * 1024, "2.1MB")


def test_nix_linked_apps_are_added(mac: FakeMac) -> None:
    mac.add("Example Browser", "com.example.browser", cask="example-browser")
    mac.add_nix_app("Example Studio", "io.example.studio", disk_kb=1000)

    apps = {app.name: app for app in mac.scan().apps}

    studio = apps["Example Studio"]
    assert (studio.channel, studio.key, studio.size) == (
        Channel.NIX,
        "io.example.studio",
        1000 * 1024,
    )


def test_invisible_characters_are_dropped_from_names(mac: FakeMac) -> None:
    mac.add("‎Example Chat", "com.example.chat")

    [app] = mac.scan().apps

    assert app.name == "Example Chat"


def test_package_cask_apps_come_from_receipts(mac: FakeMac) -> None:
    mac.add("Example Drive", "com.example.drive")
    mac.add("Example Docs", "com.example.drive.docs")
    mac.add("Example Meet", "com.example.meet")
    mac.add_package_cask(
        "example-drive",
        {
            "com.example.drive.pkg": [
                "Example Drive.app",
                "Example Drive.app/Contents",
                "Example Drive.app/Contents/Helpers/Helper.app",
            ],
            "com.example.drive.shortcuts": ["Example Docs.app"],
            "com.example.drive.missing": [],
        },
    )
    del mac.package_files["com.example.drive.missing"]
    mac.add_package_cask(
        "example-meet", {"com.example.meet.pkg": ["Applications/Example Meet.app"]}
    )

    apps = {app.name: app for app in mac.scan().apps}

    assert (apps["Example Drive"].channel, apps["Example Drive"].key) == (
        Channel.CASK,
        "example-drive",
    )
    assert apps["Example Docs"].key == "example-drive"
    assert apps["Example Meet"].key == "example-meet"
