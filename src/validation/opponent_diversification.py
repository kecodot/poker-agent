"""Opponent Diversification Framework — 22 new archetypes for robustness testing.

Creates fundamentally different opponent styles to stress-test our strategy.
Each bot has documented: VPIP, PFR, 3Bet, Aggression, Bluff Frequency.

Covers the full taxonomy:
  - Nit variants (UltraNit)
  - LAG variants (HyperAggro, 3BetManiac, AntiLimp)
  - Trap variants (TrapBot, CheckRaiseBot, AntiAggroBot)
  - Sizing variants (MinRaiseBot, OverbetBot, SmallBallBot)
  - Range variants (PolarizedBot, FitOrFoldBot)
  - Adaptive variants (GTOApproxBot, ExploitBot, FloatBot)
  - Money-pressure variants (ShortStackBot, DeepStackBot, BigPotBot)
  - Chaos variants (RandomizedBot, StationBot, DonkBetBot)
  - Meta variants (DelayedCBetBot)
"""

from __future__ import annotations

import random
from typing import Optional

# Import the base classes and bot profiles from the main test
from src.validation.arena_stress_test import (
    OpponentBot, ProfileBot, RandomBot, MonteCarloBot,
    BOT_PROFILES, create_bot,
)


# ═══════════════════════════════════════════════════════════════════
# Helper: create a ProfileBot with a custom profile
# ═══════════════════════════════════════════════════════════════════

def _make_profile_bot(name: str, profile: dict, rng: random.Random) -> ProfileBot:
    """Create a ProfileBot with the given profile dict."""
    bot = ProfileBot(name, profile, rng)
    return bot


# ═══════════════════════════════════════════════════════════════════
# 1. UltraNitBot — plays only absolute premiums
# ═══════════════════════════════════════════════════════════════════

ULTRA_NIT_PROFILE = {
    "vpip": 0.05, "pfr": 0.03, "three_bet": 0.01,
    "fold_to_3bet": 0.90, "af": 1.0,
    "fold_to_cbet": 0.75, "wtsd": 0.10,
    "aggression_postflop": 0.10,
}


class UltraNitBot(ProfileBot):
    """VPIP 5%, PFR 3%, 3Bet 1% — Plays only QQ+/AK, folds everything else."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        if call == 0 and "check" in avail:
            if self.rng.random() < 0.03 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3)}
            return {"action": "check"}
        r = self.rng.random()
        if call == 0:
            if r < 0.03 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3)}
            if r < 0.05 and "call" in avail:
                return {"action": "call"}
            if "fold" in avail:
                return {"action": "fold"}
            return {"action": "check"} if "check" in avail else {"action": "fold"}
        # Facing bet: only 3bet with AA/KK
        if "raise" in avail and r < 0.01:
            return {"action": "raise", "amount": int(call * 3)}
        if r < 0.03 and "call" in avail:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        if call == 0 and "check" in avail:
            if strength > 0.80 and "bet" in avail:
                return {"action": "bet", "amount": int(pot * 0.6)}
            return {"action": "check"}
        if call > 0:
            if strength > 0.85 and "raise" in avail:
                return {"action": "raise", "amount": int(call * 2.5)}
            if strength > 0.70 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 2. HyperAggroBot — max pressure, never stops betting
# ═══════════════════════════════════════════════════════════════════

class HyperAggroBot(ProfileBot):
    """VPIP 95%, PFR 80%, 3Bet 35% — Relentless aggression on every street."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.80 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * (1.5 + r))}
                return {"action": "check"}
            if r < 0.80 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * (1.5 + r))}
            if "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Facing bet: 3bet or call, rarely fold
        if "raise" in avail and r < 0.35:
            return {"action": "raise", "amount": int(call * (2.5 + r * 2))}
        if "call" in avail:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            # Bet almost everything
            if "bet" in avail and r < 0.85:
                sizing = int(pot * (0.5 + r * 1.0))
                return {"action": "bet", "amount": sizing}
            return {"action": "check"}
        if call > 0:
            # Raise or call, almost never fold
            if "raise" in avail and r < 0.40:
                return {"action": "raise", "amount": int(call * (2.0 + r * 2))}
            if "call" in avail and r < 0.90:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 3. 3BetManiacBot — normal opening, insane 3-betting
# ═══════════════════════════════════════════════════════════════════

