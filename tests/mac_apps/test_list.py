import json

import pytest

from tests.mac_apps.conftest import FakeMac
from valkit.mac_apps.cli import format_list
from valkit.mac_apps.manifest import ManifestError, parse_manifest

MANIFEST = json.dumps(
    {
        "casks": {"example-browser": {"dir": "/Applications"}},
        "mas": {"Example Notes": 123456789},
        "manual": {
            "Example Printer": {
                "bundleId": "com.example.printer",
                "url": "https://example.com/printer",
                "dir": "/Applications",
            }
        },
        "dock": [],
    }
)


def rows(text: str) -> list[list[str]]:
    return [line.split() for line in text.splitlines()]


def test_sorted_by_size_largest_first(mac: FakeMac) -> None:
    mac.add("Small", "com.example.small", size="900KB")
    mac.add("Unmeasured", "com.example.unmeasured", size="N/A")
    mac.add("Large", "com.example.large", size="1.50GB")
    mac.add("Medium", "com.example.medium", size="200.0MB")

    table = rows(format_list(mac.scan().apps, None))

    assert table[0] == ["NAME", "CHANNEL", "SIZE", "KEY"]
    assert [row[0] for row in table[1:]] == ["Large", "Medium", "Small", "Unmeasured"]


def test_status_with_manifest(mac: FakeMac) -> None:
    mac.add("Browser", "com.example.browser", cask="example-browser")
    mac.add("Notes", "com.example.notes", app_store_id="123456789")
    mac.add("Printer", "com.example.printer")
    mac.add("Stray", "com.example.stray", cask="example-stray")
    mac.add("Chat", "com.example.chat", app_store_id="555")
    mac.add("Tool", "com.example.tool")
    mac.add("Safari", "com.apple.Safari")

    table = format_list(mac.scan().apps, parse_manifest(MANIFEST))
    status = {row[0]: row[2] for row in rows(table)[1:]}

    assert status == {
        "Browser": "declared",
        "Notes": "declared",
        "Printer": "declared",
        "Stray": "undeclared",
        "Chat": "undeclared",
        "Tool": "undeclared",
        "Safari": "-",
    }


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"casks": {}, "mas": {}, "manual": {}}',
        '{"casks": ["arc"], "mas": {}, "manual": {}, "dock": []}',
        '{"casks": {"arc": {}}, "mas": {}, "manual": {}, "dock": []}',
        '{"casks": {}, "mas": {"Notes": "123"}, "manual": {}, "dock": []}',
        '{"casks": {}, "mas": {}, "manual": {"T": {"url": "u", "dir": "/A"}}, "dock": []}',
        '{"casks": {}, "mas": {}, "manual": {}, "dock": [1]}',
    ],
)
def test_invalid_manifest(text: str) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(text)
