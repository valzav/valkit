import subprocess
from typing import Protocol


class Runner(Protocol):
    """Runs an external command and returns its standard output. Tests pass a fake."""

    def __call__(self, command: list[str], stdin: str | None = None) -> str: ...


class CommandError(RuntimeError):
    pass


def run(command: list[str], stdin: str | None = None) -> str:
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise CommandError(f"{command[0]} is not installed") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CommandError(f"{' '.join(command)} failed ({result.returncode}): {detail}")
    return result.stdout
