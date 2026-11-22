"""What earlier runs learned: verdicts, so each email is judged once, and the emails moved."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from valkit.mailkeeper.model import CLASSES

STATE_FILE = Path.home() / ".local" / "state" / "mailkeeper" / "state.json"
"""Kept on the machine. It holds senders and Message-IDs, never a subject or a text."""


class StateError(ValueError):
    pass


@dataclass(frozen=True)
class Judged:
    sender: str
    verdict: str
    """One of `CLASSES`."""


@dataclass
class FolderState:
    uidvalidity: int
    """A UID means the same email only while the folder's UIDVALIDITY stays the same."""
    judged: dict[int, Judged] = field(default_factory=dict[int, Judged])


@dataclass
class State:
    folders: dict[str, FolderState] = field(default_factory=dict[str, FolderState])
    moved: set[str] = field(default_factory=set[str])
    """Message-IDs of the emails a run moved. A run never moves them again."""


def load_state(path: Path = STATE_FILE) -> State:
    """The state of the last `apply`, or an empty state before the first one."""
    if not path.exists():
        return State()
    try:
        data: Any = json.loads(path.read_text())
        root = cast(dict[str, Any], data)
        folders = {
            str(name): FolderState(
                uidvalidity=int(folder["uidvalidity"]),
                judged={
                    int(uid): _judged(entry)
                    for uid, entry in cast(dict[str, Any], folder["judged"]).items()
                },
            )
            for name, folder in cast(dict[str, Any], root["folders"]).items()
        }
        moved = {str(message_id) for message_id in cast(list[Any], root["moved"])}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise StateError(f"{path} is not a mailkeeper state file: {error!r}") from error
    return State(folders=folders, moved=moved)


def _judged(entry: Any) -> Judged:
    fields = cast(dict[str, Any], entry)
    verdict = str(fields["class"])
    if verdict not in CLASSES:
        raise ValueError(f"unknown class {verdict}")
    return Judged(sender=str(fields["sender"]), verdict=verdict)


def state_json(state: State) -> str:
    data = {
        "folders": {
            name: {
                "uidvalidity": folder.uidvalidity,
                "judged": {
                    str(uid): {"sender": judged.sender, "class": judged.verdict}
                    for uid, judged in sorted(folder.judged.items())
                },
            }
            for name, folder in sorted(state.folders.items())
        },
        "moved": sorted(state.moved),
    }
    return json.dumps(data, indent=2) + "\n"


def save_state(state: State, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed over it, so a crash never leaves half a file.
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(state_json(state))
    os.replace(temporary, path)
