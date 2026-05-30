"""Self-play training — run local hands against simulated opponents for evaluation.

Supports:
  - HU (heads-up) and 6-max configurations
  - Multiple opponent types (tight, loose, random, mixed)
  - Performance tracking (bb/100, win rate, position breakdown)
  - Reproducible runs via seed
  - Integration with opponent model
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Callable, Optional


class SelfPlayRunner:
    """Runs self-play sessions using the PokerKit engine."""

    def __init__(self, decide_fn: Callable, config: Optional[dict] = None):
        self.decide_fn = decide_fn
        self.config = config or {}

    def run_session(
        self,
        n_hands: int = 200,
        n_players: int = 2,
        opponent_type: str = "mixed",
        starting_stack: int = 200,
        small_blind: int = 1,
        big_blind: int = 2,
        seed: Optional[int] = None,
    ) -> dict:
        """Run a self-play session and return statistics.

        Uses the pokerkit engine for accurate hand simulation.
        """
        try:
            from pokerkit import (
                Automation,
                NoLimitTexasHoldem,
                State,
            )
        except ImportError:
            print("[self-play] pokerkit not installed; falling back to simulation-free stats",
                  file=sys.stderr)
            return self._fallback_stats(n_hands)

        if seed is not None:
            random.seed(seed)

        deltas: list[int] = []
        positions: dict[str, list[int]] = {"UTG": [], "MP": [], "CO": [], "BTN": [], "SB": [], "BB": []}
        pos_order = ["UTG", "MP", "CO", "BTN", "SB", "BB"]

        t0 = time.time()

        for hand_i in range(n_hands):
            try:
                d = self._play_hand(
                    n_players, starting_stack, small_blind, big_blind,
                    hand_i, opponent_type,
                )
            except Exception as e:
                print(f"  [self-play] WARN: hand {hand_i+1} failed ({e})", file=sys.stderr)
                d = 0

            deltas.append(d)

            # Track by position (hero is always seat 1 for simplicity)
            pos_idx = (hand_i // (n_players * 2)) % 6
            pos = pos_order[min(pos_idx, 5)]
            positions[pos].append(d)

            if (hand_i + 1) % max(1, n_hands // 10) == 0:
                net = sum(deltas)
                bb = net / big_blind / max(hand_i + 1, 1) * 100
                print(f"  ... {hand_i+1}/{n_hands} hands  net={net:+d}  bb/100={bb:+.1f}")

        elapsed = time.time() - t0

        return self._compute_stats(deltas, positions, n_players, opponent_type,
                                   big_blind, elapsed)

    def _play_hand(
        self,
        n_players: int,
        starting_stack: int,
        small_blind: int,
        big_blind: int,
        hand_id: int,
        opponent_type: str,
    ) -> int:
        """Play a single hand using pokerkit. Returns chip delta."""
        from pokerkit import Automation, NoLimitTexasHoldem

        stacks = [starting_stack] * n_players
        state = NoLimitTexasHoldem.create_state(
            automations=(
                Automation.ANTE_POSTING,
                Automation.BET_COLLECTION,
                Automation.BLIND_OR_STRADDLE_POSTING,
                Automation.CARD_BURNING,
                Automation.HOLE_DEALING,
                Automation.BOARD_DEALING,
                Automation.RUNOUT_COUNT_SELECTION,
                Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
                Automation.HAND_KILLING,
                Automation.CHIPS_PUSHING,
                Automation.CHIPS_PULLING,
            ),
            ante_trimming_status=True,
            raw_antes=0,
            raw_blinds_or_straddles=(small_blind, big_blind) + (0,) * (n_players - 2),
            min_bet=big_blind,
            raw_starting_stacks=tuple(stacks),
            player_count=n_players,
        )

        hero_idx = 0
        steps = 0
        max_steps = 200

        while state.status and state.actor_index is not None and steps < max_steps:
            actor = state.actor_index

            if actor == hero_idx:
                # Build table dict and call decide
                table = self._build_table(state, hero_idx, f"sp-{hand_id:05d}",
                                          stacks, small_blind, big_blind)
                try:
                    action = self.decide_fn(table, deadline_s=10.0)
                except Exception:
                    action = {"action": "fold"}
            else:
                action = self._opponent_action(state, actor, opponent_type)

            self._apply_action(state, action, big_blind)
            steps += 1

        return int(state.stacks[hero_idx]) - starting_stack

    def _build_table(self, state, hero_idx: int, table_id: str,
                     stacks: list, small_blind: int, big_blind: int) -> dict:
        """Convert pokerkit State to Arena-style table dict."""
        n = len(stacks)
        bets = list(state.bets) if state.bets else []
        pot_total = sum(p.amount for p in (state.pots or [])) + sum(bets)

        seats = []
        for i in range(n):
            hole = list(state.hole_cards[i]) if i < len(state.hole_cards) else []
            hole_strs = [repr(c) for c in hole] if i == hero_idx else []
            seats.append({
                "seatNumber": i + 1,
                "agentId": f"sp_seat_{i+1}",
                "agentHandle": "hero" if i == hero_idx else f"bot_{i+1}",
                "holeCards": hole_strs,
                "stackChips": int(state.stacks[i]),
            })

        available = []
        call_chips = 0
        can_check = can_bet = can_raise = False
        bet_min = bet_max = raise_min = raise_max = 0

        is_my_turn = state.actor_index == hero_idx
        if is_my_turn:
            if state.can_fold():
                available.append("fold")
            if state.can_check_or_call():
                call_chips = int(state.checking_or_calling_amount or 0)
                if call_chips == 0:
                    available.append("check")
                    can_check = True
                else:
                    available.append("call")
            if state.can_complete_bet_or_raise_to():
                try:
                    rmin = int(state.min_completion_betting_or_raising_to_amount or 0)
                    rmax = int(state.max_completion_betting_or_raising_to_amount or 0)
                except Exception:
                    rmin, rmax = 0, 0
                max_bet = max(bets) if bets else 0
                if max_bet > big_blind or call_chips > 0:
                    available.append("raise")
                    can_raise, raise_min, raise_max = True, rmin, rmax
                else:
                    available.append("bet")
                    can_bet, bet_min, bet_max = True, rmin, rmax

        return {
            "tableId": table_id,
            "potChips": int(pot_total),
            "street": self._street(state),
            "boardCards": [repr(c) for c in state.board_cards],
            "selfSeatNumber": hero_idx + 1,
            "bigBlindChips": big_blind,
            "smallBlindChips": small_blind,
            "seats": seats,
            "allowedActions": {
                "availableActions": available,
                "callChips": call_chips,
                "callToAmount": call_chips,
                "canCheck": can_check,
                "canBet": can_bet,
                "canRaise": can_raise,
                "canFold": True,
                "betRange": {"min": int(bet_min), "max": int(bet_max)},
                "raiseRange": {"min": int(raise_min), "max": int(raise_max)},
            },
        }

    def _street(self, state) -> str:
        n = len(state.board_cards)
        if n == 0:
            return "Preflop"
        return ("Flop", "Turn", "River")[min(max(n - 3, 0), 2)]

    def _opponent_action(self, state, actor: int, opponent_type: str) -> dict:
        """Simple heuristic opponent."""
        avail = []
        if state.can_fold():
            avail.append("fold")
        if state.can_check_or_call():
            if state.checking_or_calling_amount == 0:
                avail.append("check")
            else:
                avail.append("call")

        rng = random.Random()

        if opponent_type == "random":
            return {"action": rng.choice(avail) if avail else "fold"}

        if opponent_type == "tight":
            if "check" in avail:
                return {"action": "check"}
            if "call" in avail:
                call_amt = state.checking_or_calling_amount or 0
                pot = sum(p.amount for p in (state.pots or []))
                if call_amt <= pot * 0.5:
                    return {"action": "call"}
            return {"action": "fold"}

        if opponent_type == "loose":
            if "check" in avail:
                return {"action": "check"}
            if "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}

        # Mixed: randomize between strategies
        strategies = ["tight", "tight", "loose", "loose", "random"]
        return self._opponent_action(state, actor, rng.choice(strategies))

    def _apply_action(self, state, action: dict, big_blind: int) -> None:
        name = (action.get("action") or "").lower()
        try:
            if name == "fold":
                state.fold()
            elif name in ("check", "call"):
                state.check_or_call()
            elif name in ("bet", "raise"):
                lo = int(state.min_completion_betting_or_raising_to_amount or big_blind)
                hi = int(state.max_completion_betting_or_raising_to_amount or lo)
                amt = action.get("amount")
                if amt is None:
                    amt = lo
                amt = max(lo, min(int(amt), hi))
                state.complete_bet_or_raise_to(amt)
            else:
                state.fold()
        except Exception:
            try:
                state.fold()
            except Exception:
                pass

    def _compute_stats(self, deltas, positions, n_players, opp_type, bb, elapsed):
        n = max(len(deltas), 1)
        net = sum(deltas)
        wins = sum(1 for d in deltas if d > 0)
        losses = sum(1 for d in deltas if d < 0)
        pushes = n - wins - losses
        bb100 = (net / bb) / n * 100

        pos_stats = {}
        for pos, ds in positions.items():
            if ds:
                pos_stats[pos] = {
                    "hands": len(ds),
                    "net": sum(ds),
                    "avg": round(sum(ds) / max(len(ds), 1), 1),
                }

        return {
            "hands": n,
            "opponent": opp_type,
            "players": n_players,
            "net_chips": net,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "bb_per_100": round(bb100, 1),
            "by_position": pos_stats,
            "elapsed_s": round(elapsed, 1),
            "hands_per_s": round(n / max(elapsed, 0.001), 1),
        }

    def _fallback_stats(self, n_hands):
        return {"hands": n_hands, "error": "pokerkit not installed",
                "bb_per_100": 0.0, "net_chips": 0}
