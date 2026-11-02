"""Record builders shared by the viz tests: what the recorder writes, minimally.

Not a test file itself (no `test_` prefix, so pytest does not collect it). `tick(**over)` and
`decision(kind)` return dicts shaped like sim/loop.py and sim/descent.py log records; keyword
arguments override any field, e.g. `tick(t=5.0, h_m=100.0)`.
"""

from luminary_agent.plant.propulsion import F_MAX_N


def tick(t: float = 10.0, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "t": t, "h_m": 500.0, "x_m": 1_000.0, "z_m": 30.0, "hdot_ms": -5.0, "vt_ms": 4.6,
        "mass_kg": 7_500.0, "thrust_n": F_MAX_N / 2, "pitch_deg": 12.0, "mode": "auto",
        "dsky": {"prog": 64, "verb": 6, "noun": 64, "r1": 1, "r2": None, "r3": -3},
        "engine_on": True,
    }  # fmt: skip
    return base | over


def decision(kind: str = "hold", veto: bool = False) -> dict[str, object]:
    return {
        "t": 9.0, "obs": {"alarms": [1201], "radar_altitude_m": 498.0, "agc_altitude_m": 510.0},
        "intent": {"kind": kind, "params": {"descent_rate_ms": -1.0} if kind == "command" else {}},
        "applied": "ok", "reason": "heartbeat", **({"veto": True} if veto else {}),
    }  # fmt: skip
