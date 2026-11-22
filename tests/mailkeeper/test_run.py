from valkit.mailkeeper.config import Config
from valkit.mailkeeper.run import INVALID, TRUSTED, Action, Survey, apply_returns, survey
from valkit.mailkeeper.state import State

from .conftest import AUTHSERV, FakeDetector, FakeMailbox, make_email

VERDICTS: dict[str, str | None] = {
    "Dinner on Friday?": "personal",
    "Your invoice": "transactional",
    "Big sale": "marketing",
    "Quick question": "cold_outreach",
    "Sign this document": "scam",
}


def fill(mailbox: FakeMailbox) -> dict[str, int]:
    """One spam folder with each kind of email; returns UIDs by subject."""
    emails = {
        "Dinner on Friday?": make_email("Sam <sam@friend.test>", "Dinner on Friday?"),
        "Your invoice": make_email("billing@shop.test", "Your invoice"),
        "Big sale": make_email("deals@shop.test", "Big sale"),
        "Quick question": make_email("rep@leads.test", "Quick question"),
        "Club news": make_email("info@club.example", "Club news"),
        "Re: our call": make_email("partner@fund.test", "Re: our call"),
        # Claims an own domain but fails authentication: the model judges it.
        "Sign this document": make_email(
            "Owner <owner@example.test>", "Sign this document", auth=f"{AUTHSERV}; spf=none"
        ),
    }
    mailbox.sent_to.add("partner@fund.test")
    return {subject: mailbox.add("Junk", data) for subject, data in emails.items()}


def by_subject(result: Survey) -> dict[str, tuple[str, Action]]:
    return {item.header.subject: (item.verdict, item.action) for item in result.items}


def test_survey_returns_wanted_and_trusted_and_changes_nothing(
    mailbox: FakeMailbox, config: Config
) -> None:
    fill(mailbox)
    detector = FakeDetector(VERDICTS)

    result = survey(mailbox, detector, config, State())

    assert by_subject(result) == {
        "Dinner on Friday?": ("personal", Action.RETURN),
        "Your invoice": ("transactional", Action.RETURN),
        "Big sale": ("marketing", Action.STAY),
        "Quick question": ("cold_outreach", Action.STAY),
        "Club news": (TRUSTED, Action.RETURN),
        "Re: our call": (TRUSTED, Action.RETURN),
        "Sign this document": ("scam", Action.STAY),
    }
    assert mailbox.writes == []
    # Trusted senders never reach the model.
    assert "Club news" not in detector.calls
    assert "Re: our call" not in detector.calls
    # An unauthenticated sender is not looked up in the sent folder at all.
    assert "owner@example.test" not in mailbox.searched


def test_apply_moves_marks_and_records(mailbox: FakeMailbox, config: Config) -> None:
    uids = fill(mailbox)
    judged = survey(mailbox, FakeDetector(VERDICTS), config, State())

    result = apply_returns(mailbox, judged, "unspam")

    returned = {item.header.subject for item in result.returned}
    assert returned == {"Dinner on Friday?", "Your invoice", "Club news", "Re: our call"}
    assert result.failed == []
    assert sorted(mailbox.folders["Junk"]) == sorted(
        uids[s] for s in ("Big sale", "Quick question", "Sign this document")
    )
    moves = [write for write in mailbox.writes if write.startswith("move")]
    marks = [write for write in mailbox.writes if write.startswith("mark")]
    assert len(moves) == len(marks) == 4
    assert all(write.endswith(" unspam") for write in marks)
    assert {item.header.message_id for item in result.returned} == result.state.moved


def test_each_email_is_judged_once(mailbox: FakeMailbox, config: Config) -> None:
    fill(mailbox)
    detector = FakeDetector(VERDICTS)
    first = survey(mailbox, detector, config, State())
    calls = len(detector.calls)

    second = survey(mailbox, detector, config, first.state)

    assert len(detector.calls) == calls
    assert by_subject(second) == by_subject(first)


def test_a_moved_email_is_never_moved_again(mailbox: FakeMailbox, config: Config) -> None:
    data = make_email("Sam <sam@friend.test>", "Dinner on Friday?")
    mailbox.add("Junk", data)
    detector = FakeDetector(VERDICTS)
    first = apply_returns(mailbox, survey(mailbox, detector, config, State()), "unspam")
    # The owner puts it back into the spam folder by hand.
    mailbox.add("Junk", data)
    mailbox.writes.clear()

    again = survey(mailbox, detector, config, first.state)
    result = apply_returns(mailbox, again, "unspam")

    assert [(item.action, item.note) for item in again.items] == [(Action.STAY, "moved before")]
    assert result.returned == []
    assert mailbox.writes == []


def test_an_invalid_reply_records_nothing_and_is_judged_again(
    mailbox: FakeMailbox, config: Config
) -> None:
    mailbox.add("Junk", make_email("someone@other.test", "Unclear"))
    detector = FakeDetector({"Unclear": None})

    first = survey(mailbox, detector, config, State())
    second = survey(mailbox, detector, config, first.state)

    assert [(item.verdict, item.action) for item in first.items] == [(INVALID, Action.STAY)]
    assert first.state.folders["Junk"].judged == {}
    assert detector.calls == ["Unclear", "Unclear"]
    assert second.items[0].verdict == INVALID


def test_a_new_uidvalidity_forgets_the_verdicts(mailbox: FakeMailbox, config: Config) -> None:
    mailbox.add("Junk", make_email("deals@shop.test", "Big sale"))
    detector = FakeDetector(VERDICTS)
    first = survey(mailbox, detector, config, State())

    mailbox.uidvalidity += 1
    second = survey(mailbox, detector, config, first.state)

    assert detector.calls == ["Big sale", "Big sale"]
    assert second.state.folders["Junk"].uidvalidity == mailbox.uidvalidity


def test_verdicts_of_emails_gone_from_the_folder_are_dropped(
    mailbox: FakeMailbox, config: Config
) -> None:
    uid = mailbox.add("Junk", make_email("deals@shop.test", "Big sale"))
    first = survey(mailbox, FakeDetector(VERDICTS), config, State())
    del mailbox.folders["Junk"][uid]

    second = survey(mailbox, FakeDetector(VERDICTS), config, first.state)

    assert second.state.folders["Junk"].judged == {}


def test_an_email_without_message_id_stays(mailbox: FakeMailbox, config: Config) -> None:
    mailbox.add("Junk", make_email("Sam <sam@friend.test>", "Dinner on Friday?", message_id=""))

    result = survey(mailbox, FakeDetector(VERDICTS), config, State())

    assert [(item.action, item.note) for item in result.items] == [(Action.STAY, "no Message-ID")]


def test_a_failed_move_is_reported_and_not_recorded(mailbox: FakeMailbox, config: Config) -> None:
    uid = mailbox.add("Junk", make_email("Sam <sam@friend.test>", "Dinner on Friday?"))
    mailbox.fail_moves.add(uid)

    result = apply_returns(mailbox, survey(mailbox, FakeDetector(VERDICTS), config, State()), "m")

    assert [failed.header.uid for failed in result.failed] == [uid]
    assert result.returned == []
    assert result.state.moved == set()


def test_a_failed_mark_keeps_the_move(mailbox: FakeMailbox, config: Config) -> None:
    mailbox.add("Junk", make_email("Sam <sam@friend.test>", "Dinner on Friday?"))
    mailbox.fail_marks = True

    result = apply_returns(mailbox, survey(mailbox, FakeDetector(VERDICTS), config, State()), "m")

    assert [returned.mark_error for returned in result.returned] == ["mark refused"]
    assert len(result.state.moved) == 1
