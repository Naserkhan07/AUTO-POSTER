"""Start the links.txt automation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Automatically re-execute within .venv if running from system python
venv_python = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
if venv_python.exists() and sys.executable.lower() != str(venv_python.resolve()).lower():
    raise SystemExit(subprocess.call([str(venv_python), *sys.argv]))

if sys.version_info >= (3, 14):
    raise SystemExit(
        "Python 3.14 is not supported by the Chrome PO-token provider. "
        "Run: .\\.venv\\Scripts\\python.exe main.py"
    )

from dotenv import load_dotenv  # noqa: E402

from shorts_bot.file_queue import main as queue_main  # noqa: E402


def main() -> None:
    load_dotenv()
    queue_main()


if __name__ == "__main__":
    main()
