"""
Launch the Live AUTO-POSTER Mission Control Dashboard.
Open in your browser: http://localhost:5050
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

# Automatically re-execute within .venv if running from system python
venv_python = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
if venv_python.exists() and sys.executable.lower() != str(venv_python.resolve()).lower():
    import subprocess
    raise SystemExit(subprocess.call([str(venv_python), *sys.argv]))

from dotenv import load_dotenv

from shorts_bot.dashboard import run_dashboard

if __name__ == "__main__":
    load_dotenv()
    port = 5050
    print("=" * 60)
    print(f"🚀 AUTO-POSTER Live Dashboard is launching on http://localhost:{port}")
    print("Auto-refreshes every 10 seconds with live schedule & uploaded links.")
    print("=" * 60)
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass
    run_dashboard(port=port)
