"""Unit test for policies/base.py: `hold` is an ordinary, loggable Intent.

Run alone: `uv run pytest tests/unit/test_policy_base.py -v`.
"""

from luminary_agent.policies.base import hold


def test_hold_is_a_first_class_intent() -> None:
    intent = hold(valid_until_s=5.0)
    assert intent.kind == "hold"
    assert intent.params == {}
    assert intent.valid_until_s == 5.0
