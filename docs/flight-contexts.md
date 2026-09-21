# Flight contexts: what varies, what it looks like, what has to be decided

The scenario taxonomy of `APOLLO_AGENT_PLAN.md` §2, turned into the spec the scenario generator
and the agent's decision space are held to (Phase 2 / **Gate 2**). One row per failure mode:
what the crew or the agent *sees*, what must be decided, how long there is to decide it, where
the claim comes from, and whether this repo models it yet.

## How to read the citations

| Tag | Meaning |
|---|---|
| **[rope]** | Verified inside this repository's pinned `external/virtualagc` checkout. `file:line` — re-checkable with `grep` at any time. These are ground truth: the flight software says so. |
| **[doc]** | A published source, named but **not yet checked against the document itself**. Treat as a lead, not as evidence, until someone opens it and replaces this tag with a page or section number. |
| **[measured]** | Measured in this repo, in a run whose log is kept. The number is ours, not history's. |

Gate 2 asks that *every scenario knob traces to a cited real occurrence*. The **[rope]** and
**[measured]** rows meet that now. The **[doc]** rows do not yet: verifying them against NTRS and
the Apollo Flight Journal is the remaining Phase 2 work, and the gate is not passed until they
carry a locator. Nothing here should be described as "sourced" while it still reads **[doc]**.

---

## 2.1 Initial-condition dispersions

| Mode | Signature | Decision | Time | Source | Status in repo |
|---|---|---|---|---|---|
| State-vector error at PDI (position/velocity) | Nothing at all until late: the AGC gets no radar update, so it flies its belief. It shows up as a growing disagreement between the AGC's altitude (DSKY N63/N64 R3) and the landing radar. | Believe the radar or the computer; take over or let it fly | Minutes, then seconds | **[measured]** ~700 m of downrange error per m/s of radial velocity error; 0.32 m/s made Luminary hover at 406 m until propellant ran out, 1 m/s crashed 850 m short | `scenarios/dispersions.py` (`dh0_m`, `dvt0_ms`, `dvh0_ms`), all three tiers |
| Out-of-plane error | Cross-range component in the AGC's own thrust command (`UNFC/2`) | None directly (guidance closes it) — but the plant must be able to express it | Whole descent | **[measured]** a planar plant that drops the component makes Luminary wind up and abort (alarm 1410) | Modelled: `sim/loop.py` lateral channel |
| Ignition-time offset | `TIG` differs from the flight plan; `IGNALG` converges elsewhere | Accept or recycle | Pre-ignition | **[rope]** `IGNALG`'s time search, `THE_LUNAR_LANDING.agc` | Scenario-supplied `TLAND`; not dispersed |
| Mass / CG uncertainty | AGC's `MASS` disagrees with the true vehicle; guidance closes on acceleration so it scales | Nothing immediate; it eats margin | Whole descent | **[measured]** AGC `MASS` is a 6,804 kg pad load against a true ~8,100 kg in our runs | `dispersions.py` `mass_scale`; CG not modelled (no attitude dynamics) |

## 2.2 Propulsion and vehicle

| Mode | Signature | Decision | Time | Source | Status |
|---|---|---|---|---|---|
| **Fuel margin** — the one that decides missions | Propellant remaining against time to touchdown | Press on, or abort while ascent is still possible | Tens of seconds | **[doc]** Apollo 11 touched down with ≈25 s of usable descent propellant remaining (Apollo 11 Mission Report; AFJ descent commentary) | `dispersions.py` `propellant_scale` (up to −2 % / −8 % / −16 % by tier); engine cuts off when usable propellant is gone |
| Descent-engine thrust degradation | Vehicle falls behind the AGC's expected profile; throttle sits high | Accept, or take over and fly the remaining margin | Minutes | **[doc]** DPS performance dispersions, Apollo LM DPS specification / mission reports | `dispersions.py` `thrust_scale` (±0.5 / 1.5 / 3 % by tier) plus an in-flight loss (`thrust_fault_*`, up to 6 % at tier 2 and 15 % at tier 3, drawn inside the approach phase). A stuck throttle is **not** modelled |
| Throttle response lag, Isp variation | Slower than commanded throttle tracking | Usually none | — | **[rope]** throttle is a counted DAC, `agc/actuators.py` / `plant/throttle.py` | Actuator modelled; lag and Isp dispersion not |
| RCS jet stuck-on / failed-off, slosh | Attitude wanders against command | Take manual attitude, or abort | Seconds | **[rope]** jet channels 5/6, `INPUT_OUTPUT_CHANNEL_BIT_DESCRIPTIONS.agc` | **Blocked**: no attitude dynamics (perfect pointing), so no attitude failure can be expressed |

