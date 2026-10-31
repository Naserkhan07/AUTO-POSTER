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

from shorts_bot.config import Settings
from shorts_bot.dashboard import get_dashboard_data, render_html_dashboard, render_markdown_dashboard, run_dashboard

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    if "--summary" in sys.argv:
        try:
            settings = Settings.from_env()
        except Exception:
            settings = Settings.from_env(env_file=None)
        data = get_dashboard_data(settings.database_path, settings)
        print(render_markdown_dashboard(data))
        sys.exit(0)

    if "--html" in sys.argv:
        idx = sys.argv.index("--html")
        out_path = Path(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else Path("dashboard.html")
        try:
            settings = Settings.from_env()
        except Exception:
            settings = Settings.from_env(env_file=None)
        data = get_dashboard_data(settings.database_path, settings)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_html_dashboard(data), encoding="utf-8")
        print(f"Exported HTML dashboard to {out_path}")
        sys.exit(0)

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

