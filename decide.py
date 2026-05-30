"""Top-level decide() entry point for Poker Arena compatibility.

Usage with pokerkit:
    ./pokerkit run --agent decide.py --max-hands 500
    ./pokerkit selfplay --agent decide.py

This file is the minimal bridge between the Arena framework and our agent.
It re-exports the decide() function that Arena calls and the Auto Research hook.
"""

import sys
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agent.main_agent import decide, retrieve_solver_context, on_session_end

# These are the symbols the Arena framework looks for
__all__ = ["decide", "retrieve_solver_context"]
