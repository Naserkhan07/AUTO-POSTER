"""
Vercel Serverless Entrypoint & Live Mission Control Dashboard.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from shorts_bot.config import Settings
from shorts_bot.dashboard import get_dashboard_data, render_html_dashboard


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            settings = Settings.from_env(env_file=None)
        except Exception:
            settings = Settings.from_env()

        data = get_dashboard_data(settings.database_path, settings)

        if self.path == "/health" or self.path == "/api/health" or self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html_content = render_html_dashboard(data)
        self.wfile.write(html_content.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        pass
