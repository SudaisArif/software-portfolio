"""Small macOS Keychain/file primitives; no secret values enter argv or error text."""
import json
import hmac
import os
from pathlib import Path
import stat
import subprocess
import tempfile

SECURITY="/usr/bin/security"


class SecureSetupError(RuntimeError):pass


def security_command(arguments,*,stdin=None):
    try:
        return subprocess.run([SECURITY,*arguments],input=stdin,capture_output=True,timeout=30)
    except subprocess.TimeoutExpired:
        raise SecureSetupError("Keychain access is waiting for the owner; complete the macOS prompt, then retry") from None
    except (OSError,subprocess.SubprocessError):
        raise SecureSetupError("Keychain operation failed; no values or subprocess output were exposed") from None


def private_bytes(path,limit):
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        with os.fdopen(descriptor,"rb") as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
                raise SecureSetupError("Private handoff must be a regular file owned by this account and mode 600")
            raw=source.read(limit+1)
    except OSError:raise SecureSetupError("The fixed private handoff file is missing or unsafe") from None
    if len(raw)>limit:raise SecureSetupError("Private handoff exceeds its size limit")
    return raw,info


def remove_unchanged(path,original,expected_bytes):
    """Claim one inode atomically; never unlink a newly created original pathname."""
    path=Path(path)
    descriptor,name=tempfile.mkstemp(prefix=".handoff-recovery-",dir=path.parent)
    os.close(descriptor);claimed=Path(name);moved=False
    try:
        os.replace(path,claimed);moved=True
        content,current=private_bytes(claimed,len(expected_bytes))
        fields=("st_dev","st_ino","st_size","st_mtime_ns")
        if tuple(getattr(current,key) for key in fields)!=tuple(getattr(original,key) for key in fields) or not hmac.compare_digest(content,expected_bytes):
            raise SecureSetupError("Changed handoff")
        claimed.unlink()
        return not os.path.lexists(path)
    except (OSError,SecureSetupError):
        if moved:
            # Restore without overwriting a fresh handoff. If its name is now in
            # use, retain the claimed replacement as a private recovery sibling.
            try:os.link(claimed,path,follow_symlinks=False)
            except OSError:pass
            else:claimed.unlink()
        else:claimed.unlink()
        raise SecureSetupError("Handoff changed during storage; encrypted entry verified and unverified data retained at the original path or a .handoff-recovery sibling") from None


def write_private_json(path,value):
    path=Path(path)
    if path.is_symlink():raise SecureSetupError("Private receipt destination is unsafe")
    if path.exists():
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise SecureSetupError("Existing receipt must be a private file owned by this account")
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",prefix=".connection-",dir=path.parent,delete=False) as output:
            temporary=Path(output.name);os.fchmod(output.fileno(),0o600)
            json.dump(value,output,ensure_ascii=False,allow_nan=False,indent=2);output.write("\n");output.flush();os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
