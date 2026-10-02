"""Build an allowlisted source archive; never copy a working directory wholesale."""
import argparse
from pathlib import Path
import re
import zipfile

SOURCE_DIRS = {"actions", "core", "memory", "dashboard", "plugins", "tests", "scripts"}
EXCLUDED = {".venv", "venv", "__pycache__", ".git", "logs", "uploads", "downloads", "node_modules", "browser_profiles", "certs"}
ROOT_FILES = {"main.py", "ui.py", "launch.py", "setup.py", "setup_windows.ps1", ".gitignore", "LICENSE", "Start Jarvis.vbs", "Setup Windows.cmd", "Disable Autostart.cmd"}

def included(path):
    if any(part in EXCLUDED or part.startswith(".venv") for part in path.parts):
        return False
    if len(path.parts) == 1:
        return path.name in ROOT_FILES or path.suffix == ".md" or path.name.startswith("requirements") and path.suffix == ".txt"
    if path.as_posix() in ("config/__init__.py", "config/api_keys.example.json", "config/jarvis.ico", "core/prompt.txt", "dashboard/static/app.html", "dashboard/static/remote.html", "dashboard/static/remote-audio.js", "dashboard/static/remote-companion.js", "dashboard/static/remote-sw.js", "dashboard/static/login.html", "dashboard/static/crypto-js.min.js"):
        return True
    if path.parts[0] == "docs" and path.suffix == ".md":
        return True
    return path.parts[0] in SOURCE_DIRS and path.suffix == ".py"

def build(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    files = [p for p in root.rglob("*") if p.is_file() and included(p.relative_to(root))]
    for p in files:
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError("Release input links must not escape the repository")
        if p.suffix in (".py", ".json", ".md", ".txt", ".html", ".ps1"):
            text = p.read_text(encoding="utf-8-sig")
            if re.search(r"AIza[0-9A-Za-z_-]{35}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
                raise ValueError("Potential credential/private key in release input: " + str(p.relative_to(root)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, "MARK-LIV/" + path.relative_to(root).as_posix())
    return destination, len(files)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist/MARK-LIV-source.zip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path, count = build(root, root / args.output)
    print(f"Built {path.name}: {count} files, {path.stat().st_size} bytes")
