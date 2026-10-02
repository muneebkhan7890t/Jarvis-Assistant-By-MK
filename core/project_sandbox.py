"""Generated programs run only in an explicitly configured Docker image.

No host credentials, network, Docker socket, or directories besides this project
are mounted. The image must be prepared by the user with its required packages.
"""
import os
from pathlib import Path, PureWindowsPath
import shlex
import shutil
import subprocess

def safe_path(root, relative):
    raw = str(relative)
    if Path(raw).is_absolute() or PureWindowsPath(raw).drive or ".." in raw.replace("\\", "/").split("/"):
        raise ValueError("Only project-relative paths are permitted")
    base = Path(root).resolve()
    dest = (base / raw).resolve()
    if dest == base or not dest.is_relative_to(base):
        raise ValueError("Path escapes project workspace")
    return dest

def command(run_command, project_dir, timeout):
    from memory.config_manager import load_api_keys
    image = load_api_keys().get("developer_sandbox_image", "")
    if not image or not shutil.which("docker"):
        raise RuntimeError("Execution not verified: configure developer_sandbox_image and Docker; generated code was not run on the host")
    parts = shlex.split(run_command)
    if len(parts) != 2 or parts[0] not in ("python", "python3") or not parts[1].endswith(".py"):
        raise ValueError("Only python <project-relative script.py> is supported by the sandbox")
    root = Path(project_dir).resolve()
    safe_path(root, parts[1])
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Project symlinks are not permitted in sandbox mounts")
    import uuid
    name = "jarvis-" + uuid.uuid4().hex
    argv = ["docker", "run", "--rm", "--pull=never", "--name", name,
        "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--memory=512m", "--cpus=1", "--pids-limit=64", "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m", "--mount", f"type=bind,src={root},dst=/workspace,readonly",
        "--workdir=/workspace", str(image), "python", "-B", parts[1]]
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=min(max(timeout, 1), 120))
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
