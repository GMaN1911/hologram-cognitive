"""What each editor needs to reach `hologram hook`: the hook entries to install, per harness.

The policy (what is injected, what is refused, what is reinforced) lives in the package and is
reached through `hologram hook <event>` (hologram/hook.py). These modules only say where each
harness's events are declared and how its entries are added and removed. An installer reads
them; nothing here touches a file.
"""

import shutil
import sys
from pathlib import Path


def executable(name: str = 'hologram') -> str:
    """The absolute path of this installation's console script, so the entry an installer
    writes works whatever PATH the harness's shell has (a venv's bin is rarely on it; a pipx
    install's ~/.local/bin usually is, but not always). Beside the running interpreter first,
    then PATH, else the bare name."""
    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return str(beside)
    return shutil.which(name) or name
