import argparse
import glob
import os
import sys
from pathlib import Path

from valkit.email_extractor.contacts import collect, resolve
from valkit.email_extractor.convert import html_to_markdown, unwrap_mailto
from valkit.email_extractor.log import ProcessedLog, message_key
from valkit.email_extractor.model import Message, Participant
from valkit.email_extractor.output import (
    Renderer,
    default_file_name,
    render_single,
    write_by_topic,
    write_single,
)
from valkit.email_extractor.parse import NotAnEmailError, load
from valkit.email_extractor.signature import strip_signatures
from valkit.email_extractor.split import split_thread


def read_thread(path: Path) -> tuple[list[Message], list[Participant]]:
    source = load(path)
    if source.html is not None:
        markdown = html_to_markdown(source.html)
    elif source.text is not None:
        markdown = unwrap_mailto(source.text)
    else:
        raise ValueError(f"{path} has no text or HTML body")
    messages = split_thread(markdown, source.top)
    resolve(messages)
    for message in messages:
        message.key = message_key(message)
    # Signatures and contacts use the whole thread: more messages give more evidence.
    strip_signatures(messages)
    return messages, collect(messages)


def extract(path: Path, strict: bool = False) -> str:
    """The whole thread as one Markdown document, without the processing log."""
    messages, participants = read_thread(path)
    return render_single(messages, participants, path.name, Renderer(messages, strict))


def expand_inputs(arguments: list[str]) -> list[Path]:
    """Expand wildcard patterns; an argument naming an existing file is taken literally.

    Exported emails often have "[" in their names, which would otherwise read as a pattern.
    """
    paths: list[Path] = []
    for argument in arguments:
        argument = os.path.expanduser(argument)
        if Path(argument).exists() or not any(char in argument for char in "*?["):
            matches = [argument]
        else:
            matches = sorted(glob.glob(argument, recursive=True))
            if not matches:
                raise ValueError(f"no files match {argument}")
        paths.extend(Path(match) for match in matches if Path(match) not in paths)
    return paths


def convert(
    input_path: Path, folder: Path, file_name: str | None, by_topic: bool, strict: bool
) -> list[Path]:
    """Write the input's new messages into `folder` and return the files written.

    `file_name` names a new single-file output; None means the default, `<input>.md`.
    """
    messages, participants = read_thread(input_path)
    renderer = Renderer(messages, strict)
    folder.mkdir(parents=True, exist_ok=True)
    log = ProcessedLog(folder)
    if by_topic:
        written = write_by_topic(messages, participants, input_path.name, folder, renderer, log)
    else:
        name = file_name or default_file_name(input_path, renderer)
        written = write_single(messages, participants, input_path.name, folder, name, renderer, log)
    # Saved only after the files are written, so a failed run never marks messages as done.
    log.save()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert .eml email threads into readable Markdown. Messages already "
        "converted into the output folder are skipped, and new ones are appended."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="input",
        help="one or more .eml files or quoted wildcard patterns, such as '~/mail/*.eml' "
        "('**' searches subfolders)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="the Markdown file to write; with several inputs or --by-topic, the folder to "
        "write into (default: the input's folder)",
    )
    parser.add_argument(
        "--by-topic",
        action="store_true",
        help="write one file per topic (<YYYYMMDD>-<YYYYMMDD>-<topic>.md) and merge the "
        "folder's metadata.json",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="strip personal details for sharing: keep first names only, replace emails, "
        "phones, links and dollar amounts, and write no metadata",
    )
    args = parser.parse_args()
    try:
        inputs = expand_inputs(args.inputs)
    except ValueError as error:
        sys.exit(f"email-extractor: {error}")
    output: Path | None = args.output
    # With one input and no --by-topic, -o names the Markdown file itself; otherwise a folder.
    output_is_file = output is not None and len(inputs) == 1 and not args.by_topic
    failures = 0
    for input_path in inputs:
        if output is None:
            folder, file_name = input_path.parent, None
        elif output_is_file:
            folder, file_name = output.parent, output.name
        else:
            folder, file_name = output, None
        try:
            written = convert(input_path, folder, file_name, args.by_topic, args.strict)
        except NotAnEmailError:
            print(f"email-extractor: skipped {input_path}: not an email", file=sys.stderr)
            continue
        except (OSError, ValueError) as error:
            # One bad file must not stop the rest of a batch.
            print(f"email-extractor: {input_path}: {error}", file=sys.stderr)
            failures += 1
            continue
        for path in written:
            print(path)
        if not written:
            print(f"email-extractor: {input_path}: no new messages", file=sys.stderr)
    if failures:
        sys.exit(f"email-extractor: {failures} of {len(inputs)} files failed")