class ThreeBetManiacBot(ProfileBot):
    """VPIP 30%, PFR 20%, 3Bet 45% — Will 3-bet relentlessly when facing opens."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.20 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 2.5)}
                return {"action": "check"}
            if r < 0.20 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.2)}
            if r < 0.30 and "call" in avail:
                return {"action": "call"}
            if "fold" in avail:
                return {"action": "fold"}
            return {"action": "check"} if "check" in avail else {"action": "fold"}
        # Facing bet: 3bet mania
        if "raise" in avail and r < 0.45:
            return {"action": "raise", "amount": int(call * (2.5 + r))}
        if "call" in avail and r < 0.70:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.50:
                return {"action": "bet", "amount": int(pot * 0.6)}
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and r < 0.30:
                return {"action": "raise", "amount": int(call * 2.5)}
            if "call" in avail and r < 0.55:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 4. TrapBot — passive pre, deadly post
# ═══════════════════════════════════════════════════════════════════

class TrapBot(ProfileBot):
    """VPIP 25%, PFR 8%, 3Bet 2% — Limps premiums, then springs traps postflop."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.30 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3)}
                return {"action": "check"}
            # Limp most hands including premiums
            if r < 0.08 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3)}
            if r < 0.25 and "call" in avail:
                return {"action": "call"}
            if "fold" in avail:
                return {"action": "fold"}
            return {"action": "check"} if "check" in avail else {"action": "fold"}
        # Facing bet: call or trap-raise
        if "raise" in avail and r < 0.08:
            return {"action": "raise", "amount": int(call * 3)}
        if "call" in avail and r < 0.50:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            # Check to trap, bet only with moderate strength to balance
            if strength > 0.85 and r < 0.20 and "bet" in avail:
                return {"action": "bet", "amount": int(pot * 0.4)}
            return {"action": "check"}
        if call > 0:
            # Spring trap: raise with strong hands, call with draws
            if strength > 0.70 and "raise" in avail and r < 0.60:
                return {"action": "raise", "amount": int(call * 3.0)}
            if "call" in avail and r < 0.65:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 5. MinRaiseBot — always clicks min-raise
# ═══════════════════════════════════════════════════════════════════

class MinRaiseBot(ProfileBot):
    """VPIP 28%, PFR 20%, 3Bet 8% — Min-raises every time, never sizes up."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.20 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 1.05)}  # min-raise
                return {"action": "check"}
            if r < 0.20 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 1.05)}
            if r < 0.28 and "call" in avail:
                return {"action": "call"}
            if "fold" in avail:
                return {"action": "fold"}
            return {"action": "check"} if "check" in avail else {"action": "fold"}
        if "raise" in avail and r < 0.08:
            return {"action": "raise", "amount": int(call * 2.0)}  # exact min
        if "call" in avail and r < 0.45:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.35:
                return {"action": "bet", "amount": max(1, int(pot * 0.25))}  # tiny bet
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and r < 0.12:
                return {"action": "raise", "amount": int(call * 2.0)}  # min-raise
            if "call" in avail and r < 0.50:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 6. OverbetBot — loves 2x+ pot overbets
# ═══════════════════════════════════════════════════════════════════

class OverbetBot(ProfileBot):
    """VPIP 25%, PFR 18%, 3Bet 8% — Uses massive overbets as primary sizing."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.18 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * (4 + r * 3))}
                return {"action": "check"}
            if r < 0.18 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 4)}
            if r < 0.25 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail and r < 0.08:
            return {"action": "raise", "amount": int(pot * 5)}
        if "call" in avail and r < 0.40:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.45:
                sizing = int(pot * (1.5 + r * 1.5))  # 1.5-3x pot
                return {"action": "bet", "amount": sizing}
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and r < 0.20:
                return {"action": "raise", "amount": int(pot * 2.5)}
            if "call" in avail and r < 0.35 and call <= pot * 2:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 7. PolarizedBot — only premiums and trash, no middle
# ═══════════════════════════════════════════════════════════════════

class PolarizedBot(ProfileBot):
    """VPIP 35%, PFR 25%, 3Bet 15% — Top 15% OR bottom 20%, nothing in between."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        # Simulates polarized: use bimodal random
        polarized_r = self.rng.random()  # 0-1 for hand "quality"
        is_premium = polarized_r < 0.15
        is_bluff = 0.15 <= polarized_r < 0.35

        if call == 0:
            if "check" in avail:
                if is_premium and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3.5)}
                return {"action": "check"}
            if is_premium and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3)}
            if is_bluff:
                if "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 2.2)}
            if "fold" in avail:
                return {"action": "fold"}
            return {"action": "check"} if "check" in avail else {"action": "fold"}
        if is_premium and "raise" in avail:
            return {"action": "raise", "amount": int(call * 3)}
        if is_bluff and "call" in avail:
            return {"action": "call"}  # float
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                if strength > 0.70:
                    return {"action": "bet", "amount": int(pot * 0.75)}
                if r < 0.25:  # polar bluff
                    return {"action": "bet", "amount": int(pot * (0.6 + r * 0.8))}
            return {"action": "check"}
        if call > 0:
            if strength > 0.70 and "raise" in avail and r < 0.50:
                return {"action": "raise", "amount": int(call * 2.5)}
            if strength > 0.50 and "call" in avail and r < 0.40:
                return {"action": "call"}
            # Polar bluff-raise
            if "raise" in avail and r < 0.12:
                return {"action": "raise", "amount": int(call * 3)}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 8. GTOApproxBot — balanced frequencies, near-optimal sizing
# ═══════════════════════════════════════════════════════════════════

class GTOApproxBot(ProfileBot):
    """VPIP 30%, PFR 22%, 3Bet 10% — Uses balanced, mixed frequencies everywhere."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                # BB: raise 25%, check 75% (balanced)
                if r < 0.25 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3.0)}
                return {"action": "check"}
            # Unopened: raise 22%, limp 8%, fold 70% (GTO BTN open ~55% but balanced)
            if r < 0.22 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.5)}
            if r < 0.30 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Facing bet: 3bet 10%, call 55%, fold 35%
        if "raise" in avail and r < 0.10:
            return {"action": "raise", "amount": int(call * 3.0)}
        if "call" in avail and r < 0.65:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                # Bet proportional to strength, check some strong hands for balance
                if strength > 0.70 and r < 0.75:
                    return {"action": "bet", "amount": int(pot * 0.66)}
                if 0.40 < strength <= 0.70 and r < 0.35:
                    return {"action": "bet", "amount": int(pot * 0.50)}
                if r < 0.10:  # balanced bluff frequency
                    return {"action": "bet", "amount": int(pot * 0.33)}
            return {"action": "check"}
        if call > 0:
            # MDF-approximation: defend enough to prevent auto-profit
            call_pct = call / max(pot + call, 1)
            if strength > 0.75 and "raise" in avail and r < 0.40:
                return {"action": "raise", "amount": int(call * 2.8)}
            # Call if pot odds justified by MDF
            if "call" in avail and call_pct < 0.45:
                defend_threshold = 0.60 - call_pct  # higher bet = less defense
                if r < defend_threshold:
                    return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 9. DelayedCBetBot — checks flop, bets turn at high frequency
