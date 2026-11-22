import argparse
import contextlib
import imaplib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from valkit.mailkeeper.config import Config, ConfigError, parse_config
from valkit.mailkeeper.detector import DetectorError, ModelDetector
from valkit.mailkeeper.mailbox import ImapMailbox, MailboxError
from valkit.mailkeeper.model import Header
from valkit.mailkeeper.report import plain, render_report, write_report
from valkit.mailkeeper.run import Action, Item, Result, Survey, apply_returns, survey
from valkit.mailkeeper.state import StateError, load_state, save_state


def describe(header: Header) -> str:
    return plain(f"{header.date}  {header.from_text}  {header.subject}")


def format_plan(result: Survey) -> str:
    returns = [item for item in result.items if item.action is Action.RETURN]
    stays = sorted(
        (item for item in result.items if item.action is Action.STAY),
        key=lambda item: (item.verdict, item.header.uid),
    )
    width = max((len(item.verdict) for item in result.items), default=0)

    def line(item: Item) -> str:
        note = f"  ({item.note})" if item.note else ""
        return f"{item.action.value:<6}  {item.verdict:<{width}}  {describe(item.header)}{note}"

    head = (
        f"spam folder {plain(result.spam)}: {len(result.items)} emails,"
        f" apply would return {len(returns)}"
    )
    return "\n".join([head, *(line(item) for item in [*returns, *stays])])


def format_result(result: Result, report: Path | None) -> str:
    if not result.returned and not result.failed:
        return "nothing to return"
    lines = [f"returned {len(result.returned)} emails to the inbox"]
    for returned in result.returned:
        note = f"  (not marked: {plain(returned.mark_error)})" if returned.mark_error else ""
        lines.append(f"  {returned.verdict}  {describe(returned.header)}{note}")
    for failed in result.failed:
        lines.append(f"  FAILED  {describe(failed.header)}: {plain(failed.error)}")
    if report is not None:
        lines.append(f"report: {report}")
    return "\n".join(lines)


def connect(config: Config) -> tuple[imaplib.IMAP4, ImapMailbox]:
    password = os.environ.get(config.password_env)
    if not password:
        raise ConfigError(f"the environment variable {config.password_env} holds no password")
    try:
        imap = imaplib.IMAP4_SSL(config.imap_host)
    except OSError as error:
        raise MailboxError(f"connecting to {config.imap_host}: {error}") from error
    try:
        mailbox = ImapMailbox.open(
            imap, config.imap_user, password, config.spam_folder, config.sent_folder
        )
    except MailboxError:
        _logout(imap)
        raise
    return imap, mailbox


def _logout(imap: imaplib.IMAP4) -> None:
    # The run's work is done or failed already; a failed goodbye changes nothing.
    with contextlib.suppress(imaplib.IMAP4.error, OSError):
        imap.logout()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mailkeeper",
        description="Keep an IMAP mailbox clean of spam: return wanted email from the spam folder.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("plan", "judge the spam folder and show what apply would do; change nothing"),
        ("apply", "return the wanted emails of the spam folder to the inbox, marked"),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--config", metavar="FILE", required=True, help="configuration JSON")
    args = parser.parse_args()

    try:
        config = parse_config(Path(args.config).expanduser().read_text())
        if args.command == "apply" and not config.report_dir.is_dir():
            raise ConfigError(f"report_dir {config.report_dir} is not a folder")
        state = load_state()
        imap, mailbox = connect(config)
        try:
            judged = survey(mailbox, ModelDetector(config), config, state)
            if args.command == "plan":
                print(format_plan(judged))
                return
            result = apply_returns(mailbox, judged, config.mark)
        finally:
            _logout(imap)
        report = None
        if result.returned:
            when = datetime.now(UTC)
            report = write_report(
                config.report_dir, when, render_report(when, judged.spam, config.mark, result)
            )
        # Saved after the report: a run that fails before this repeats its steps next time.
        save_state(result.state)
        print(format_result(result, report))
        if result.failed or any(returned.mark_error for returned in result.returned):
            sys.exit(1)
    except (ConfigError, StateError, MailboxError, DetectorError, OSError) as error:
        sys.exit(f"mailkeeper: {error}")
