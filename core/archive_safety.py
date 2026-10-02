"""Bounded ZIP/TAR extraction; no links, traversal or overwrites."""
from pathlib import Path
import stat
import tarfile
import zipfile
from core.project_sandbox import safe_path

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 5000

def extract(source, destination):
    source, root = Path(source), Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    is_zip = zipfile.is_zipfile(source)
    archive = zipfile.ZipFile(source) if is_zip else tarfile.open(source)
    written = []
    with archive:
        entries = archive.infolist() if is_zip else archive.getmembers()
        if len(entries) > MAX_FILES:
            raise ValueError("Archive file limit exceeded")
        total = 0
        plan = []
        for entry in entries:
            name = entry.filename if is_zip else entry.name
            if name.rstrip("/") in ("", "."):
                continue
            path = safe_path(root, name.rstrip("/"))
            directory = entry.is_dir() if is_zip else entry.isdir()
            size = entry.file_size if is_zip else entry.size
            if is_zip and stat.S_ISLNK(entry.external_attr >> 16) or not is_zip and not (entry.isfile() or entry.isdir()):
                raise ValueError("Archive links and special files are forbidden")
            total += size
            if total > MAX_BYTES:
                raise ValueError("Archive expansion limit exceeded")
            if path.exists() and not (directory and path.is_dir()):
                raise ValueError("Archive would overwrite an existing path")
            plan.append((entry, path, directory))
        consumed = 0
        for entry, path, directory in plan:
            if directory:
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.open(entry) if is_zip else archive.extractfile(entry)
            with stream, path.open("xb") as output:
                while chunk := stream.read(65536):
                    consumed += len(chunk)
                    if consumed > MAX_BYTES:
                        raise ValueError("Archive expansion limit exceeded; partial files may remain")
                    output.write(chunk)
            written.append(path)
    return written