# ═══════════════════════════════════════════════════════════════════

class DelayedCBetBot(ProfileBot):
    """VPIP 25%, PFR 18%, 3Bet 7% — Rarely cbets flop, probes turn aggressively."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        return super()._decide_preflop(avail, call, pot, stack, is_hu)

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                if street == "Flop":
                    # Low cbet on flop
                    if strength > 0.80 and r < 0.30:
                        return {"action": "bet", "amount": int(pot * 0.50)}
                    return {"action": "check"}
                else:
                    # High probe bet on turn/river
                    if r < 0.55:
                        return {"action": "bet", "amount": int(pot * 0.60)}
            return {"action": "check"}
        if call > 0:
            if strength > 0.65 and "raise" in avail and r < 0.25:
                return {"action": "raise", "amount": int(call * 2.5)}
            if "call" in avail and r < 0.50:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 10. CheckRaiseBot — high check-raise frequency
# ═══════════════════════════════════════════════════════════════════

class CheckRaiseBot(ProfileBot):
    """VPIP 27%, PFR 16%, 3Bet 9% — Check-raises at extremely high frequency."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        return super()._decide_preflop(avail, call, pot, stack, is_hu)

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            # Check most hands (set up for x/r)
            if strength > 0.85 and r < 0.15 and "bet" in avail:
                return {"action": "bet", "amount": int(pot * 0.5)}
            return {"action": "check"}
        if call > 0:
            # HIGH check-raise frequency
            if "raise" in avail and r < 0.40:
                sizing = int(call * (2.5 + r))
                return {"action": "raise", "amount": sizing}
            if "call" in avail and r < 0.30:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 11. FloatBot — floats flop cbets, bets turn when checked to
# ═══════════════════════════════════════════════════════════════════

class FloatBot(ProfileBot):
    """VPIP 28%, PFR 15%, 3Bet 8% — Floats flop frequently, steals on turn."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        return super()._decide_preflop(avail, call, pot, stack, is_hu)

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                if street == "Flop":
                    if r < 0.25:
                        return {"action": "bet", "amount": int(pot * 0.45)}
                else:
                    # On turn/river when checked to: bet high frequency (stole pot)
                    if r < 0.55:
                        return {"action": "bet", "amount": int(pot * 0.65)}
            return {"action": "check"}
        if call > 0:
            call_pct = call / max(pot + call, 1)
            if street == "Flop":
                # Float flop: call wider than normal
                if "call" in avail and call_pct < 0.5 and r < 0.65:
                    return {"action": "call"}
            else:
                # Turn/river: more standard
                if strength > 0.60 and "raise" in avail and r < 0.20:
                    return {"action": "raise", "amount": int(call * 2.3)}
                if "call" in avail and r < 0.35:
                    return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 12. DonkBetBot — high donk-bet frequency
# ═══════════════════════════════════════════════════════════════════

class DonkBetBot(ProfileBot):
    """VPIP 30%, PFR 14%, 3Bet 5% — Donk-bets into preflop raiser constantly."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        return super()._decide_preflop(avail, call, pot, stack, is_hu)

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                # Donk bet at high frequency (betting OOP into PFR)
                if r < 0.45:
                    sizing = int(pot * (0.33 + r * 0.4))
                    return {"action": "bet", "amount": sizing}
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and r < 0.18:
                return {"action": "raise", "amount": int(call * 2.3)}
            if "call" in avail and r < 0.40:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 13. AntiLimpBot — punishes limpers with isolation raises
# ═══════════════════════════════════════════════════════════════════

