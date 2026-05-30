"""Continuous Strategy Mixer — weighted blending of all three strategies.

Replaces hard/discrete routing with probabilistic blending:
  final_action = w1*l limp_value + w2*raise_exploit + w3*hybrid

Weights are computed dynamically per decision based on:
  - opponent pool type & classification confidence
  - position, stack depth, street
  - hand strength, pot size
  - temporal smoothing to prevent oscillation

Tasks 1-4: Mixture Model, Contextual Weights, Smooth Transitions, Aggressive Fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyVote:
    """A single strategy's preferred action."""
    action: str
    amount: Optional[int]
    confidence: float
    reasoning: str
    strategy_name: str


@dataclass
class BlendedDecision:
    """Result of blending multiple strategy votes."""
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float
    # Explainability (Task 5)
    weights_used: dict[str, float]
    votes: dict[str, str]
    blend_method: str


class StrategyMixer:
    """Continuous strategy blender with temporal smoothing.

    Computes contextual weights, runs all strategies, and blends their outputs
    via weighted voting. Maintains state to smooth transitions across hands.
    """

    def __init__(self):
        # Smoothed weights — decayed across decisions
        self._prev_weights: dict[str, float] = {
            "limp_value": 0.333, "raise_exploit": 0.333, "hybrid": 0.333
        }
        self._prev_pool_type: str = "mixed"
        self._hand_count: int = 0

    # ═══════════════════════════════════════════════════════════════
    # Task 2: Contextual Weight Generator
    # ═══════════════════════════════════════════════════════════════

    def compute_weights(
        self,
        pool_type: str,
        confidence: float,
        position: str,
        stack_depth_bb: float,
        hand_strength: float,
        street: str,
        pot_to_stack: float = 0.1,
        table_aggression: float = 0.5,
    ) -> dict[str, float]:
        """Compute raw (pre-smoothing) strategy weights from game context.

        Args:
            pool_type: 'passive', 'aggressive', or 'mixed'
            confidence: classifier confidence [0.0-1.0]
            position: seat position string (BTN, BB, SB, etc.)
            stack_depth_bb: effective stack in big blinds
            hand_strength: 0.0-1.0 hand strength estimate
            street: 'Preflop', 'Flop', 'Turn', 'River'
            pot_to_stack: pot size / effective stack
            table_aggression: estimated 0.0-1.0 aggression at table

        Returns:
            dict with keys limp_value, raise_exploit, hybrid — sums to 1.0
        """
        # ── Base weights from pool type ──────────────────────────
        if pool_type == "passive":
            w = {"limp_value": 0.55, "raise_exploit": 0.15, "hybrid": 0.30}
        elif pool_type == "aggressive":
            w = {"limp_value": 0.30, "raise_exploit": 0.45, "hybrid": 0.25}
        else:  # mixed
            w = {"limp_value": 0.33, "raise_exploit": 0.33, "hybrid": 0.34}

        # ── Confidence scaling (Task 3) ──────────────────────────
        # Low confidence → push toward hybrid (safe fallback)
        if confidence < 0.7:
            hybrid_boost = (0.7 - confidence) * 0.60
            w["hybrid"] = min(0.70, w["hybrid"] + hybrid_boost)
            drain = hybrid_boost / 2.0
            w["limp_value"] = max(0.05, w["limp_value"] - drain)
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - drain)

        # ── Position adjustment ──────────────────────────────────
        if position == "BTN":
            w["raise_exploit"] += 0.06
            w["limp_value"] = max(0.05, w["limp_value"] - 0.06)
        elif position == "BB":
            w["limp_value"] += 0.05
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - 0.05)
        # SB is in between — small tilt toward limp
        elif position == "SB":
            w["limp_value"] += 0.03
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - 0.03)

        # ── Stack depth ──────────────────────────────────────────
        if stack_depth_bb < 25:  # Shallow — favor raise/fold
            w["raise_exploit"] += 0.08
            w["limp_value"] = max(0.05, w["limp_value"] - 0.05)
            w["hybrid"] = max(0.05, w["hybrid"] - 0.03)
        elif stack_depth_bb > 80:  # Deep — exploit with cheap flops
            w["limp_value"] += 0.05
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - 0.05)

        # ── Hand strength ────────────────────────────────────────
        if hand_strength > 0.70:  # Premium — build pot
            w["raise_exploit"] += 0.08
            w["limp_value"] = max(0.05, w["limp_value"] - 0.05)
            w["hybrid"] = max(0.05, w["hybrid"] - 0.03)
        elif hand_strength < 0.35:  # Weak — fold or see cheap
            w["limp_value"] += 0.08
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - 0.08)

        # ── Street adjustment ────────────────────────────────────
        if street == "River":
            # River: more polarized — value or fold, less call
            w["hybrid"] += 0.04
            w["limp_value"] = max(0.05, w["limp_value"] - 0.02)
            w["raise_exploit"] = max(0.05, w["raise_exploit"] - 0.02)
        elif street == "Preflop":
            # Preflop: allow more variation
            pass

        # ── Pot-to-stack ratio ───────────────────────────────────
        if pot_to_stack > 0.5:  # Large pot relative to stack
            w["raise_exploit"] += 0.05
            w["limp_value"] = max(0.05, w["limp_value"] - 0.05)

        # ── Normalize to sum 1.0 ─────────────────────────────────
        total = w["limp_value"] + w["raise_exploit"] + w["hybrid"]
        if total <= 0:
            return {"limp_value": 0.333, "raise_exploit": 0.333, "hybrid": 0.334}
        w = {k: v / total for k, v in w.items()}

        # ── Clamp to valid range ─────────────────────────────────
        for k in w:
            w[k] = max(0.05, min(0.85, w[k]))

        # Re-normalize after clamp
        total = sum(w.values())
        return {k: v / total for k, v in w.items()}

    # ═══════════════════════════════════════════════════════════════
    # Task 3: Smooth Transition Logic
    # ═══════════════════════════════════════════════════════════════

    def smooth_weights(
        self,
        raw_weights: dict[str, float],
        pool_type: str,
        confidence: float,
    ) -> dict[str, float]:
        """Apply exponential moving average to prevent hard switches.

        When confidence is low or pool type changes, transitions are slower.
        """
        # Alpha: how fast we adapt to new weights
        # Higher = faster adaptation
        if self._hand_count < 5:
            alpha = 0.6  # Fast initial convergence
        elif pool_type != self._prev_pool_type:
            alpha = 0.45  # Quick but not instant on pool change
        elif confidence < 0.6:
            alpha = 0.15  # Slow when uncertain
        else:
            alpha = 0.30  # Normal rate

        smoothed = {}
        for k in ["limp_value", "raise_exploit", "hybrid"]:
            prev = self._prev_weights.get(k, 0.333)
            raw = raw_weights.get(k, 0.333)
            smoothed[k] = alpha * raw + (1.0 - alpha) * prev

        # Normalize
        total = sum(smoothed.values())
        smoothed = {k: v / total for k, v in smoothed.items()}

        # Update state
        self._prev_weights = dict(smoothed)
        self._prev_pool_type = pool_type
        self._hand_count += 1

        return smoothed

    # ═══════════════════════════════════════════════════════════════
    # Task 1: Strategy Mixture Model — Action Blending
    # ═══════════════════════════════════════════════════════════════

    def blend(
        self,
        votes: list[StrategyVote],
        weights: dict[str, float],
    ) -> BlendedDecision:
        """Blend multiple strategy votes into a single action via weighted voting.

        Each strategy's vote carries weight; the action with highest total
        weight wins. For bet/raise actions, sizing is a weighted average
        of all strategies that voted for a bet/raise action.
        """
        # Aggregate votes by action category
        action_weights: dict[str, float] = {}
        action_details: dict[str, list[tuple[float, Optional[int], str, float]]] = {}

        for vote in votes:
            w = weights.get(vote.strategy_name, 0.33)
            act = vote.action
            action_weights[act] = action_weights.get(act, 0.0) + w

            if act not in action_details:
                action_details[act] = []
            action_details[act].append((w, vote.amount, vote.reasoning, vote.confidence))

        # Pick winning action (highest total weight)
        if not action_weights:
            return BlendedDecision(
                action="fold", amount=None,
                reasoning="no votes", confidence=0.0,
                weights_used=weights,
                votes={v.strategy_name: v.action for v in votes},
                blend_method="fallback",
            )

        best_action = max(action_weights, key=action_weights.get)
        best_weight = action_weights[best_action]
        total_weight = sum(action_weights.values())

        blend_method = "majority" if best_weight > 0.5 else "plurality"

        # Compute amount (for bet/raise)
        amount = None
        if best_action in ("bet", "raise"):
            # Weighted average of amounts from strategies that voted for bet/raise/call
            # (only use strategies that specified an amount)
            sized = [(w, amt) for w, amt, _, _ in action_details[best_action] if amt is not None]
            if sized:
                total_sized_w = sum(w for w, _ in sized)
                if total_sized_w > 0:
                    amount = int(sum(w * amt for w, amt in sized) / total_sized_w)

        # Build reasoning from winning votes
        best_reasoning = max(action_details[best_action], key=lambda x: x[0])[2]

        # Confidence: weighted average of strategy confidences
        avg_confidence = sum(
            sw * conf for act, details in action_details.items()
            for sw, _, _, conf in details
        ) / max(total_weight, 0.001)
        avg_confidence = min(1.0, avg_confidence)

        # Build votes summary for explainability
        votes_summary = {v.strategy_name: v.action for v in votes}

        return BlendedDecision(
            action=best_action,
            amount=amount,
            reasoning=best_reasoning,
            confidence=avg_confidence,
            weights_used=weights,
            votes=votes_summary,
            blend_method=blend_method,
        )

    def get_state(self) -> dict:
        """Return current mixer state for logging/debugging."""
        return {
            "smoothed_weights": dict(self._prev_weights),
            "pool_type": self._prev_pool_type,
            "hand_count": self._hand_count,
        }
