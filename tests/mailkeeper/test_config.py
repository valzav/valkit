import json
from pathlib import Path

import pytest

from valkit.mailkeeper.config import ConfigError, parse_config

from .conftest import config_data


def test_a_full_configuration_parses() -> None:
    data = config_data(
        own_addresses=["Owner@Example.TEST"],
        folders={"spam": "Junk", "sent": "Sent Items"},
    )

    config = parse_config(json.dumps(data))

    assert config.imap_host == "imap.example.test"
    assert config.password_env == "TEST_IMAP_PASSWORD"
    assert config.own_addresses == {"owner@example.test"}
    assert config.own_domains == {"example.test", "club.example"}
    assert config.report_dir == Path.home() / "reports"
    assert (config.spam_folder, config.sent_folder) == ("Junk", "Sent Items")


def test_folders_are_optional() -> None:
    config = parse_config(json.dumps(config_data()))

    assert (config.spam_folder, config.sent_folder) == (None, None)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (config_data(extra=1), "unknown keys: extra"),
        (config_data(imap={"host": "h", "user": "u", "password_env": "P", "port": 993}), "port"),
        (config_data(folders={"trash": "Bin"}), "unknown keys: trash"),
        ({k: v for k, v in config_data().items() if k != "mark"}, "missing mark"),
        (config_data(model={"base_url": "http://x"}), "model is missing name"),
        (config_data(mark="from spam"), "mark may hold only"),
        (config_data(owner={"name": "", "description": "d"}), "owner.name"),
        (config_data(own_domains="example.test"), "list of strings"),
        (config_data(imap=[]), "imap must be a JSON object"),
    ],
)
def test_a_wrong_configuration_is_an_error(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(json.dumps(data))


def test_text_that_is_not_json_is_an_error() -> None:
    with pytest.raises(ConfigError, match="not valid JSON"):
        parse_config("{")