class AntiLimpBot(ProfileBot):
    """VPIP 32%, PFR 26%, 3Bet 12% — Isolation-raises limpers relentlessly."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.35 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3.5)}
                return {"action": "check"}
            # Punish limpers: raise very wide
            if r < 0.26 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3.0)}
            if r < 0.32 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Facing bet: 3bet wide to isolate
        if "raise" in avail and r < 0.12:
            return {"action": "raise", "amount": int(call * 3.0)}
        if "call" in avail and r < 0.40:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.50:
                return {"action": "bet", "amount": int(pot * 0.65)}
            return {"action": "check"}
        if call > 0:
            if strength > 0.65 and "raise" in avail and r < 0.30:
                return {"action": "raise", "amount": int(call * 2.5)}
            if "call" in avail and r < 0.40:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 14. AntiAggroBot — traps aggressive opponents
# ═══════════════════════════════════════════════════════════════════

class AntiAggroBot(ProfileBot):
    """VPIP 28%, PFR 10%, 3Bet 4% — Calls down aggro, traps with strong hands."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.10 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3)}
                return {"action": "check"}
            if r < 0.10 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.5)}
            if r < 0.28 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Call down vs aggression
        if "raise" in avail and r < 0.04:
            return {"action": "raise", "amount": int(call * 3.5)}
        if "call" in avail and r < 0.60:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if strength > 0.85 and r < 0.25 and "bet" in avail:
                return {"action": "bet", "amount": int(pot * 0.35)}
            return {"action": "check"}
        if call > 0:
            # Call down light (trap aggressive bluffs)
            call_pct = call / max(pot + call, 1)
            if strength > 0.80 and "raise" in avail and r < 0.35:
                return {"action": "raise", "amount": int(call * 2.0)}
            if "call" in avail and call_pct < 0.5 and r < 0.70:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 15. ExploitBot — exploits standard tendencies
# ═══════════════════════════════════════════════════════════════════

class ExploitBot(ProfileBot):
    """VPIP 30%, PFR 22%, 3Bet 14% — Cbets dry flops, over-folds to 3bets, steals blinds."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.22 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 2.5)}
                return {"action": "check"}
            if r < 0.22 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.2)}
            if r < 0.30 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail and r < 0.14:
            return {"action": "raise", "amount": int(call * 3.0)}
        if "call" in avail and r < 0.35:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                # High cbet on dry boards, probe turns
                if street == "Flop" and r < 0.65:
                    return {"action": "bet", "amount": int(pot * 0.55)}
                if street != "Flop" and r < 0.45:
                    return {"action": "bet", "amount": int(pot * 0.60)}
            return {"action": "check"}
        if call > 0:
            if strength > 0.65 and "raise" in avail and r < 0.25:
                return {"action": "raise", "amount": int(call * 2.5)}
            call_pct = call / max(pot + call, 1)
            if "call" in avail and call_pct < 0.35 and r < 0.40:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 16. RandomizedBot — completely random decisions
# ═══════════════════════════════════════════════════════════════════

class RandomizedBot(ProfileBot):
    """VPIP 50%, PFR 35%, 3Bet 15% — Every decision is a coin flip."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        if "raise" in avail and self.rng.random() < 0.35:
            return {"action": "raise", "amount": int(pot * self.rng.uniform(0.5, 5.0))}
        if "call" in avail and self.rng.random() < 0.50:
            return {"action": "call"}
        if "check" in avail and self.rng.random() < 0.50:
            return {"action": "check"}
        if "fold" in avail:
            return {"action": "fold"}
        return {"action": "check"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.40:
                return {"action": "bet", "amount": int(pot * self.rng.uniform(0.2, 2.0))}
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and r < 0.20:
                return {"action": "raise", "amount": int(call * self.rng.uniform(2.0, 4.0))}
            if "call" in avail and r < 0.45:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 17. SmallBallBot — many small bets, avoids big pots
# ═══════════════════════════════════════════════════════════════════

class SmallBallBot(ProfileBot):
    """VPIP 35%, PFR 15%, 3Bet 5% — Small bets everywhere, never builds big pots."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.15 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 2.0)}
                return {"action": "check"}
            if r < 0.15 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.0)}
            if r < 0.35 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail and r < 0.05:
            return {"action": "raise", "amount": int(call * 2.0)}
        if "call" in avail and r < 0.55:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and r < 0.35:
                return {"action": "bet", "amount": int(pot * 0.25)}  # always 1/4 pot
            return {"action": "check"}
        if call > 0:
            # Avoid big pots: fold to large bets
            call_pct = call / max(pot + call, 1)
            if "call" in avail and call_pct < 0.3 and r < 0.55:
                return {"action": "call"}
            if "raise" in avail and r < 0.08:
                return {"action": "raise", "amount": int(call * 2.0)}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 18. BigPotBot — inflates pots with any decent hand
# ═══════════════════════════════════════════════════════════════════

class BigPotBot(ProfileBot):
    """VPIP 35%, PFR 25%, 3Bet 15% — Overplays hands, builds massive pots."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.30 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 4)}
                return {"action": "check"}
            if r < 0.25 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3.5)}
            if r < 0.35 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail and r < 0.15:
            return {"action": "raise", "amount": int(call * 4.0)}
        if "call" in avail and r < 0.50:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail:
                # Overbet with any piece
                if r < 0.55:
                    return {"action": "bet", "amount": int(pot * (1.0 + r * 1.5))}
            return {"action": "check"}
        if call > 0:
            # Raise or call big
            if "raise" in avail and r < 0.30:
                return {"action": "raise", "amount": int(call * 3.0)}
            if "call" in avail and r < 0.55:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 19. FitOrFoldBot — only plays made hands
