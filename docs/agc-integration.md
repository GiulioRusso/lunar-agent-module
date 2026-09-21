# AGC ↔ plant integration: units, signs, scaling, channel

What crosses the boundary between the real Luminary 099 rope (running in yaAGC) and the Python
plant, one row per signal. Source of truth is the code named in each row; every row names the unit
test that pins it analytically and the integration test that pins it against a real yaAGC.
Integration tests need `127.0.0.1` sockets: `uv run pytest tests/integration -q`.

## Plant → AGC (sensors and discretes)

| Signal | AGC address | Unit / scale | Sign / frame | Code | Unit test | Integration test |
|---|---|---|---|---|---|---|
| PIPA X/Y/Z (accelerometer) | counter regs `0o37/0o40/0o41` via `0x80 \| reg`, `PINC`/`MINC` | 1 pulse = 0.01 m/s (`KPIP1`: 2⁻¹⁴·.0128·2⁷ m/cs); fractional remainder carried | specific force in stable-member axes, ones' complement counter | `plant/sensors.py`, `agc/registers.py` | `test_sensors.py`, `test_registers.py` | `test_pipa_pulses_against_real_yaagc.py` |
| CDU X/Y/Z (gimbal angles) | counter regs `0o32/0o33/0o34`, `PCDU`/`MCDU` (fast: `0o21/0o23`) | 1 pulse = 360/32768° (2¹⁵ per rev); THETAD in the same counts | 2's-complement mod 2¹⁵; seeded at the burn attitude (P63 R60LEM becomes a no-op) | `agc/cdu.py`, `plant/sensors.py` | `test_cdu.py`, `test_sensors.py` | `test_coredump_against_real_yaagc.py` |
| Hardware discretes | input channels `0o30`–`0o33` | bit flags, **inverted as sensed** (0 = present) | see `plant/discretes.py` for the named bits (IMU operate, LGC control, ATT HOLD/AUTO, LR position/data-good) | `plant/discretes.py` | `test_discretes.py` | `test_discretes_against_real_yaagc.py` |
| State vector / pad loads | erasable via uplink (P27) | DP, B-scaled (m B-27, m/cs B-5, cs B-28) | lunar-sphere inertial | `agc/state_vector.py`, `agc/scaling.py`, `agc/padloads.py`, `agc/uplink.py` | `test_state_vector.py`, `test_scaling.py`, `test_padloads.py`, `test_uplink_validation.py` | `test_state_vector_p27.py`, `test_padloads_p27.py`, `test_uplink_p27.py` |
| DSKY keys | input channel `0o15` | keycode (`agc/dsky.py:KEYCODE`) | – | `agc/dsky.py`, `agc/stepped_dsky.py` | `test_dsky.py` | `test_stepped_mode.py` |
| **Landing radar** | **none** | – | – | `plant/radar.py` | `test_radar.py` | – |

**Radar boundary (deliberate).** yaAGC's socket build has no radar data path. Radar altitude
(bias, noise, dropout band) reaches the *observation* only, so the AGC keeps flying its belief
and the agent/crew must decide which to trust. There is no `RNRAD` write; do not describe
Luminary as "using" the radar in this simulator.

## AGC → plant (actuators and readouts)

| Signal | AGC address | Unit / scale | Sign / semantics | Code | Unit test | Integration test |
|---|---|---|---|---|---|---|
| Engine ON/OFF | output channel `0o11` bits 13/14 | momentary relay pulses | ON sets, OFF clears | `agc/actuators.py` | `test_actuators.py` | `test_gate0_mission_timer.py` |
| Throttle command | `THRUST` erasable (increment `PIF = FC − FP`) + strobe channel `0o14` bit 4 | counts; 1 count = 12.533 N; slew `FRATE` 32 counts/cs; clamp min throttle … `FMAX` | an *increment*, not a level; accumulated as pending command, rate-limited | `plant/throttle.py`, `sim/loop.py` | `test_throttle.py`, `test_loop_throttle.py`, `test_propulsion.py` | `test_sim_loop_coasting.py` |
| Thrust direction | `UNFC/2` (core dump) | unit vector, stable-member frame | rotated to the lunar frame by `plant/lunar_orientation.py` | `sim/loop.py`, `agc/guidance.py`, `plant/lunar_orientation.py` | `test_lunar_orientation.py`, `test_dynamics.py` | `test_sim_loop_coasting.py` |
| RCS jets | output channels `0o5` (pitch), `0o6` (roll) | raw 8-bit jet patterns | **logged only**, not mapped to torque | `agc/actuators.py` | `test_actuators.py` | – |
| DSKY display | output channel `0o10` | 7-segment words `AAAABCCCCCDDDDD` | decoded to verb/noun/R1–R3, alarms | `agc/dsky.py` | `test_dsky.py` | `test_stepped_mode.py` |
| Guidance readouts (altitude, program, alarms) | core dump (`COREDUMP`) via `agc/symbols.py` (addresses from the yaYUL listing, never hard-coded) | see `agc/coredump.py` | erasable banks, ones' complement | `agc/coredump.py`, `agc/symbols.py` | `test_coredump.py`, `test_symbols.py` | `test_coredump_against_real_yaagc.py` |

## Plant model and MVP boundary (decided)

- **3-DoF**: planar (down-range/altitude) plus a lateral channel driven by Luminary's own thrust
  command; commanded pitch, no attitude dynamics. Mass flow, gravity, rotating surface, DPS,
  incremental throttle are modelled.
- **Out of scope until frame/attitude tests exist**: 6-DoF, RCS torque, jet-to-axis mapping,
  abort, P66/LPD, RCS failure, 1201/1202. They are separate capabilities, not S1 leftovers.
- **Time**: stepped clock (`sim/clock.py`); the AGC only executes when the loop steps it, and the
  free-run yaAGC patch removes host-side pacing only (TIME1/TIME2 come from counter interrupts).
- **Scoring**: `soft_touchdown` is computed; `mission_success` stays `not_scored` until the surface
  model (S2) exposes target, hazard and slope.
