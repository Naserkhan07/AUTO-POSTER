"""
Vercel Serverless Entrypoint & Status Dashboard.
Serves a status dashboard showing active scheduler slots and configuration.
"""

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health" or self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "online",
                "service": "Auto-Poster Automation Dashboard",
                "timestamp": datetime.now().isoformat(),
                "min_daily_target_per_platform": 10,
                "platforms": ["YouTube Shorts", "Instagram Reels", "Facebook Reels"],
            }
            self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AUTO-POSTER Cloud Dashboard</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }
    .card { background: #1e293b; border-radius: 12px; padding: 2rem; max-width: 800px; margin: 0 auto; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
    h1 { color: #38bdf8; margin-top: 0; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-weight: bold; background: #22c55e; color: #000; margin-bottom: 1rem; }
    .info { line-height: 1.6; color: #cbd5e1; }
    ul { list-style: square; padding-left: 1.5rem; }
    .note { background: #334155; padding: 1rem; border-left: 4px solid #38bdf8; border-radius: 4px; margin-top: 1.5rem; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">SYSTEM READY</div>
    <h1>AUTO-POSTER Multi-Platform Engine</h1>
    <p class="info">24/7 Automated video clipping, GTA V/Minecraft/Subway Surfers split-screen generator, Whisper subtitles, and multi-platform scheduler.</p>
    
    <h3>Target Daily Volume:</h3>
    <ul>
      <li><strong>YouTube Shorts:</strong> Minimum 10 uploads/day</li>
      <li><strong>Instagram Reels:</strong> Minimum 10 uploads/day</li>
      <li><strong>Facebook Reels:</strong> Minimum 10 uploads/day</li>
    </ul>

    <h3>Scheduling Windows:</h3>
    <ul>
      <li><strong>Morning:</strong> 6:30 AM - 10:00 AM</li>
      <li><strong>Afternoon:</strong> 11:30 AM - 3:00 PM</li>
      <li><strong>Evening / Night Peak:</strong> 6:00 PM - 11:00 PM</li>
      <li><strong>Preparation:</strong> Auto-rendered 30 minutes in advance</li>
    </ul>

    <div class="note">
      <strong>Vercel vs Persistent Worker Note:</strong>
      Vercel operates as a serverless web host (ideal for dashboards and webhooks). Heavy FFmpeg rendering and 24/7 background worker execution runs through Docker / Coolify / local daemon.
    </div>
  </div>
</body>
</html>
"""
        self.wfile.write(html.encode("utf-8"))

