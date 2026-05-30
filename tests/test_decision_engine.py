"""Tests for decision_engine — end-to-end decision making."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.decision_engine import DecisionEngine


def _make_table(
    hole: list[str],
    board: list[str],
    street: str = "Preflop",
    pot: int = 3,
    call_chips: int = 0,
    seat_num: int = 4,
    n_players: int = 6,
    stack: int = 200,
    big_blind: int = 2,
    can_check: bool = True,
    can_bet: bool = True,
    can_raise: bool = False,
    can_call: bool = True,
    can_fold: bool = True,
) -> dict:
    """Helper to create Arena-style table dicts for testing."""
    seats = []
    for i in range(n_players):
        sn = i + 1
        seats.append({
            "seatNumber": sn,
            "agentId": f"test_agent_{sn}",
            "agentHandle": "hero" if sn == seat_num else f"bot_{sn}",
            "holeCards": hole if sn == seat_num else [],
            "stackChips": stack if sn == seat_num else 200,
        })

    available = []
    if can_fold:
        available.append("fold")
    if can_check and call_chips == 0:
        available.append("check")
    if can_call and call_chips > 0:
        available.append("call")
    if can_bet and call_chips == 0:
        available.append("bet")
    if can_raise and call_chips > 0:
        available.append("raise")

    return {
        "tableId": "test_table_001",
        "potChips": pot,
        "street": street,
        "boardCards": board,
        "selfSeatNumber": seat_num,
        "bigBlindChips": big_blind,
        "smallBlindChips": big_blind // 2,
        "seats": seats,
        "allowedActions": {
            "availableActions": available,
            "callChips": call_chips,
            "callToAmount": call_chips,
            "canCheck": can_check and call_chips == 0,
            "canBet": can_bet and call_chips == 0,
            "canRaise": can_raise and call_chips > 0,
            "canFold": can_fold,
            "betRange": {"min": 2, "max": 200},
            "raiseRange": {"min": 4, "max": 200},
        },
        "actionDeadlineAt": 9999999999999,
    }


def test_preflop_open_premium():
    engine = DecisionEngine()
    table = _make_table(
        ["As", "Ad"], [], "Preflop", pot=3, call_chips=0,
        seat_num=4, can_bet=True, can_raise=False,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert result["action"] in ("raise", "bet", "all-in"), \
        f"Expected raise/bet/all-in with AA, got {result['action']}"


def test_preflop_open_weak_utg():
    engine = DecisionEngine()
    table = _make_table(
        ["7h", "2s"], [], "Preflop", pot=3, call_chips=0,
        seat_num=4, can_bet=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert result["action"] in ("fold", "check"), \
        f"Expected fold/check with 72o UTG, got {result['action']}"


def test_preflop_3bet_spot():
    engine = DecisionEngine()
    table = _make_table(
        ["Kh", "Ks"], [], "Preflop", pot=10, call_chips=6,
        seat_num=3, can_raise=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert result["action"] in ("raise", "all-in"), \
        f"Expected 3-bet with KK, got {result['action']}"


def test_deadline_fallback():
    engine = DecisionEngine()
    table = _make_table(
        ["As", "Ad"], [], "Preflop", pot=3, call_chips=0,
    )
    result = engine.decide(table, deadline_s=1.0)
    assert result["action"] in ("check", "fold"), \
        f"Expected safe action under deadline, got {result['action']}"


def test_action_format():
    engine = DecisionEngine()
    table = _make_table(
        ["As", "Ks"], [], "Preflop", pot=3, call_chips=0,
        can_bet=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert "action" in result
    assert result["action"] in ("fold", "check", "call", "bet", "raise", "all-in")
    assert "message" in result
    assert "reasoning" in result
    assert len(result["reasoning"]) <= 150, \
        f"Reasoning too long: {len(result['reasoning'])} chars"


def test_flop_decision_basic():
    engine = DecisionEngine()
    # Hero has top pair on dry flop
    table = _make_table(
        ["As", "Kh"], ["Ah", "7d", "2c"], "Flop",
        pot=10, call_chips=0, can_bet=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert result["action"] in ("bet", "check"), \
        f"Expected bet or check with top pair, got {result['action']}"


def test_flop_facing_bet_with_nothing():
    engine = DecisionEngine()
    table = _make_table(
        ["Ts", "9s"], ["Ah", "Kd", "7c"], "Flop",
        pot=20, call_chips=10, can_call=True, can_fold=True, can_raise=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    # Should fold with no pair and no draw vs significant bet
    assert result["action"] != "raise", \
        f"Should not raise air on A-high flop"


def test_river_decision_with_strong_hand():
    engine = DecisionEngine()
    # Hero has set on river
    table = _make_table(
        ["Ah", "Ad"], ["As", "7d", "2c", "8h", "Qc"], "River",
        pot=50, call_chips=0, can_bet=True,
    )
    result = engine.decide(table, deadline_s=10.0)
    assert result["action"] in ("bet", "raise"), \
        f"Should value bet set on river, got {result['action']}"


if __name__ == "__main__":
    test_preflop_open_premium()
    test_preflop_open_weak_utg()
    test_preflop_3bet_spot()
    test_deadline_fallback()
    test_action_format()
    test_flop_decision_basic()
    test_flop_facing_bet_with_nothing()
    test_river_decision_with_strong_hand()
    print("All decision_engine tests passed!")
