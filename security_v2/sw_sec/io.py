"""Small secret-file and subprocess boundaries. Never include child output in errors."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def private_write(path, content, *, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Refusing a symlink destination')
    fd, temporary = tempfile.mkstemp(prefix='.sw-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or (info.st_uid != os.geteuid() and os.geteuid() != 0):
            raise ValueError('Secret file must be private and service-owned (root verification is permitted)')
        return handle.read()


def audit(path, event, **fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Audit file must be mode 0600')
        handle.write(json.dumps({'event':event, **fields}, separators=(',', ':')) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def run_checked(argv, **kwargs):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, shell=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('External command failed or timed out; diagnostics withheld') from None
    if result.returncode:
        raise RuntimeError('External command failed; diagnostics withheld')
    return result