## 2.3 Navigation and sensors

| Mode | Signature | Decision | Time | Source | Status |
|---|---|---|---|---|---|
| Landing-radar late lock-on or dropout | Radar altitude simply absent; only the AGC's number remains | Continue on the computer's belief, or take over | Tens of seconds | **[doc]** LR lock-on behaviour, Apollo 11–15 mission reports; **[rope]** LR antenna position discrete `ch33` bit 6 | `plant/radar.py`: tier-3 dead band of 150–250 m somewhere in 100–400 m |
| **LR-vs-computer altitude discrepancy** | Two altitudes on screen that disagree — in a tier-3 episode Luminary reads 180–380 m high throughout | Accept the radar update, or reject it | Seconds | **[doc]** the Apollo 11 crew accepted a large LR/computer discrepancy during P63 (AFJ descent transcript) | Observable (`Observation.radar_altitude_m` vs `agc_altitude_m`). **Simplification to state**: the radar does *not* feed the AGC (yaAGC's socket build has no radar path), so "accept the update" is not yet an action, only a belief |
| IMU bias and drift | Slow divergence of the AGC's state from truth | Same as a state-vector error | Whole descent | **[rope]** PIPA pulse weight from `KPIP1`, `CONTROLLED_CONSTANTS.agc` | PIPA model exists; bias/drift not dispersed |
| Gimbal-lock proximity | Alarm 0401 | Manoeuvre away, or ignore | Seconds | **[rope]** alarm 0401 is Luminary's own attitude arithmetic | Raised in our runs and recorded as non-fatal — our perfectly-pointed plant has no gimbals, so it is an artefact here, not a decision |
| Stale state vector needing an uplink | — | Accept an uplinked update | Pre-ignition | **[rope]** the V71/V72 (P27) path, used for every load in `agc/loads.py` | Modelled as the *setup* path, not as an in-flight event |

## 2.4 Guidance computer

| Mode | Signature | Decision | Time | Source | Status |
|---|---|---|---|---|---|
| **Executive overflow: 1201 (no VAC areas) / 1202 (no core sets)** | Program alarm light, PROG display, the DSKY drops out and comes back | Go / no-go, within seconds, while the vehicle keeps descending | ~10 s | **[rope]** both codes are in the rope: `EXECUTIVE.agc:152` (`OCT 1201 # NO VAC AREAS`) and `EXECUTIVE.agc:213` (`OCT 1202`); **[doc]** Apollo 11's 1201/1202 storm, caused by the rendezvous radar stealing cycles (Apollo 11 Mission Report; Eyles, *Tales from the Lunar Module Guidance Computer*) | **Not yet inducible.** The canonical agent decision, and the highest-value scenario axis left. Inducing it means loading the executive artificially (spurious interrupt traffic or a competing job), not patching a display |
| Restart / phase-table failure (1107) | Alarm at power-up | Fresh start (`V36E`) | Pre-ignition | **[measured]** raised by every cold boot here, before any of our I/O | Handled in setup (`SteppedDsky.fresh_start`); not a scenario |
| Guidance overflow 1410, "ignition algorithm not converging" 1412, bad root 1406 | Alarm, then Luminary abandons the landing programs | Abort or take over | Seconds | **[measured]** all three produced and diagnosed here (see the plan's Phase 1 ledger) | Recorded as non-fatal; abort detected by Luminary leaving P63–P67 |

## 2.5 Terrain and landing site

| Mode | Signature | Decision | Time | Source | Status |
|---|---|---|---|---|---|
| Boulder field or crater at the target | Visible out of the window; nothing on the DSKY | Redesignate (LPD), or take manual control and fly over it | ~30 s in P64 | **[doc]** Apollo 11's manual takeover and fly-over to a clear area (AFJ/ALSJ descent transcript); *seeded craters and boulders now exist* (`plant/terrain.py`), are scored (`mission_success`) and reported to the agent below 500 m (`Observation.hazards_near`); the agent can steer away with `command(horizontal_ms)`, but the *LPD redesignation* below is still blocked; **[rope]** the LPD path exists: `N64` is "TIME LEFT FOR REDESIGNATION — LPD ANGLE" (`ASSEMBLY_AND_OPERATION_INFORMATION.agc:421`) and channel 16 carries elevation/azimuth redesignation (`INPUT_OUTPUT_CHANNEL_BIT_DESCRIPTIONS.agc:174,179`) | **Blocked**: redesignation and P66 arrive through MARKRUPT on channel 16, for which yaAGC's socket build raises no interrupt; P66's law also needs `RODSCALE`, `LAG/TAU`, `MAXFORCE`, `MINFORCE` (`ERASABLE_ASSIGNMENTS.agc:1407-1409`), whose Apollo 11 values are in no source in the pinned repo |
| Dust obscuration below ~30 m | Surface disappears; horizontal rate cues are lost | Commit to the descent rate and land blind, or abort | Seconds | **[doc]** severe on Apollo 12 and 15 (mission reports, crew debriefings) | Not modelled. Would be a *sensor* failure (lose the horizontal-rate cue) rather than terrain |
| Surface slope | Tilt at touchdown | Choose where to put it down | Seconds | **[doc]** landing criteria: ≤ 12° tilt on ≤ 6° slope | Modelled as data (`plant/terrain.py`): seeded relief and slope under the LM, scored against the 12° limit; visible to the agent below 500 m (`Observation.slope_here_deg`). Contact physics is still a flat plane |
| Mascon-driven downrange error | Landing long | Redesignate or accept | Minutes | **[doc]** Apollo 11 landed several km downrange, partly attributed to mascons | Not modelled as a gravity anomaly; the *symptom* (downrange error) is produced by the state-vector dispersions |

## 2.6 Mission phase and mode

| Transition | Signature | Decision | Source | Status |
|---|---|---|---|---|
| P63 braking → P64 approach | Automatic phase switch; the DSKY nouns change | None required; it is the cue that the approach has begun | **[rope]** `LUNAR_LANDING_GUIDANCE_EQUATIONS.agc`; **[measured]** at t = 577 s in our nominal run | Observable, used by `ScriptedAgent` |
| P64 → P66 (rate of descent) | Crew ROD clicks | When to take the descent rate | **[rope]** `RODCOUNT`, `RODSCALE` (`ERASABLE_ASSIGNMENTS.agc:1407`) | **Blocked** (no MARKRUPT path, missing pad loads) |
| Auto → P67 manual | AUTO THROTTLE discrete clears; Luminary's R13 monitor selects P67 and stops commanding thrust | **When to take over** — the live decision in this repo | **[rope]** `GUILDENSTERN`; **[measured]** verified: `MODREG` = 103, AGC stops commanding thrust | Modelled: `Intent.take_manual`, `sim/executor.py` |
| Abort / abort-stage | — | The irreversible one | **[rope]** abort programs exist in the rope | **Blocked**: no ascent stage in the plant, so abort cannot be scored |

## 2.7 Vehicle configuration

J-mission LMs (15–17) were heavier, carried the rover and flew a steeper descent to harder sites
— **[doc]** (mission reports). Not modelled: one vehicle configuration here. It is a mass/target
change, not new software, so it is cheap to add once the scenario axes above are exhausted.

## 2.8 Communications and external authority

Loss of signal, delayed Mission Control calls, no uplink — **[doc]**. Not modelled. It matters
for the agent because it decides whether a decision may be deferred; with no Mission Control in
this environment, the agent always owns the decision. Say so in any result.

## 2.9 The decision space this actually leaves

Available to an agent today: **take manual control** (irreversible), **commit to a descent rate
and a horizontal target**, **hold**. Everything else in §2.9 — go/no-go on a program alarm,
accept/reject a radar update, LPD redesignation, P64→P66, abort — is either blocked by the
emulator (no MARKRUPT interrupt, no radar path), missing sourced pad loads, or missing plant
(no ascent stage, no attitude dynamics).

That is the honest state of the decision space, and it caps what a first LLM run can demonstrate:
**when to take over, and how to fly it down**. The two axes that would widen it most, in order of
value per unit of work:

1. **1201/1202 induction** — canonical, in-rope, needs no new plant.
2. **Engine degradation / fuel starvation severe enough to force an early takeover** — needs no
   new actuation at all, only a wider dispersion range.