# ═══════════════════════════════════════════════════════════════════

class FitOrFoldBot(ProfileBot):
    """VPIP 22%, PFR 10%, 3Bet 3% — Folds without pair+ or strong draw."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.10 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3)}
                return {"action": "check"}
            if r < 0.10 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 3)}
            if r < 0.22 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail and r < 0.03:
            return {"action": "raise", "amount": int(call * 3)}
        if "call" in avail and r < 0.30:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        if call == 0 and "check" in avail:
            if "bet" in avail and strength > 0.55:
                return {"action": "bet", "amount": int(pot * 0.6)}
            return {"action": "check"}
        if call > 0:
            # Only continue with strong hands
            if strength > 0.80 and "raise" in avail:
                return {"action": "raise", "amount": int(call * 3)}
            if strength > 0.55 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 20. StationBot — never folds any pair or draw
# ═══════════════════════════════════════════════════════════════════

class StationBot(ProfileBot):
    """VPIP 40%, PFR 5%, 3Bet 1% — Ultimate calling station, never folds."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.05 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3)}
                return {"action": "check"}
            if r < 0.05 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.5)}
            if "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Never fold preflop if possible
        if "call" in avail:
            return {"action": "call"}
        if "raise" in avail and r < 0.10:
            return {"action": "raise", "amount": int(call * 2)}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        if call == 0 and "check" in avail:
            if "bet" in avail and strength > 0.60 and r < 0.15:
                return {"action": "bet", "amount": int(pot * 0.4)}
            return {"action": "check"}
        if call > 0:
            # Never fold with any piece
            if strength > 0.70 and "raise" in avail and r < 0.10:
                return {"action": "raise", "amount": int(call * 2)}
            if "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 21. ShortStackBot — plays 50BB short-stack strategy
# ═══════════════════════════════════════════════════════════════════

