"""Verify local downloads against extracted bytes, or stage a ZIP extraction."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
from itertools import islice
import json
from pathlib import Path, PureWindowsPath
import shutil
import stat
import tarfile
import tempfile
import zipfile


def safe_member(root, name):
    relative = Path(name)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or "\\" in name or PureWindowsPath(name).drive:
        raise ValueError(f"Unsafe archive path: {name}")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Symbolic link in archive destination: {path}")
    return path


def compare_bytes(source, target, size):
    if not target.is_file() or target.stat().st_size != size:
        raise ValueError(f"Missing file or size mismatch: {target}")
    with target.open("rb") as output:
        while chunk := source.read(1024 * 1024):
            if chunk != output.read(len(chunk)):
                raise ValueError(f"Content mismatch: {target}")


def stream_digest(stream, digest):
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


class HashingReader:
    """Hash compressed bytes while gzip consumes its forward-only stream."""

    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.md5()

    def read(self, count=-1):
        data = self.stream.read(count)
        self.digest.update(data)
        return data


def verify_tar(archive, root):
    """Index TAR member digests sequentially, then compare the extracted files."""
    files = {}
    directories = set()
    with archive.open("rb", buffering=1024 * 1024) as raw:
        reader = HashingReader(raw)
        with gzip.GzipFile(fileobj=reader, mode="rb") as stream:
            with tarfile.open(fileobj=stream, mode="r|", bufsize=1024 * 1024) as container:
                for member in container:
                    if member.name in (".", "./") and member.isdir():
                        continue
                    if member.isdir():
                        directories.add(member.name)
                        continue
                    if not member.isfile() or member.name in files:
                        raise ValueError(f"Unexpected TAR member: {member.name}")
                    with container.extractfile(member) as source:
                        files[member.name] = (member.size, stream_digest(source, hashlib.sha256()))
            while stream.read(1024 * 1024):
                pass  # consume gzip trailer and validate CRC
        checksum = reader.digest.hexdigest()

    targets = {}
    for name in directories:
        target = safe_member(root, name)
        if not target.is_dir():
            raise ValueError(f"Missing directory: {target}")

    def check_file(item):
        target, (size, expected) = item
        if not target.is_file() or target.stat().st_size != size:
            raise ValueError(f"Missing file or size mismatch: {target}")
        with target.open("rb") as output:
            if stream_digest(output, hashlib.sha256()) != expected:
                raise ValueError(f"Content mismatch: {target}")

    for name, entry in files.items():
        target = safe_member(root, name)
        if target in targets:
            raise ValueError(f"Duplicate TAR path: {target}")
        targets[target] = entry
    # A bounded dispatch keeps disk requests in inventory order without queuing every file.
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = iter(targets.items())
        while batch := list(islice(items, 256)):
            for _ in pool.map(check_file, batch):
                pass
    return files, checksum


def verify(archive, root, expected_md5=None, *, extract=False):
    raw = Path("data/raw").absolute()
    archive, root = Path(archive).absolute(), Path(root).absolute()
    for path in (archive, root):
        if not path.is_relative_to(raw) or safe_member(raw, str(path.relative_to(raw))) != path:
            raise ValueError(f"Expected project-owned data path: {path}")
    if raw.resolve() != raw or not archive.is_file() or archive.stat().st_nlink != 1:
        raise ValueError(f"Expected a project-owned regular archive: {archive}")
    original = archive.stat()
    files = set()
    if zipfile.is_zipfile(archive):
        with archive.open("rb") as stream:
            checksum = stream_digest(stream, hashlib.md5())
        if expected_md5 and checksum != expected_md5:
            raise ValueError(f"MD5 mismatch: {archive}")
        with zipfile.ZipFile(archive) as container:
            members = container.infolist()
            paths = {}
            for member in members:
                target = safe_member(root, member.filename)
                kind = stat.S_IFMT(member.external_attr >> 16)
                if kind not in (0, stat.S_IFDIR if member.is_dir() else stat.S_IFREG):
                    raise ValueError(f"Unexpected ZIP member type: {member.filename}")
                if target in paths:
                    raise ValueError(f"Duplicate ZIP path: {target}")
                paths[target] = member
                if not member.is_dir():
                    files.add(target)
            if any(files.intersection(p.parents) for p in paths):
                raise ValueError("ZIP file listed as parent directory")
            if extract and any((root / p.relative_to(root).parts[0]).exists()
                               for p in paths):
                raise FileExistsError("ZIP extraction would overwrite existing data")
            if bad := container.testzip():
                raise ValueError(f"ZIP CRC mismatch: {bad}")
            stage = Path(tempfile.mkdtemp(prefix="archive-", dir="data")) if extract else root
            for target, member in paths.items():
                item = stage / target.relative_to(root)
                if member.is_dir():
                    if extract:
                        item.mkdir(parents=True, exist_ok=True)
                    elif not item.is_dir():
                        raise ValueError(f"Missing directory: {item}")
                    continue
                if extract:
                    item.parent.mkdir(parents=True, exist_ok=True)
                    with container.open(member) as source, item.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                with container.open(member) as source:
                    compare_bytes(source, item, member.file_size)
            if extract:
                if {p.relative_to(stage) for p in stage.rglob("*") if p.is_file()} != {
                    p.relative_to(root) for p in files
                }:
                    raise ValueError("Extracted ZIP inventory differs from central directory")
                top = list(stage.iterdir())
                if len(top) != 1 or not top[0].is_dir():
                    raise ValueError("Expected a single top-level dataset directory")
                destination = root / top[0].name
                destination.mkdir()  # exclusive, even if another run published concurrently
                top[0].rename(destination)
                stage.rmdir()
    else:
        if extract:
            raise ValueError("Staged extraction requires ZIP")
        files, checksum = verify_tar(archive, root)
        if expected_md5 and checksum != expected_md5:
            raise ValueError(f"MD5 mismatch: {archive}")
    now = archive.stat()
    if not files or (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns) != (
        original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns
    ):
        raise ValueError("Empty or changed archive")
    return {"archive": str(archive.relative_to(Path.cwd())), "root": str(root.relative_to(Path.cwd())),
            "files": len(files), "bytes": original.st_size, "allocated_bytes": original.st_blocks * 512,
            "md5": checksum, "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("root")
    parser.add_argument("--md5")
    parser.add_argument("--extract", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.archive, args.root, args.md5, extract=args.extract)))
