"""Monitoring Dashboard — web UI for real-time agent performance.

Usage:
  python start_dashboard.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional


def _build_html(stats_json: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Poker Agent Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'SF Mono', 'Consolas', monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
  h1 {{ color: #00ff88; font-size: 24px; margin-bottom: 5px; }}
  .subtitle {{ color: #666; font-size: 12px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
  .card {{ background: #141414; border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; }}
  .card h2 {{ color: #00ff88; font-size: 14px; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 1px; }}
  .stat {{ display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #1a1a1a; }}
  .stat .label {{ color: #888; }}
  .stat .value {{ color: #fff; font-weight: bold; }}
  .positive {{ color: #00ff88 !important; }}
  .negative {{ color: #ff4455 !important; }}
  .neutral {{ color: #ffaa00 !important; }}
  .bar {{ height: 6px; background: #2a2a2a; border-radius: 3px; margin-top: 8px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 1s ease; }}
  .bar-green {{ background: #00ff88; }}
  .bar-red {{ background: #ff4455; }}
  .bar-yellow {{ background: #ffaa00; }}
  .leak {{ padding: 6px 8px; margin: 4px 0; border-radius: 4px; font-size: 12px; }}
  .leak-critical {{ background: #ff445520; border-left: 3px solid #ff4455; }}
  .leak-high {{ background: #ff445510; border-left: 3px solid #ff8866; }}
  .leak-medium {{ background: #ffaa0010; border-left: 3px solid #ffaa00; }}
  .leak-low {{ background: #00ff8810; border-left: 3px solid #00ff88; }}
  #status {{ font-size: 11px; color: #555; margin-top: 20px; text-align: center; }}
  .refresh {{ color: #00ff88; cursor: pointer; text-decoration: underline; font-size: 11px; }}
</style>
</head>
<body>
<h1> Poker Agent Dashboard</h1>
<div class="subtitle">Auto-refreshing every 10s | <span class="refresh" onclick="location.reload()">Refresh Now</span></div>

<div class="grid" id="stats-container">
  <div class="card"><h2>Loading...</h2><p id="loading-msg"></p></div>
</div>

<div id="status">Last update: --</div>

<script>
var STATS = {stats_json};

function fmt(v, d) {{
  if (typeof v !== 'number') return v || '--';
  return v.toFixed(d || 1);
}}
function cls(v) {{
  if (typeof v !== 'number') return '';
  return v > 0 ? 'positive' : (v < 0 ? 'negative' : 'neutral');
}}
function statRow(label, value, clsName, suffix) {{
  suffix = suffix || '';
  var displayVal = typeof value === 'number' ? value.toFixed(1) : (value || '--');
  return '<div class="stat"><span class="label">' + label + '</span><span class="value ' + (clsName||'') + '">' + displayVal + suffix + '</span></div>';
}}

function render(data) {{
  var html = '';

  html += '<div class="card"><h2>Performance</h2>';
  html += statRow('Total Hands', data.total_hands || 0);
  html += statRow('BB/100 (100h)', data.bb_per_100_100, cls(data.bb_per_100_100));
  html += statRow('BB/100 (1000h)', data.bb_per_100_1000, cls(data.bb_per_100_1000));
  html += statRow('ROI', ((data.roi||0)*100), cls(data.roi), '%');
  html += statRow('Win Rate', ((data.win_rate||0)*100), '', '%');
  html += statRow('Net Chips', data.net_chips || 0, cls(data.net_chips));
  html += '</div>';

  html += '<div class="card"><h2>Strategy Stats</h2>';
  html += statRow('VPIP', ((data.vpip||0)*100), '', '%');
  html += statRow('PFR', ((data.pfr||0)*100), '', '%');
  html += statRow('3BET', ((data.three_bet||0)*100), '', '%');
  html += statRow('Fold to CBet', ((data.fold_to_cbet||0)*100), '', '%');
  html += statRow('Agg Factor', data.aggression_factor);
  html += statRow('WTSD', ((data.wtsd||0)*100), '', '%');
  html += statRow('W$SD', ((data.wsd||0)*100), '', '%');
  html += '</div>';

  html += '<div class="card"><h2>Strategy</h2>';
  html += statRow('Version', data.strategy_version || 'v1');
  html += statRow('Active Since', data.strategy_active_since || '--');
  if (data.generation) html += statRow('Evolution Gen', data.generation);
  html += '</div>';

  var positions = data.positions || {{}};
  var posOrder = ['BTN','CO','MP','UTG','SB','BB'];
  html += '<div class="card"><h2>Position P/L</h2>';
  for (var i = 0; i < posOrder.length; i++) {{
    var p = positions[posOrder[i]];
    if (p) html += statRow(posOrder[i], p.bb_per_100 || 0, cls(p.bb_per_100), 'BB/100');
  }}
  html += '</div>';

  var leaks = data.leaks || [];
  html += '<div class="card"><h2>Active Leaks</h2>';
  if (leaks.length === 0) {{
    html += '<p style="color:#888;font-size:12px;">No active leaks detected</p>';
  }} else {{
    for (var j = 0; j < leaks.length; j++) {{
      var l = leaks[j];
      html += '<div class="leak leak-' + (l.severity || 'low') + '">';
      html += '<strong>' + l.type + '</strong> [' + (l.severity || '?') + ']';
      html += '<br><span style="color:#888;font-size:11px;">' + (l.suggestion || '') + '</span>';
      html += '</div>';
    }}
  }}
  html += '</div>';

  var actions = data.action_distribution || {{}};
  var keys = Object.keys(actions).sort(function(a,b) {{ return actions[b] - actions[a]; }}).slice(0, 8);
  html += '<div class="card"><h2>Action Distribution</h2>';
  for (var k = 0; k < keys.length; k++) {{
    var act = keys[k];
    var pct = actions[act] * 100;
    html += '<div style="margin:6px 0;">';
    html += '<div class="stat"><span class="label">' + act + '</span><span class="value">' + pct.toFixed(1) + '%</span></div>';
    html += '<div class="bar"><div class="bar-fill bar-green" style="width:' + pct + '%"></div></div>';
    html += '</div>';
  }}
  html += '</div>';

  document.getElementById('stats-container').innerHTML = html;
  document.getElementById('status').textContent = 'Last update: ' + new Date().toLocaleTimeString();
}}

// Initial render from embedded data
render(STATS);
document.getElementById('loading-msg').textContent = '';

// Auto-refresh
setInterval(function() {{
  fetch('/api/stats')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{ render(data); }})
    .catch(function(e) {{ document.getElementById('status').textContent = 'Refresh error: ' + e.message; }});
}}, 10000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    db = None
    strategy_params = None
    leak_detector = None

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/stats":
            self._serve_stats()
        else:
            self.send_error(404)

    def _serve_html(self):
        stats = self._gather_stats()
        stats_json = json.dumps(stats)
        html = _build_html(stats_json)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_stats(self):
        data = self._gather_stats()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _gather_stats(self) -> dict:
        db = DashboardHandler.db
        params = DashboardHandler.strategy_params
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_hands": 0, "bb_per_100_100": 0, "bb_per_100_1000": 0,
            "roi": 0, "win_rate": 0, "net_chips": 0,
            "vpip": 0, "pfr": 0, "three_bet": 0, "fold_to_cbet": 0,
            "aggression_factor": 0, "wtsd": 0, "wsd": 0,
            "strategy_version": "v1", "strategy_active_since": "--",
            "generation": 0, "positions": {}, "leaks": [],
            "action_distribution": {},
        }

        if db:
            try:
                result["total_hands"] = db.get_hand_count()
                stats100 = db.get_stats_for_n_hands(100)
                stats1000 = db.get_stats_for_n_hands(1000)
                if stats100:
                    result["bb_per_100_100"] = stats100.get("bb_per_100", 0)
                    result["win_rate"] = stats100.get("win_rate", 0) / 100
                if stats1000:
                    result["bb_per_100_1000"] = stats1000.get("bb_per_100", 0)
                    result["net_chips"] = stats1000.get("net_chips", 0)
                result["positions"] = db.get_position_stats(1000)

                # Advanced stats
                adv = self._get_advanced_stats(db, 1000)
                result.update(adv)

                active = db.get_active_strategy()
                if active:
                    result["strategy_version"] = active.get("version", "v1")
                    result["strategy_active_since"] = active.get("created_at", "--")
            except Exception:
                pass

        if params:
            result["strategy_version"] = params.get_version()

        if DashboardHandler.leak_detector:
            try:
                ld = DashboardHandler.leak_detector.detect_all(1000)
                if ld:
                    result["leaks"] = [
                        {"type": l["type"], "severity": l.get("severity", "low"),
                         "suggestion": l.get("suggestion", "")}
                        for l in ld.get("leaks_found", [])
                    ]
            except Exception:
                pass

        return result

    def _get_advanced_stats(self, db, n: int = 1000) -> dict:
        conn = db._get_conn()
        hands = db.get_recent_hands(n)
        if not hands:
            return {}

        hand_ids = [h["hand_id"] for h in hands]
        total = len(hands)
        action_counts: dict[str, int] = {}

        for hid in hand_ids:
            rows = conn.execute(
                "SELECT action FROM actions WHERE hand_id=?", (hid,)
            ).fetchall()
            for r in rows:
                action_counts[r["action"]] = action_counts.get(r["action"], 0) + 1

        total_actions = max(sum(action_counts.values()), 1)
        agg = action_counts.get("bet", 0) + action_counts.get("raise", 0)
        passive = max(action_counts.get("call", 0) + action_counts.get("check", 0), 1)
        af = agg / passive
        river_hands = sum(1 for h in hands if h.get("street_reached") == "River")
        wtsd = river_hands / max(total, 1)
        wsd_wins = sum(1 for h in hands if h.get("street_reached") == "River" and h.get("chip_delta", 0) > 0)
        wsd = wsd_wins / max(river_hands, 1)
        net = sum(h.get("chip_delta", 0) for h in hands)
        invested = sum(
            h.get("stack_start", 0) - h.get("stack_end", 0)
            for h in hands if h.get("stack_start", 0) > h.get("stack_end", 0)
        )
        roi = net / max(invested, 1)

        return {
            "vpip": db.get_stats_for_n_hands(n).get("vpip_estimate", 0) / 100,
            "pfr": round((action_counts.get("raise", 0) + action_counts.get("bet", 0)) / total_actions, 3),
            "three_bet": round(action_counts.get("raise", 0) / total_actions, 3),
            "fold_to_cbet": round(action_counts.get("fold", 0) / total_actions, 3),
            "aggression_factor": round(af, 2),
            "wtsd": round(wtsd, 3),
            "wsd": round(wsd, 3),
            "roi": round(roi, 3),
            "action_distribution": {
                k: round(v / total_actions, 3)
                for k, v in sorted(action_counts.items(), key=lambda x: -x[1])[:8]
            },
        }

    def log_message(self, format, *args):
        pass


class DashboardServer:
    """Wrapper to manage the dashboard HTTP server."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8800):
        self.host = host
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[Thread] = None

    def configure(self, db=None, strategy_params=None, leak_detector=None):
        DashboardHandler.db = db
        DashboardHandler.strategy_params = strategy_params
        DashboardHandler.leak_detector = leak_detector

    def start(self, background: bool = True) -> None:
        self._server = HTTPServer((self.host, self.port), DashboardHandler)
        if background:
            self._thread = Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            print(f"[dashboard] serving at http://{self.host}:{self.port}")
        else:
            print(f"[dashboard] serving at http://{self.host}:{self.port}")
            self._server.serve_forever()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
