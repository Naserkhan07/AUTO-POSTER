"""
Live Web Dashboard for AUTO-POSTER.
Displays real-time schedule, next upload countdown, uploaded videos history,
and monitored creator channels.
"""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import Settings
from .scheduler import ContentScheduler


def format_12h_time(iso_or_dt: str) -> str:
    """Converts ISO or standard timestamp string to 12-hour AM/PM format."""
    if not iso_or_dt:
        return ""
    try:
        clean = iso_or_dt.replace("Z", "+00:00").split(".")[0]
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%b %d, %I:%M %p")
    except Exception:
        return iso_or_dt


def get_dashboard_data(db_path: Path, settings: Settings) -> dict[str, Any]:
    scheduler = ContentScheduler()
    now = datetime.now()

    # Get slots for today
    yt_slots = scheduler.get_slots_for_day("YouTube", now)
    ig_slots = scheduler.get_slots_for_day("Instagram", now)
    fb_slots = scheduler.get_slots_for_day("Facebook", now)

    yt_next = scheduler.get_next_slot("YouTube", now)
    ig_next = scheduler.get_next_slot("Instagram", now)
    fb_next = scheduler.get_next_slot("Facebook", now)

    yt_prep_due, yt_prep_slot = scheduler.is_prep_due("YouTube", now)
    ig_prep_due, ig_prep_slot = scheduler.is_prep_due("Instagram", now)
    fb_prep_due, fb_prep_slot = scheduler.is_prep_due("Facebook", now)

    # Read uploaded clips from database
    uploaded_clips: list[dict[str, Any]] = []
    monitored_seen: list[dict[str, Any]] = []

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT c.job_id, c.clip_index, c.title, c.youtube_video_id,
                           c.instagram_url, c.facebook_url, j.source_title, j.created_at,
                           j.status
                    FROM job_clips c
                    JOIN jobs j ON j.id = c.job_id
                    WHERE (c.youtube_video_id IS NOT NULL AND c.youtube_video_id != '')
                       OR (c.instagram_url IS NOT NULL AND c.instagram_url != '')
                       OR (c.facebook_url IS NOT NULL AND c.facebook_url != '')
                    ORDER BY j.created_at DESC
                    LIMIT 25
                    """
                ).fetchall()
                for r in rows:
                    created_at_raw = str(r["created_at"])
                    uploaded_clips.append(
                        {
                            "job_id": r["job_id"],
                            "clip_index": r["clip_index"],
                            "title": r["title"] or r["source_title"] or "Short Clip",
                            "youtube_video_id": r["youtube_video_id"],
                            "instagram_url": r["instagram_url"],
                            "facebook_url": r["facebook_url"],
                            "created_at": created_at_raw,
                            "created_at_12h": format_12h_time(created_at_raw),
                        }
                    )

                # Recent autopilot seen videos
                seen_rows = conn.execute(
                    """
                    SELECT video_id, channel_id, title, published_at, seen_at, queued
                    FROM autopilot_seen
                    ORDER BY seen_at DESC
                    LIMIT 15
                    """
                ).fetchall()
                for sr in seen_rows:
                    monitored_seen.append(
                        {
                            "video_id": sr["video_id"],
                            "channel_id": sr["channel_id"],
                            "title": sr["title"],
                            "published_at": sr["published_at"],
                            "seen_at": sr["seen_at"],
                            "seen_at_12h": format_12h_time(str(sr["seen_at"])),
                            "queued": bool(sr["queued"]),
                        }
                    )
        except Exception:
            pass

    # Read pending links in links.txt
    pending_links: list[str] = []
    if settings.links_file.exists():
        try:
            lines = settings.links_file.read_text(encoding="utf-8").splitlines()
            for line in lines:
                candidate = line.strip()
                if candidate and not candidate.startswith("#"):
                    pending_links.append(candidate)
        except Exception:
            pass

    return {
        "timestamp": now.strftime("%I:%M:%S %p"),
        "date_12h": now.strftime("%b %d, %Y - %I:%M %p"),
        "today_name": now.strftime("%A"),
        "channels": list(settings.autopilot_channels),
        "pending_links": pending_links,
        "uploaded_clips": uploaded_clips,
        "monitored_seen": monitored_seen,
        "schedules": {
            "YouTube": {
                "next_slot": yt_next.target_time.strftime("%I:%M %p"),
                "prep_due": yt_prep_due,
                "slots_today": [s.target_time.strftime("%I:%M %p") for s in yt_slots],
            },
            "Instagram": {
                "next_slot": ig_next.target_time.strftime("%I:%M %p"),
                "prep_due": ig_prep_due,
                "slots_today": [s.target_time.strftime("%I:%M %p") for s in ig_slots],
            },
            "Facebook": {
                "next_slot": fb_next.target_time.strftime("%I:%M %p"),
                "prep_due": fb_prep_due,
                "slots_today": [s.target_time.strftime("%I:%M %p") for s in fb_slots],
            },
        },
    }


def render_markdown_dashboard(data: dict[str, Any]) -> str:
    """Renders a rich markdown dashboard for GitHub Actions Job Summaries ($GITHUB_STEP_SUMMARY)."""
    yt = data["schedules"]["YouTube"]
    ig = data["schedules"]["Instagram"]
    fb = data["schedules"]["Facebook"]

    md: list[str] = []
    md.append("# 🚀 AUTO-POSTER Live Mission Control")
    md.append(f"**Live Server Time (12-Hour Clock):** `{data['date_12h']}` | **Status:** ✅ `Running 24/7`\n")

    md.append("### 📅 Today's 12-Hour Upload Schedule (Min 10 Uploads Target)")
    md.append("| Platform | Next Upload Window | 30m Auto-Prep Status | Today's Slots (12-Hour AM/PM) |")
    md.append("| :--- | :--- | :--- | :--- |")
    md.append(f"| **YouTube Shorts** | **{yt['next_slot']}** | {'⚡ Auto-Prep Active' if yt['prep_due'] else 'Standby'} | {', '.join(yt['slots_today'])} |")
    md.append(f"| **Instagram Reels** | **{ig['next_slot']}** | {'⚡ Auto-Prep Active' if ig['prep_due'] else 'Standby'} | {', '.join(ig['slots_today'])} |")
    md.append(f"| **Facebook Reels** | **{fb['next_slot']}** | {'⚡ Auto-Prep Active' if fb['prep_due'] else 'Standby'} | {', '.join(fb['slots_today'])} |")
    md.append("")

    md.append("### 🎬 Recently Published Videos & Live Links")
    if data["uploaded_clips"]:
        md.append("| Video Title | Published (12-Hour) | Direct Platform Links |")
        md.append("| :--- | :--- | :--- |")
        for c in data["uploaded_clips"][:10]:
            links: list[str] = []
            if c.get("youtube_video_id"):
                links.append(f"[🔴 YouTube Short](https://www.youtube.com/shorts/{c['youtube_video_id']})")
            if c.get("instagram_url"):
                links.append(f"[🟣 Instagram Reel]({c['instagram_url']})")
            if c.get("facebook_url"):
                links.append(f"[🔵 Facebook Reel]({c['facebook_url']})")
            link_str = " • ".join(links) or "Processing"
            time_str = c.get("created_at_12h") or c["created_at"]
            md.append(f"| **{c['title']}** | {time_str} | {link_str} |")
    else:
        md.append("> *No uploaded clips in database yet. Scheduled runs will populate direct live links here automatically.*")
    md.append("")

    md.append(f"### 📡 Monitored Creator Channels ({len(data['channels'])})")
    channel_list = [f"`{ch.get('name', 'Channel')}`" for ch in data["channels"]]
    md.append(" • ".join(channel_list))
    md.append("")

    if data["pending_links"]:
        md.append(f"### 📋 Staging Queue (`links.txt` - {len(data['pending_links'])} Videos Ready)")
        for pl in data["pending_links"][:5]:
            md.append(f"- {pl}")
    md.append("")

    return "\n".join(md)


def render_html_dashboard(data: dict[str, Any]) -> str:
    yt = data["schedules"]["YouTube"]
    ig = data["schedules"]["Instagram"]
    fb = data["schedules"]["Facebook"]

    clips_html = ""
    if data["uploaded_clips"]:
        for c in data["uploaded_clips"]:
            yt_link = (
                f'<a href="https://www.youtube.com/shorts/{c["youtube_video_id"]}" target="_blank" class="badge red">YouTube Short</a>'
                if c.get("youtube_video_id")
                else ""
            )
            ig_link = (
                f'<a href="{c["instagram_url"]}" target="_blank" class="badge pink">Instagram Reel</a>'
                if c.get("instagram_url")
                else ""
            )
            fb_link = (
                f'<a href="{c["facebook_url"]}" target="_blank" class="badge blue">Facebook Reel</a>'
                if c.get("facebook_url")
                else ""
            )
            clips_html += f"""
            <tr>
              <td><strong>{html.escape(c["title"])}</strong><div class="meta">{c["created_at"][:19].replace('T', ' ')} (Job: {c["job_id"]})</div></td>
              <td>{yt_link} {ig_link} {fb_link}</td>
            </tr>
            """
    else:
        clips_html = '<tr><td colspan="2" style="text-align:center; color:#94a3b8; padding:2rem;">No uploaded clips recorded in local database yet. Next scheduled run will populate live clips here.</td></tr>'

    channels_html = ""
    for ch in data["channels"]:
        channels_html += f'<span class="channel-tag">📺 {html.escape(ch.get("name") or "Channel")}</span> '

    pending_html = ""
    if data["pending_links"]:
        for p in data["pending_links"]:
            pending_html += f'<li><a href="{p}" target="_blank">{p}</a></li>'
    else:
        pending_html = '<li style="color:#64748b;">Queue is clear. Autopilot is scanning creator channels every 15m.</li>'

    yt_prep_badge = '<span class="prep-badge">⚡ 30m Auto-Prep Active</span>' if yt["prep_due"] else '<span class="status-badge">Standby</span>'
    ig_prep_badge = '<span class="prep-badge">⚡ 30m Auto-Prep Active</span>' if ig["prep_due"] else '<span class="status-badge">Standby</span>'
    fb_prep_badge = '<span class="prep-badge">⚡ 30m Auto-Prep Active</span>' if fb["prep_due"] else '<span class="status-badge">Standby</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="10">
  <title>AUTO-POSTER Live Mission Control</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #151c2e;
      --border: #232f48;
      --text: #f1f5f9;
      --subtext: #94a3b8;
      --primary: #38bdf8;
      --green: #22c55e;
      --red: #ef4444;
      --pink: #ec4899;
      --blue: #3b82f6;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 1.5rem;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex; justify-content: space-between; align-items: center;
      background: var(--card-bg); padding: 1.25rem 2rem; border-radius: 12px;
      border: 1px solid var(--border); margin-bottom: 1.5rem;
    }}
    h1 {{ font-size: 1.5rem; color: var(--primary); display: flex; align-items: center; gap: 0.5rem; }}
    .live-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--green); box-shadow: 0 0 10px var(--green); animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} 100% {{ opacity: 1; }} }}
    .time-badge {{ font-size: 0.85rem; color: var(--subtext); }}
    
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.25rem; margin-bottom: 1.5rem; }}
    .card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); padding: 1.25rem; }}
    .card h2 {{ font-size: 1.1rem; margin-bottom: 0.75rem; color: #e2e8f0; display: flex; justify-content: space-between; }}
    
    .slot-row {{ display: flex; justify-content: space-between; margin: 0.5rem 0; font-size: 0.95rem; }}
    .slot-highlight {{ font-size: 1.4rem; font-weight: bold; color: var(--primary); margin: 0.5rem 0; }}
    .slots-list {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; }}
    .slot-pill {{ background: #1e293b; padding: 0.2rem 0.5rem; border-radius: 6px; font-size: 0.75rem; color: #cbd5e1; border: 1px solid #334155; }}
    
    .badge {{ display: inline-block; padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.75rem; font-weight: 600; text-decoration: none; color: #fff; margin-right: 0.3rem; }}
    .badge.red {{ background: #dc2626; }}
    .badge.pink {{ background: #db2777; }}
    .badge.blue {{ background: #2563eb; }}
    .prep-badge {{ background: #f59e0b; color: #000; font-size: 0.75rem; font-weight: bold; padding: 0.2rem 0.5rem; border-radius: 4px; }}
    .status-badge {{ background: #334155; font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; color: #94a3b8; }}

    table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
    th, td {{ text-align: left; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--subtext); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    .meta {{ font-size: 0.75rem; color: var(--subtext); margin-top: 0.2rem; }}
    
    .channel-tag {{ display: inline-block; background: #1e293b; padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem; margin: 0.2rem; border: 1px solid var(--border); }}
    ul.queue {{ padding-left: 1.25rem; font-size: 0.85rem; line-height: 1.6; }}
    ul.queue a {{ color: var(--primary); text-decoration: none; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1><span class="live-dot"></span> AUTO-POSTER Live Dashboard</h1>
        <div class="time-badge">Day: {data["today_name"]} | Live Server Clock: {data["timestamp"]} | Auto-Refreshes every 10s</div>
      </div>
      <div>
        <span class="badge blue">Min 10 Uploads/Day Active</span>
        <span class="badge" style="background:#059669;">GTA V / MC / Subway Surfers Active</span>
      </div>
    </header>

    <div class="grid">
      <!-- YouTube Card -->
      <div class="card">
        <h2><span>📺 YouTube Shorts</span> {yt_prep_badge}</h2>
        <div class="slot-row"><span>Next Target Slot:</span></div>
        <div class="slot-highlight">{yt["next_slot"]}</div>
        <div class="slot-row" style="color:var(--subtext); font-size:0.8rem;">Preparation starts 30 mins before upload.</div>
        <div style="margin-top:0.75rem; font-size:0.8rem; color:var(--subtext);">Today's {len(yt["slots_today"])} Scheduled Slots:</div>
        <div class="slots-list">
          {''.join(f'<span class="slot-pill">{s}</span>' for s in yt["slots_today"])}
        </div>
      </div>

      <!-- Instagram Card -->
      <div class="card">
        <h2><span>📸 Instagram Reels</span> {ig_prep_badge}</h2>
        <div class="slot-row"><span>Next Target Slot:</span></div>
        <div class="slot-highlight">{ig["next_slot"]}</div>
        <div class="slot-row" style="color:var(--subtext); font-size:0.8rem;">Preparation starts 30 mins before upload.</div>
        <div style="margin-top:0.75rem; font-size:0.8rem; color:var(--subtext);">Today's {len(ig["slots_today"])} Scheduled Slots:</div>
        <div class="slots-list">
          {''.join(f'<span class="slot-pill">{s}</span>' for s in ig["slots_today"])}
        </div>
      </div>

      <!-- Facebook Card -->
      <div class="card">
        <h2><span>👥 Facebook Reels</span> {fb_prep_badge}</h2>
        <div class="slot-row"><span>Next Target Slot:</span></div>
        <div class="slot-highlight">{fb["next_slot"]}</div>
        <div class="slot-row" style="color:var(--subtext); font-size:0.8rem;">Preparation starts 30 mins before upload.</div>
        <div style="margin-top:0.75rem; font-size:0.8rem; color:var(--subtext);">Today's {len(fb["slots_today"])} Scheduled Slots:</div>
        <div class="slots-list">
          {''.join(f'<span class="slot-pill">{s}</span>' for s in fb["slots_today"])}
        </div>
      </div>
    </div>

    <!-- Uploaded Videos Table -->
    <div class="card" style="margin-bottom: 1.5rem;">
      <h2><span>🚀 Published Content & Live Links</span> <span style="font-size:0.8rem; color:var(--subtext);">Recent Uploads</span></h2>
      <table>
        <thead>
          <tr>
            <th>Video Title & Timestamp</th>
            <th>Direct Platform Links</th>
          </tr>
        </thead>
        <tbody>
          {clips_html}
        </tbody>
      </table>
    </div>

    <div class="grid">
      <!-- Monitored Channels -->
      <div class="card">
        <h2><span>📡 Monitored Channels ({len(data["channels"])})</span></h2>
        <div style="margin-top:0.5rem;">
          {channels_html}
        </div>
      </div>

      <!-- Pending Queue -->
      <div class="card">
        <h2><span>📋 links.txt Staging Queue</span></h2>
        <ul class="queue" style="margin-top:0.5rem;">
          {pending_html}
        </ul>
      </div>
    </div>
  </div>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        settings = Settings.from_env()
        data = get_dashboard_data(settings.database_path, settings)

        if self.path == "/api/data":
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

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet logging


def run_dashboard(port: int = 5050) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"[Dashboard] Live Mission Control running at: http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard()

