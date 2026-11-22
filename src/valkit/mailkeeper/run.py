"""One run: judge the spam folder, then return its wanted emails to the inbox."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from valkit.mailkeeper.config import Config
from valkit.mailkeeper.mailbox import Mailbox, MailboxError
from valkit.mailkeeper.message import read_header, read_text
from valkit.mailkeeper.model import WANTED, EmailText, Header
from valkit.mailkeeper.state import FolderState, Judged, State
from valkit.mailkeeper.trust import trusted

type Detector = Callable[[EmailText], str | None]
"""Names an email's class, or returns None when the model's reply is not valid."""

TRUSTED = "trusted"
INVALID = "no valid reply"


class Action(StrEnum):
    RETURN = "return"
    STAY = "stay"


@dataclass(frozen=True)
class Item:
    header: Header
    verdict: str
    """A class, `TRUSTED`, or `INVALID`."""
    action: Action
    note: str = ""
    """Why a wanted email stays."""


@dataclass
class Survey:
    spam: str
    items: list[Item]
    state: State
    """The given state with this run's verdicts; nothing is saved here."""


@dataclass(frozen=True)
class Returned:
    header: Header
    verdict: str
    mark_error: str = ""
    """Empty when the mark is set."""


@dataclass(frozen=True)
class Failed:
    header: Header
    error: str


@dataclass
class Result:
    state: State
    returned: list[Returned] = field(default_factory=list[Returned])
    failed: list[Failed] = field(default_factory=list[Failed])


def survey(mailbox: Mailbox, detector: Detector, config: Config, state: State) -> Survey:
    """Judge every email of the spam folder and decide what `apply` does with it.

    A trusted sender's email is never sent to the model. Every other email is judged once;
    a reply that breaks the schema records nothing, so a later run judges the email again.
    """
    spam = mailbox.spam
    uidvalidity, uids = mailbox.uids(spam)
    present = set(uids)
    earlier = state.folders.get(spam)
    judged = (
        {uid: entry for uid, entry in earlier.judged.items() if uid in present}
        if earlier is not None and earlier.uidvalidity == uidvalidity
        else {}
    )
    raw = mailbox.headers(spam, uids)
    headers = [read_header(uid, raw[uid], config.authserv_id) for uid in uids if uid in raw]

    wrote: dict[str, bool] = {}

    def wrote_to(address: str) -> bool:
        if address not in wrote:
            wrote[address] = mailbox.wrote_to(address)
        return wrote[address]

    trust = {header.uid: trusted(header, config, wrote_to) for header in headers}
    unjudged = [h.uid for h in headers if not trust[h.uid] and h.uid not in judged]
    bodies = mailbox.messages(spam, unjudged)
    invalid: set[int] = set()
    for header in headers:
        if header.uid not in unjudged or header.uid not in bodies:
            continue
        verdict = detector(read_text(bodies[header.uid]))
        if verdict is None:
            invalid.add(header.uid)
        else:
            judged[header.uid] = Judged(sender=header.sender, verdict=verdict)

    items: list[Item] = []
    for header in headers:
        if trust[header.uid]:
            verdict = TRUSTED
        elif header.uid in judged:
            verdict = judged[header.uid].verdict
        elif header.uid in invalid:
            verdict = INVALID
        else:
            continue  # vanished between the header and the body fetch
        items.append(_decide(header, verdict, state.moved))

    folders = {**state.folders, spam: FolderState(uidvalidity=uidvalidity, judged=judged)}
    return Survey(spam=spam, items=items, state=State(folders=folders, moved=set(state.moved)))


def _decide(header: Header, verdict: str, moved: set[str]) -> Item:
    if verdict != TRUSTED and verdict not in WANTED:
        return Item(header, verdict, Action.STAY)
    if not header.message_id:
        # Without a Message-ID a later run cannot tell that this email was moved before.
        return Item(header, verdict, Action.STAY, "no Message-ID")
    if header.message_id in moved:
        return Item(header, verdict, Action.STAY, "moved before")
    return Item(header, verdict, Action.RETURN)


def apply_returns(mailbox: Mailbox, survey: Survey, mark: str) -> Result:
    """Move each email to return into the inbox, then mark it."""
    result = Result(state=survey.state)
    moved: list[tuple[Item, int | None]] = []
    for item in survey.items:
        if item.action is not Action.RETURN:
            continue
        try:
            new_uid = mailbox.move_to_inbox(survey.spam, item.header.uid)
        except MailboxError as error:
            result.failed.append(Failed(item.header, str(error)))
            continue
        result.state.moved.add(item.header.message_id)
        moved.append((item, new_uid))
    for item, new_uid in moved:
        if new_uid is None:
            result.returned.append(
                Returned(item.header, item.verdict, "the server did not name the new UID")
            )
            continue
        try:
            mailbox.mark(new_uid, mark)
        except MailboxError as error:
            result.returned.append(Returned(item.header, item.verdict, str(error)))
            continue
        result.returned.append(Returned(item.header, item.verdict))
    return result