class ShortStackBot(ProfileBot):
    """VPIP 22%, PFR 18%, 3Bet 10% — Short-stack: raise/fold, shoves light."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        # Short-stack: push/fold dynamic
        spr = stack / max(pot, 1)
        if call == 0:
            if "check" in avail:
                if r < 0.18 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 2.5)}
                return {"action": "check"}
            if r < 0.18 and "raise" in avail:
                # Sometimes shove
                if spr < 8 and r < 0.25:
                    return {"action": "raise", "amount": stack}
                return {"action": "raise", "amount": int(pot * 2.5)}
            if r < 0.22 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        if "raise" in avail:
            if r < 0.12:
                # Shove or large 3bet
                amt = stack if spr < 6 else int(call * 3.5)
                return {"action": "raise", "amount": amt}
        if "call" in avail and r < 0.35:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        # Estimate stack from pot (short-stack simulation: assume 50BB)
        est_stack = pot * 10
        spr = est_stack / max(pot, 1)
        if call == 0 and "check" in avail:
            if "bet" in avail:
                if spr < 4 and strength > 0.55:  # Commit
                    return {"action": "bet", "amount": est_stack}
                if r < 0.35:
                    return {"action": "bet", "amount": int(pot * 0.55)}
            return {"action": "check"}
        if call > 0:
            if "raise" in avail and strength > 0.60 and r < 0.30:
                amt = est_stack if spr < 5 else int(call * 2.5)
                return {"action": "raise", "amount": amt}
            if "call" in avail and r < 0.30:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# 22. DeepStackBot — plays 500BB deep, more postflop
# ═══════════════════════════════════════════════════════════════════

class DeepStackBot(ProfileBot):
    """VPIP 32%, PFR 20%, 3Bet 8% — Deep-stack: more call/float, more postflop pressure."""

    def _decide_preflop(self, avail, call, pot, stack, is_hu=True):
        r = self.rng.random()
        if call == 0:
            if "check" in avail:
                if r < 0.20 and "raise" in avail:
                    return {"action": "raise", "amount": int(pot * 3.0)}
                return {"action": "check"}
            if r < 0.20 and "raise" in avail:
                return {"action": "raise", "amount": int(pot * 2.8)}
            if r < 0.32 and "call" in avail:
                return {"action": "call"}
            return {"action": "fold"}
        # Deep: more calling, less 3betting
        if "raise" in avail and r < 0.08:
            return {"action": "raise", "amount": int(call * 3.0)}
        if "call" in avail and r < 0.55:
            return {"action": "call"}
        return {"action": "fold"}

    def _decide_postflop(self, avail, call, pot, street, strength, is_hu=True):
        r = self.rng.random()
        # Deep: more floating, more turn/river pressure
        if call == 0 and "check" in avail:
            if "bet" in avail:
                if strength > 0.70 and r < 0.55:
                    return {"action": "bet", "amount": int(pot * 0.70)}
                if r < 0.25:
                    return {"action": "bet", "amount": int(pot * 0.45)}
            return {"action": "check"}
        if call > 0:
            call_pct = call / max(pot + call, 1)
            if strength > 0.70 and "raise" in avail and r < 0.25:
                return {"action": "raise", "amount": int(call * 2.8)}
            # Deep: call wider on early streets
            if "call" in avail and call_pct < 0.5 and r < 0.55:
                return {"action": "call"}
            return {"action": "fold"}
        return {"action": "check"}


# ═══════════════════════════════════════════════════════════════════
# Bot registry with documentation
# ═══════════════════════════════════════════════════════════════════

ALL_DIVERSE_BOTS: dict[str, dict] = {
    # (factory_function or class, documented_stats, description)
}

DIVERSE_BOT_FACTORIES = {
    "UltraNitBot": lambda rng: UltraNitBot("UltraNitBot", ULTRA_NIT_PROFILE, rng),
    "HyperAggroBot": lambda rng: HyperAggroBot("HyperAggroBot",
        {"vpip": 0.55, "pfr": 0.42, "three_bet": 0.18,
         "fold_to_3bet": 0.15, "af": 6.0,
         "fold_to_cbet": 0.15, "wtsd": 0.38,
         "aggression_postflop": 0.70}, rng),
    "3BetManiacBot": lambda rng: ThreeBetManiacBot("3BetManiacBot",
        {"vpip": 0.30, "pfr": 0.20, "three_bet": 0.45,
         "fold_to_3bet": 0.30, "af": 3.5,
         "fold_to_cbet": 0.35, "wtsd": 0.30,
         "aggression_postflop": 0.45}, rng),
    "TrapBot": lambda rng: TrapBot("TrapBot",
        {"vpip": 0.25, "pfr": 0.08, "three_bet": 0.02,
         "fold_to_3bet": 0.40, "af": 2.0,
         "fold_to_cbet": 0.55, "wtsd": 0.35,
         "aggression_postflop": 0.50}, rng),
    "MinRaiseBot": lambda rng: MinRaiseBot("MinRaiseBot",
        {"vpip": 0.28, "pfr": 0.20, "three_bet": 0.08,
         "fold_to_3bet": 0.45, "af": 1.5,
         "fold_to_cbet": 0.42, "wtsd": 0.30,
         "aggression_postflop": 0.30}, rng),
    "OverbetBot": lambda rng: OverbetBot("OverbetBot",
        {"vpip": 0.25, "pfr": 0.18, "three_bet": 0.08,
         "fold_to_3bet": 0.38, "af": 4.0,
         "fold_to_cbet": 0.35, "wtsd": 0.28,
         "aggression_postflop": 0.60}, rng),
    "PolarizedBot": lambda rng: PolarizedBot("PolarizedBot",
        {"vpip": 0.35, "pfr": 0.25, "three_bet": 0.15,
         "fold_to_3bet": 0.40, "af": 3.5,
         "fold_to_cbet": 0.40, "wtsd": 0.28,
         "aggression_postflop": 0.50}, rng),
    "GTOApproxBot": lambda rng: GTOApproxBot("GTOApproxBot",
        {"vpip": 0.30, "pfr": 0.22, "three_bet": 0.10,
         "fold_to_3bet": 0.50, "af": 2.5,
         "fold_to_cbet": 0.45, "wtsd": 0.35,
         "aggression_postflop": 0.40}, rng),
    "DelayedCBetBot": lambda rng: DelayedCBetBot("DelayedCBetBot",
        {"vpip": 0.25, "pfr": 0.18, "three_bet": 0.07,
         "fold_to_3bet": 0.50, "af": 2.2,
         "fold_to_cbet": 0.50, "wtsd": 0.32,
         "aggression_postflop": 0.40}, rng),
    "CheckRaiseBot": lambda rng: CheckRaiseBot("CheckRaiseBot",
        {"vpip": 0.27, "pfr": 0.16, "three_bet": 0.09,
         "fold_to_3bet": 0.40, "af": 3.0,
         "fold_to_cbet": 0.35, "wtsd": 0.32,
         "aggression_postflop": 0.50}, rng),
    "FloatBot": lambda rng: FloatBot("FloatBot",
        {"vpip": 0.28, "pfr": 0.15, "three_bet": 0.08,
         "fold_to_3bet": 0.45, "af": 2.5,
         "fold_to_cbet": 0.35, "wtsd": 0.32,
         "aggression_postflop": 0.45}, rng),
    "DonkBetBot": lambda rng: DonkBetBot("DonkBetBot",
        {"vpip": 0.30, "pfr": 0.14, "three_bet": 0.05,
         "fold_to_3bet": 0.40, "af": 2.0,
         "fold_to_cbet": 0.50, "wtsd": 0.30,
         "aggression_postflop": 0.40}, rng),
    "AntiLimpBot": lambda rng: AntiLimpBot("AntiLimpBot",
        {"vpip": 0.32, "pfr": 0.26, "three_bet": 0.12,
         "fold_to_3bet": 0.35, "af": 3.5,
         "fold_to_cbet": 0.35, "wtsd": 0.30,
         "aggression_postflop": 0.50}, rng),
    "AntiAggroBot": lambda rng: AntiAggroBot("AntiAggroBot",
        {"vpip": 0.28, "pfr": 0.10, "three_bet": 0.04,
         "fold_to_3bet": 0.55, "af": 1.5,
         "fold_to_cbet": 0.25, "wtsd": 0.45,
         "aggression_postflop": 0.25}, rng),
    "ExploitBot": lambda rng: ExploitBot("ExploitBot",
        {"vpip": 0.30, "pfr": 0.22, "three_bet": 0.14,
         "fold_to_3bet": 0.45, "af": 3.0,
         "fold_to_cbet": 0.40, "wtsd": 0.30,
         "aggression_postflop": 0.50}, rng),
    "RandomizedBot": lambda rng: RandomizedBot("RandomizedBot",
        {"vpip": 0.50, "pfr": 0.35, "three_bet": 0.15,
         "fold_to_3bet": 0.50, "af": 2.0,
         "fold_to_cbet": 0.50, "wtsd": 0.40,
         "aggression_postflop": 0.40}, rng),
    "SmallBallBot": lambda rng: SmallBallBot("SmallBallBot",
        {"vpip": 0.35, "pfr": 0.15, "three_bet": 0.05,
         "fold_to_3bet": 0.50, "af": 1.5,
         "fold_to_cbet": 0.40, "wtsd": 0.35,
         "aggression_postflop": 0.25}, rng),
    "BigPotBot": lambda rng: BigPotBot("BigPotBot",
        {"vpip": 0.35, "pfr": 0.25, "three_bet": 0.15,
         "fold_to_3bet": 0.25, "af": 5.0,
         "fold_to_cbet": 0.20, "wtsd": 0.35,
         "aggression_postflop": 0.65}, rng),
    "FitOrFoldBot": lambda rng: FitOrFoldBot("FitOrFoldBot",
        {"vpip": 0.22, "pfr": 0.10, "three_bet": 0.03,
         "fold_to_3bet": 0.65, "af": 1.2,
         "fold_to_cbet": 0.60, "wtsd": 0.15,
         "aggression_postflop": 0.15}, rng),
    "StationBot": lambda rng: StationBot("StationBot",
        {"vpip": 0.40, "pfr": 0.05, "three_bet": 0.01,
         "fold_to_3bet": 0.10, "af": 0.3,
         "fold_to_cbet": 0.10, "wtsd": 0.65,
         "aggression_postflop": 0.05}, rng),
    "ShortStackBot": lambda rng: ShortStackBot("ShortStackBot",
        {"vpip": 0.22, "pfr": 0.18, "three_bet": 0.10,
         "fold_to_3bet": 0.40, "af": 3.0,
         "fold_to_cbet": 0.35, "wtsd": 0.25,
         "aggression_postflop": 0.45}, rng),
    "DeepStackBot": lambda rng: DeepStackBot("DeepStackBot",
        {"vpip": 0.32, "pfr": 0.20, "three_bet": 0.08,
         "fold_to_3bet": 0.45, "af": 2.5,
         "fold_to_cbet": 0.40, "wtsd": 0.33,
         "aggression_postflop": 0.40}, rng),
}

# Documented stats for each bot
DIVERSE_BOT_DOCS = {
    # Original 7 bots
    "RandomBot":            {"vpip_h": "45%", "pfr_h": "30%", "3bet_h": "10%", "af_h": "1.5", "bluff_h": "Random", "pool": "mixed"},
    "NitBot":               {"vpip_h": "12%", "pfr_h": "8%", "3bet_h": "3%", "af_h": "1.0", "bluff_h": "Very Low", "pool": "passive"},
    "TAGBot":               {"vpip_h": "20%", "pfr_h": "16%", "3bet_h": "6%", "af_h": "2.5", "bluff_h": "Low", "pool": "mixed"},
    "LAGBot":               {"vpip_h": "30%", "pfr_h": "25%", "3bet_h": "10%", "af_h": "3.5", "bluff_h": "High", "pool": "aggressive"},
    "CallingStationBot":    {"vpip_h": "35%", "pfr_h": "8%", "3bet_h": "2%", "af_h": "0.6", "bluff_h": "None", "pool": "passive"},
    "ManiacBot":            {"vpip_h": "55%", "pfr_h": "42%", "3bet_h": "18%", "af_h": "6.0", "bluff_h": "Very High", "pool": "aggressive"},
    "MonteCarloBot":        {"vpip_h": "25%", "pfr_h": "18%", "3bet_h": "7%", "af_h": "2.0", "bluff_h": "Low", "pool": "mixed"},
    # 22 new bots
    "UltraNitBot":         {"vpip_h": "5%", "pfr_h": "3%", "3bet_h": "1%", "af_h": "1.0", "bluff_h": "Very Low", "pool": "passive"},
    "HyperAggroBot":       {"vpip_h": "95%", "pfr_h": "80%", "3bet_h": "35%", "af_h": "8.0", "bluff_h": "Very High", "pool": "aggressive"},
    "3BetManiacBot":       {"vpip_h": "30%", "pfr_h": "20%", "3bet_h": "45%", "af_h": "3.5", "bluff_h": "High", "pool": "aggressive"},
    "TrapBot":             {"vpip_h": "25%", "pfr_h": "8%", "3bet_h": "2%", "af_h": "2.0", "bluff_h": "Low", "pool": "mixed"},
    "MinRaiseBot":         {"vpip_h": "28%", "pfr_h": "20%", "3bet_h": "8%", "af_h": "1.5", "bluff_h": "Medium", "pool": "mixed"},
    "OverbetBot":          {"vpip_h": "25%", "pfr_h": "18%", "3bet_h": "8%", "af_h": "4.0", "bluff_h": "High", "pool": "aggressive"},
    "PolarizedBot":        {"vpip_h": "35%", "pfr_h": "25%", "3bet_h": "15%", "af_h": "3.5", "bluff_h": "High", "pool": "aggressive"},
    "GTOApproxBot":        {"vpip_h": "30%", "pfr_h": "22%", "3bet_h": "10%", "af_h": "2.5", "bluff_h": "Balanced", "pool": "mixed"},
    "DelayedCBetBot":      {"vpip_h": "25%", "pfr_h": "18%", "3bet_h": "7%", "af_h": "2.2", "bluff_h": "Medium", "pool": "mixed"},
    "CheckRaiseBot":       {"vpip_h": "27%", "pfr_h": "16%", "3bet_h": "9%", "af_h": "3.0", "bluff_h": "High", "pool": "aggressive"},
    "FloatBot":            {"vpip_h": "28%", "pfr_h": "15%", "3bet_h": "8%", "af_h": "2.5", "bluff_h": "High", "pool": "aggressive"},
    "DonkBetBot":          {"vpip_h": "30%", "pfr_h": "14%", "3bet_h": "5%", "af_h": "2.0", "bluff_h": "Medium", "pool": "mixed"},
    "AntiLimpBot":         {"vpip_h": "32%", "pfr_h": "26%", "3bet_h": "12%", "af_h": "3.5", "bluff_h": "High", "pool": "aggressive"},
    "AntiAggroBot":        {"vpip_h": "28%", "pfr_h": "10%", "3bet_h": "4%", "af_h": "1.5", "bluff_h": "Low", "pool": "passive"},
    "ExploitBot":          {"vpip_h": "30%", "pfr_h": "22%", "3bet_h": "14%", "af_h": "3.0", "bluff_h": "Medium", "pool": "mixed"},
    "RandomizedBot":       {"vpip_h": "50%", "pfr_h": "35%", "3bet_h": "15%", "af_h": "2.0", "bluff_h": "Random", "pool": "mixed"},
    "SmallBallBot":        {"vpip_h": "35%", "pfr_h": "15%", "3bet_h": "5%", "af_h": "1.5", "bluff_h": "Low", "pool": "passive"},
    "BigPotBot":           {"vpip_h": "35%", "pfr_h": "25%", "3bet_h": "15%", "af_h": "5.0", "bluff_h": "High", "pool": "aggressive"},
    "FitOrFoldBot":        {"vpip_h": "22%", "pfr_h": "10%", "3bet_h": "3%", "af_h": "1.2", "bluff_h": "Very Low", "pool": "passive"},
    "StationBot":          {"vpip_h": "40%", "pfr_h": "5%", "3bet_h": "1%", "af_h": "0.3", "bluff_h": "None", "pool": "passive"},
    "ShortStackBot":       {"vpip_h": "22%", "pfr_h": "18%", "3bet_h": "10%", "af_h": "3.0", "bluff_h": "Medium", "pool": "mixed"},
    "DeepStackBot":        {"vpip_h": "32%", "pfr_h": "20%", "3bet_h": "8%", "af_h": "2.5", "bluff_h": "Medium", "pool": "mixed"},
}

# Pool classifier mapping for these bots (for strategy routing)
DIVERSE_BOT_POOL_MAP = {
    name: doc["pool"] for name, doc in DIVERSE_BOT_DOCS.items()
}


def create_diverse_bot(name: str, rng: random.Random) -> OpponentBot:
    """Factory for all diverse bots."""
    factory = DIVERSE_BOT_FACTORIES.get(name)
    if factory:
        return factory(rng)
    # Fall back to original bot creation
    return create_bot(name, rng)


def get_all_bot_types() -> list[str]:
    """Return all bot type names (original 7 + new 22)."""
    original = ["RandomBot", "NitBot", "TAGBot", "LAGBot", "CallingStationBot", "ManiacBot", "MonteCarloBot"]
    diverse = list(DIVERSE_BOT_FACTORIES.keys())
    return original + diverse
