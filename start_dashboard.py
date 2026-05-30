#!/usr/bin/env python3
"""Standalone dashboard launcher."""
import sys
sys.path.insert(0, '/root/poker-agent')

from src.agent.main_agent import _init_all
from src.dashboard.server import DashboardServer

_init_all()

# Import after init
from src.agent.main_agent import _db, _strategy_params, _leak_detector

server = DashboardServer(host="0.0.0.0", port=8800)
server.configure(db=_db, strategy_params=_strategy_params, leak_detector=_leak_detector)
print("Dashboard running at http://0.0.0.0:8800", flush=True)
server.start(background=False)
