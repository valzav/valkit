"""The configuration file: one JSON object, read strictly before anything connects."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# A mark is sent unquoted as a Gmail label or an IMAP keyword, so it must be a plain atom.
MARK_RE = re.compile(r"[A-Za-z0-9_-]+")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    imap_host: str
    imap_user: str
    password_env: str
    """The environment variable that holds the IMAP password. The file holds no password."""
    model_url: str
    """Base URL of a model server with an OpenAI-compatible API, such as http://host/v1."""
    model_name: str
    owner_name: str
    owner_description: str
    """Who owns the mailbox, as the detector's first sentence names them."""
    own_addresses: frozenset[str]
    own_domains: frozenset[str]
    mark: str
    report_dir: Path
    authserv_id: str
    """The receiving server whose Authentication-Results header counts."""
    spam_folder: str | None
    """Overrides the folder the server marks \\Junk."""
    sent_folder: str | None
    """Overrides the folder the server marks \\Sent."""


def parse_config(text: str) -> Config:
    """Parse the configuration JSON. An unknown or missing key is an error.

    {"imap": {"host", "user", "password_env"}, "model": {"base_url", "name"},
     "owner": {"name", "description"}, "own_addresses": [...], "own_domains": [...],
     "mark", "report_dir", "authserv_id", optional "folders": {"spam"?, "sent"?}}
    """
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(f"configuration is not valid JSON: {error}") from error
    root = _fields(
        data,
        "configuration",
        required={
            "imap",
            "model",
            "owner",
            "own_addresses",
            "own_domains",
            "mark",
            "report_dir",
            "authserv_id",
        },
        optional={"folders"},
    )
    imap = _fields(root["imap"], "imap", required={"host", "user", "password_env"})
    model = _fields(root["model"], "model", required={"base_url", "name"})
    owner = _fields(root["owner"], "owner", required={"name", "description"})
    folders = _fields(root.get("folders", {}), "folders", optional={"spam", "sent"})
    mark = _string(root["mark"], "mark")
    if not MARK_RE.fullmatch(mark):
        raise ConfigError("mark may hold only letters, digits, '-' and '_'")
    return Config(
        imap_host=_string(imap["host"], "imap.host"),
        imap_user=_string(imap["user"], "imap.user"),
        password_env=_string(imap["password_env"], "imap.password_env"),
        model_url=_string(model["base_url"], "model.base_url"),
        model_name=_string(model["name"], "model.name"),
        owner_name=_string(owner["name"], "owner.name"),
        owner_description=_string(owner["description"], "owner.description"),
        own_addresses=frozenset(
            a.lower() for a in _strings(root["own_addresses"], "own_addresses")
        ),
        own_domains=frozenset(d.lower() for d in _strings(root["own_domains"], "own_domains")),
        mark=mark,
        report_dir=Path(_string(root["report_dir"], "report_dir")).expanduser(),
        authserv_id=_string(root["authserv_id"], "authserv_id").lower(),
        spam_folder=_string(folders["spam"], "folders.spam") if "spam" in folders else None,
        sent_folder=_string(folders["sent"], "folders.sent") if "sent" in folders else None,
    )


def _fields(
    value: Any, where: str, required: set[str] | None = None, optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a JSON object")
    fields = cast(dict[str, Any], value)
    required = required or set()
    unknown = fields.keys() - required - (optional or set())
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    missing = required - fields.keys()
    if missing:
        raise ConfigError(f"{where} is missing {', '.join(sorted(missing))}")
    return fields


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string")
    return value.strip()


def _strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{where} must be a list of strings")
    return [_string(item, where) for item in cast(list[Any], value)]
