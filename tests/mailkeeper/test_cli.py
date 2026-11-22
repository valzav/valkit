import imaplib
import json
import sys
from pathlib import Path

import pytest

from valkit.mailkeeper import cli

from .conftest import config_data


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    def no_connection(host: str) -> imaplib.IMAP4_SSL:
        raise AssertionError(f"connected to {host}")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", no_connection)
    monkeypatch.setattr(sys, "argv", ["mailkeeper", *args])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    return str(stopped.value.code)


def write(tmp_path: Path, data: dict[str, object]) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_a_wrong_configuration_stops_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write(tmp_path, config_data(unknown=True))

    assert "unknown keys: unknown" in run_main(monkeypatch, "plan", "--config", config)


def test_a_missing_password_stops_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_IMAP_PASSWORD", raising=False)
    config = write(tmp_path, config_data())

    assert "TEST_IMAP_PASSWORD holds no password" in run_main(
        monkeypatch, "plan", "--config", config
    )


def test_apply_needs_the_report_folder_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_IMAP_PASSWORD", "secret")
    config = write(tmp_path, config_data(report_dir=str(tmp_path / "missing")))

    assert "is not a folder" in run_main(monkeypatch, "apply", "--config", config)
