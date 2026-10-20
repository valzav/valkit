import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write through a temporary file in the same folder, then move it into place.

    Output folders often hold files from elsewhere, such as an unpacked mail export. `os.replace`
    swaps the folder entry itself, so a symlink planted at `path` is replaced, never followed.
    """
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
