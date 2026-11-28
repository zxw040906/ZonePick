"""Own and clean only a temporary directory allocated by the current run."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile


@contextmanager
def temporary_run(project_root):
    """Create a private run root and remove it only while its identity matches."""
    root = Path(project_root).resolve()
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    if runs.resolve() != runs:
        raise ValueError("Temporary run parent cannot be a symbolic link")
    directory = Path(tempfile.mkdtemp(prefix=".temporary-", dir=runs))
    identity = directory.stat()
    try:
        yield directory
    finally:
        if directory.resolve() == directory and directory.is_dir():
            current = directory.stat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                shutil.rmtree(directory)
