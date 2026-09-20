# LUMINARY-AGENT — Build Plan (v3)

An LLM agent that flies the Apollo Lunar Module to the surface, closing the loop around the
**original 1969 AGC flight software** running in emulation. Fully local, no APIs, no paid services.

Target platform: MacBook Air M5, 16 GB, no discrete GPU.

**v2 changes:** split into Track A (build now, no agentic knowledge required) and Track B (the
agent, after the course); added the flight-context taxonomy (§2); demoted the agent from "the
project" to "one client of the environment".

**v3 changes:** the simulation is **pausable** — plant *and* AGC — so the agent actually flies the
vehicle instead of racing it (§3.1); realtime stays as a second mode and the gap between them
becomes a headline result rather than a lost claim (§0.3, Phase 6). Added record/replay of episodes
at true speed (§3.2), and promoted "see where the LM is and where the ground is" to Phase 1b via a
cheap 2D terrain profile, with a stated visual style (§3.3). Full 3D remains Phase 5.

---

## 0. Honest framing before you start

Five things must be true or the project fails.

1. **The hard part is not the agent. It is closing the loop around yaAGC.**
   Virtual AGC states explicitly that it is not a lunar-lander simulator and not a behavioural
   simulation of the LM — it is a CPU emulator plus peripherals, intended as a *component* of such
   a simulation. Nobody hands you a physics plant. You write it. Luminary expects PIPA
   accelerometer pulse increments, CDU gimbal angles and landing-radar words; it emits jet
   commands and a throttle DAC value. Budget **50–60% of total project time here**.

2. **The agent is ~2 weeks of a 12-week project.** Everything else — emulator, plant, sensors,
   scenarios, eval harness, visualisation — is ordinary engineering that needs zero agentic
   knowledge. This is why you can start today and let the course run in parallel.

3. **An LLM cannot be in the inner control loop.** The LM digital autopilot runs at tens of Hz.
   A local 8B model on an M-series Air gives roughly 0.5–3 s per structured decision. So the
   architecture is necessarily **hierarchical**: the LLM is the flight director / crew, issuing
   mode changes, target redesignations, abort decisions and DSKY entries at 0.2–1 Hz or on events;
   deterministic code holds the fast loop. Any plan where the LLM outputs thrust at 20 Hz fails.

   **Amended (v3): the wall-clock half of this is a choice, not a law.** The whole simulation —
   plant *and* AGC — can be paused while the agent thinks, and resumed with no time skip (§3.1).
   That removes the latency penalty entirely and lets the agent genuinely fly the vehicle instead
   of watching it fall past. What does *not* change is the authority split: the AGC's DAP really
   does run at tens of Hz and decisions cannot be injected mid-tick, so the hierarchy survives —
   its justification just moves from "the model is too slow" to "the computer owns the fast loop".
   Run both modes and report the difference (§3.1, Phase 6); the gap between them *is* the
   measurement of what real-time pressure costs an 8B model.

4. **Original code + local physics is the whole novelty.** Reimplementing Klumpp's guidance in
   Python and calling it "Apollo" is a toy. Running the Luminary 099 core rope and having an agent
   negotiate with it through the actual I/O channels is not. Protect that property.

5. **Have a declared fallback.** If the AGC loop has not closed by its gate date, you drop to a
   Python reimplementation of the P63/P64/P66 guidance law and keep everything else intact.
   Decide this in advance, in writing.

---

## 1. Track A / Track B — what to build now

**Reframe the deliverable.** The primary artifact is not the agent. It is a *lunar descent
benchmark environment* with the real AGC in the loop, plus a set of baseline policies and an
evaluation harness. The LLM agent is one policy among several that plug into it.

This reframing does three things: it lets you build for 8–10 weeks without knowing any agentic
AI; it means the project is a portfolio piece even if the agent underperforms (a hard,
historically grounded, fully local RL/agent benchmark is itself worth showing); and it forces the
clean interfaces that make the agent easy to drop in later.

### Track A — start immediately, no agentic knowledge required

| Order | Work | Why now |
|---|---|---|
| A1 | Emulator: build `yaYUL` + `yaAGC`, assemble Luminary 099, Python channel client, programmatic DSKY | Highest technical risk in the project. Fail here early, not in week 8. |
| A2 | Plant: 3-DoF → 6-DoF dynamics, DPS/RCS, IMU (PIPA/CDU), landing radar | The other half of the risk. Nothing downstream exists without it. |
| A3 | Debug viewer: Rerun time-series + 2D trajectory | This is a *debugging tool*, not decoration. You cannot distinguish an integrator bug from an IMU sign error from a wrong channel bit without it. (Defer the polished 3D/DSKY replay — that one *is* decoration until the physics works.) |
| A4 | Domain research: the flight-context taxonomy (§2) | Answers "what could change". Feeds A5 directly. Reuse the Apollo/NTRS RAG work rather than starting a new corpus — extracting a structured failure taxonomy is a better use of it than free-form Q&A, and the taxonomy becomes a repo document. |
| A5 | Scenario generator + frozen eval set | Defines the problem the agent solves. Must exist before the agent. |
| A6 | Baselines: null (pure Luminary), scripted Apollo 11 timeline, PID/MPC on the ROD channel | Gives you something to beat and a fallback policy for graceful degradation. |
| A7 | Eval harness: metrics, parallel runner, report generation | Same reason. Also the thing that turns a demo into a result. |
| A8 | **Define the `Agent` protocol and the tool schemas now, as stubs** | So course material plugs into a fixed interface instead of reshaping the codebase. |

### Track B — after/alongside the course

Phase 4 only: planner/executor split, tool calling, blackboard summariser, safety monitor with
veto, memory, reflection, self-consistency, then the ablations. See §5.

**What to bring back from the course each week:** write down one pattern you learned and one line
on whether it applies here. Most will not — most agentic tooling targets long-horizon text tasks,
not a latency-constrained control loop with a veto layer. Being able to say *why* a pattern does
not apply is worth as much as implementing the ones that do.

---

## 2. What "different flight contexts" actually means

This is the axis you said you could not enumerate. Here it is, grounded in what genuinely varied
across Apollo 11–17. It becomes the spec for the scenario generator (A5) and it defines the
agent's decision space.

### 2.1 Initial-condition dispersions
State vector error at PDI (position, velocity), out-of-plane error, altitude uncertainty,
ignition-time offset, vehicle mass and centre-of-gravity uncertainty.

### 2.2 Propulsion and vehicle
Descent engine thrust degradation, throttle response lag, Isp variation, RCS jet stuck-on or
failed-off, CG offset requiring gimbal trim, propellant slosh, and the one that decides missions:
**fuel margin** — Apollo 11 touched down with roughly 25 s of usable propellant remaining.

### 2.3 Navigation and sensors
Landing-radar late lock-on or dropout (a real recurring problem), a large LR-vs-computer altitude
discrepancy that must be accepted or rejected by the crew, IMU bias and drift, gimbal-lock
proximity, a stale state vector needing an uplinked update.

### 2.4 Guidance computer
Executive-overflow program alarms — 1201/1202 on Apollo 11, caused by the rendezvous radar
stealing computer cycles. This is *the* canonical agent decision: the computer is reporting it is
overloaded, the display is dropping out, and someone has to call go or abort within seconds. It is
reproducible in Luminary, and it should be a first-class scenario.

### 2.5 Terrain and landing site
Boulder field or crater at the designated point, forcing redesignation (Apollo 11: manual takeover
into P66 and a fly-over to a clear area); surface slope; dust obscuration below ~30 m, severe on
Apollo 12 and 15; mascon gravity anomalies producing downrange error — Apollo 11 landed several km
long partly because of this. Site type varies enormously: mare flats (11), pinpoint target next to
an existing spacecraft (12, Surveyor 3), mountainous rille (15), highlands (16).

### 2.6 Mission phase and mode
P63 braking → P64 approach with landing-point designator redesignation → P66 rate-of-descent
manual → P67. Plus abort modes. "Different context" is often just "different program active with
different authority split between computer and crew".

### 2.7 Vehicle configuration
J-mission LMs (15–17) were heavier, carried the rover, used a steeper descent and targeted harder
sites. Same software family, materially different flight problem.

### 2.8 Communications and external authority
Loss of signal, delayed Mission Control go/no-go calls, uplink unavailable. Determines whether the
agent may defer a decision or must own it.

### 2.9 The resulting agent decision space
Go/no-go on program alarms · accept or reject a landing-radar update · redesignate the landing
site (LPD angle) · switch program (P64→P66) · commit to a descent rate · abort vs abort-stage ·
explicitly hold. Notice that these are all **discrete, low-rate, high-consequence** decisions —
exactly the class an LLM can plausibly handle and a PID cannot. That is the thesis of the project;
make the scenario set test it.

**Sources to mine (all free, all on NTRS or the Apollo Flight Journal):** Apollo 11 Mission Report
and its LM descent postflight analysis, the Apollo Lunar Descent Guidance technical literature
(Klumpp), the Apollo Flight Journal descent transcripts and commentary, and the Luminary source
comments themselves — the rope is annotated.

---

## 3. System architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  SCENARIO GENERATOR (seeded, YAML) — taxonomy §2                   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│  PLANT  (Python, 50 Hz fixed step)                                 │
│  6-DoF rigid body · lunar gravity · DPS thrust & mass flow         │
│  RCS jets · IMU model (PIPA pulses, CDU angles) · landing radar    │
└───────▲──────────────────────────────────────────┬─────────────────┘
        │ channel writes (jets, throttle DAC)      │ channel reads
┌───────┴──────────────────────────────────────────▼─────────────────┐
│  AGC BRIDGE (one asyncio TCP socket + debugger pipe on stdin/out)  │
└───────▲──────────────────────────────────────────┬─────────────────┘
        │                                          │
┌───────┴────────────┐              ┌──────────────▼─────────────────┐
│  yaAGC + Luminary  │              │  BLACKBOARD (flight state)     │
│  099 (unmodified)  │              │  h, ḣ, v, fuel, prog, alarms   │
└────────────────────┘              └──────────────┬─────────────────┘
                                                   │
                    ┌──────────────────────────────▼─────────────────┐
                    │  SAFETY MONITOR (deterministic, has veto)      │
                    └──────────────┬────────────────────────────────┘
                                   │
                    ┌──────────────▼────────────────────────────────┐
                    │  POLICY  ← null | scripted | PID | LLM agent  │
                    │  one fixed interface, swappable by config     │
                    └──────────────┬────────────────────────────────┘
                                   │ "thinking" → hold the clock
                    ┌──────────────▼────────────────────────────────┐
                    │  CLOCK  realtime | stepped | replay   (§3.1)  │
                    │  owns advance/pause of BOTH plant and AGC     │
                    └──────────────┬────────────────────────────────┘
                                   │
                    ┌──────────────▼────────────────────────────────┐
                    │  RECORDER → episode.jsonl + core snapshots    │
                    │  every tick, self-describing        (§3.2)    │
                    └──────────────┬────────────────────────────────┘
                                   │
                    ┌──────────────▼────────────────────────────────┐
                    │  RERUN VIEWER — profile, terrain, DSKY, trace │
                    │  live, or replaying a log at 1×     (§3.3)    │
                    └───────────────────────────────────────────────┘
```

Ports: **one connection is enough.** yaAGC opens `MAX_CLIENTS` (10) *identical* listening sockets
at `--port` … `--port+9` (`SocketAPI.c:ChannelRoutineGeneric`); every one broadcasts all channel
writes and accepts all channel writes, so "DSKY port / IMU port / ACA port" is a naming convention
of the separate GUI peripherals, not something the protocol distinguishes. (An earlier draft of this
table listed 19797/19800/19801/19802/19803 as distinct services — wrong; corrected after reading the
source.) We use `--port=19797` by LM convention; 19697+ is the CM range, do not copy CM tutorials.

**Second channel: the debugger pipe.** In `stepped` mode yaAGC is launched *without* `--nodebug`, and
its stdin/stdout are ours. That pipe carries `STEP <octal n>`, `COREDUMP <file>` and nothing else we
need; the pause point it creates is also where we read state the socket cannot show (§3.1). Its
prompt output includes the flight-software source line the AGC stopped at
(`ADVAN () at EXECUTIVE.agc:475`) — free "what is Luminary doing right now" context for the viewer.

### 3.1 Clock modes — pausing the whole simulation

The plant is ours and trivially pausable. The question was whether **yaAGC** can be held too, since
it drives itself off wall-clock (`SimManageTime` computes `DesiredCycles` from `times()`), and a
naive `SIGSTOP`/`SIGCONT` would make it *fast-forward* on resume — burning through every missed
cycle at max speed while the plant stood still. That would silently desynchronise the two.

**It can be held cleanly, and the mechanism is the one yaAGC already supports.** In debug mode,
`DbgHasBreakEvent` → `DbgExecute` blocks on stdin at the `(agc)` prompt, and the *first thing it
does on receiving a command* is call `SimUpdateTime()`, which slides `RealTimeOffset` forward by
however long it was blocked — cancelling the catch-up exactly. That function exists for no other
reason; the debugger is the only caller. So:

| Mode | How | What it's for |
|---|---|---|
| **realtime** | `--nodebug`, AGC free-runs, agent races the clock; late decisions land late | The honest, hard condition. The headline result. |
| **stepped** | debugger `STEP <n>` (**n is octal**): AGC runs *n* instructions, stops, blocks at the prompt until we send the next command. Sim-time advances only when we say so. | The agent genuinely flies the vehicle. Think time is free. |
| **replay** | no AGC at all — play a recorded log back (§3.2) | Watching, debugging, figures. |

**Verified empirically, not just from source** (`scratchpad/step_probe.py`, `pause_probe.py`):
- A 5 s pause before a `STEP 1000` advanced the AGC by 1,664 cycles vs 1,623 with no pause. No
  fast-forward burst (that would have been ~427,000). The `SimUpdateTime` cancellation works.
- **Stepped is paced 1:1 to wall-clock, not faster.** The step loop only runs while
  `CycleCount < DesiredCycles`, and `DesiredCycles` grows with *un-paused* wall time. Measured:
  `STEP 100000` took 1.92 s wall and advanced 192 cs of AGC time. Pausing is free; *speed-up is
  not on offer* — a 12-minute descent costs ≥12 minutes of wall-clock plus thinking time. Going
  faster than real time would need a patched `SimExecute`, which we are not doing (submodule stays
  pristine). Replay (§3.2) is the fast way to *watch* one.
- ~1.62 AGC cycles per instruction (1,623–1,664 per 1,000), so a fixed instruction count per tick
  drifts a few percent against the plant's `dt`. `sim/clock.py` must **calibrate**: read
  `CycleCounter` (in the core dump) periodically and adapt instructions-per-tick, and log the
  plant-vs-AGC time drift as a first-class number.
- **`COREDUMP <file>` exists as a debugger command** and costs ~15 ms. Too heavy per 50 Hz tick;
  exactly right at the pause boundary once per guidance cycle. In `stepped` mode this replaces the
  `--dump-time` polling for reading the DPS `THRUST` register — deterministic instead of racy.
  `CoreDumpPoller` remains the `realtime`-mode mechanism.

**Consequence worth knowing:** yaAGC is single-threaded and services its sockets in the same loop,
so while it is blocked at the prompt it is not reading the channel socket. Plant→AGC pulses written
during a pause queue in the TCP buffer and are consumed on resume. That is actually the correct
semantics (they represent the interval that already elapsed), but it means *the pause boundary is
also the I/O boundary* — do not expect the AGC to react to anything mid-pause.

Note the inversion: the Gate 0 trap (yaAGC hangs forever without `--nodebug`, because the engine
loop blocks on the debugger prompt) is *precisely* this feature. Same behaviour, opposite sign.
`stepped` mode must therefore launch **without** `--nodebug`, with stdin held as a pipe.

Design rule: nothing outside `sim/clock.py` may call `time.sleep`, read the wall clock, or assume
sim-time equals wall-time. Every module takes `dt` from the clock. Break this and `stepped` and
`replay` modes rot immediately.

### 3.2 Record and replay

Replay is **playback of a recorded log, not re-simulation.** No AGC process, no physics, no model
calls — just reading back what happened. That makes it exact, instant, and dependency-free, and it
is what makes both the viewer and `make reproduce` work.

- **Record every tick:** plant state, all channel traffic in/out, DSKY registers, throttle register,
  fuel, alarms, plus every agent intent, reasoning summary, tool call and safety veto.
- **One line per tick, JSONL**, gzipped. An episode is minutes at 50 Hz — small.
- **Self-describing header** (already required by §6): scenario seed, policy config, model hash,
  prompt hash, git SHA, clock mode. A log that cannot say what produced it is worthless by week two.
- **Play back at any rate:** 1× to watch it like a recording, faster to scan, scrub/seek because
  Rerun gives you a timeline for free. A 40-minute stepped episode that took two hours of wall-clock
  to run plays back in its true 12 minutes.
- **Do not promise bit-exact re-simulation.** In `realtime` mode the AGC is wall-clock coupled and
  will not reproduce identically. `stepped` mode is much closer to deterministic, which is a second,
  quieter argument for it. Replay of the *log* is always exact; re-*running* is not.

### 3.3 What you actually see

The ask is simple: where is the vehicle, where is the ground, what is it doing, what is the agent
thinking. In that order.

- **Side-elevation profile (2D)** — the one that answers "am I about to hit something": terrain line,
  LM marker with attitude tick, thrust vector, trajectory trail, target site, hazards. Cheap to
  build, and it carries most of the value. **This comes first, in Phase 1b.**
- **Terrain is synthetic and seeded, not real selenography** — and it is not extra work: §2.5 already
  requires craters, boulder fields and slopes as *scenario* parameters, so the generator has to
  produce a heightmap regardless. The viewer just draws what the scenario already contains.
- **Telemetry strips** — h, ḣ, horizontal v, throttle, fuel-seconds-remaining, tilt, PROG/V/N, alarms.
- **DSKY panel** — the real AGC display registers. This is the thing that proves the 1969 rope is
  genuinely in the loop rather than claimed to be.
- **Agent trace on the same timeline** — intent, reasoning summary, tool call, vetoes, so a bad
  landing can be scrubbed back to the decision that caused it.
- **3D** — LM body axes, thrust vector, trajectory ribbon over a heightmap. Phase 5. It is the least
  informative per hour spent; the 2D profile already answers the altitude question.

**Style: instrument panel, not dashboard.** Dark, monospace, two or three accent colours total
(nominal / caution / alarm) and nothing else. Numbers with units and fixed decimal places over
gauges and dials. No gradients, no drop shadows, no chartjunk, no decorative 3D. Every pixel either
states a value or shows a trend. If an element does not change a decision, delete it.

---

## 4. Stack decisions (prescriptive, tradeoff stated)

| Concern | Choice | Why, and what you give up |
|---|---|---|
| AGC emulation | `virtualagc` — build **only `yaYUL` + `yaAGC`** | The GUI components drag in GTK/wxWidgets/X11; `LM_Simulator` is Tcl/Tk and documented as running at fractional speed on Macs. You lose the ready-made DSKY; you write one in Python in a day and need a programmatic one anyway. |
| Flight software | **Luminary 099** (Apollo 11) | The landing rope. Keep Luminary 131 as a swap-in — its source provenance is better validated. |
| Language | Python 3.12, `numpy` plant | One language, one repo, one test runner. |
| Package mgmt | `uv` | Fast, single lockfile. |
| LLM runtime | **Ollama** + `qwen3:8b` primary, `llama3.1:8b` secondary | Native Metal, local endpoint, already in your stack. Less control than raw `llama.cpp`; drop down if you need GBNF grammar constraints. |
| Structured output | JSON schema + validate + one repair retry + deterministic fallback | Small models emit malformed JSON often enough to matter. |
| Visualisation | **`rerun-sdk`** | Local, pip-installable, 3D + synchronised time-series + text log on one scrubbable timeline. Add `matplotlib` for final figures. |
| Sim clock | **Own it in `sim/clock.py`**, three modes (§3.1) | `stepped` mode is the difference between the agent flying the LM and the agent commentating on it. Cost: nothing outside the clock may touch wall-time, forever. |
| Episode log | **gzipped JSONL, one line per tick** | Greppable, streamable, diffable, no schema migration pain, replays without the emulator. Bigger than a binary format; irrelevant at this scale. |
| Orchestration | **Write your own loop.** No LangChain / CrewAI. | ~200 lines. Framework abstractions actively obstruct a latency-constrained loop with a veto layer. Deliberate call — and a defensible one to explain in an interview. |

**Day-1 risk check:** does `yaAGC` compile and run on macOS arm64? If not, fall back to a Linux
container (colima + Docker) with the plant on the host and TCP across the boundary, or the
WebAssembly build. Do not discover this in week 6.

---

## 5. Phase plan with gates

Each phase has a **gate** (binary, demonstrable) and a **kill criterion**.

### Phase 0 — Repo and emulator (week 1) · Track A
- [x] Repo scaffold, `uv init`, ruff + mypy + pytest, pre-commit
- [x] `virtualagc` as a **git submodule** at a pinned commit — never vendor it into your tree
- [x] Build `yaYUL`, assemble Luminary 099 to a core rope, run `yaAGC` headless
      (virtualagc has moved to top-level CMake since this plan was written — no more
      per-directory Makefiles; see `src/luminary_agent/agc/build.py`)
- [x] `AgcClient`: 4-byte channel packet encode/decode, including the `u` mask bit that lets
      multiple peripherals share one input channel (protocol read directly from
      `agc_utilities.c`'s `FormIoPacket`/`ParseIoPacket` — ground truth beats the doc)
- [x] Text DSKY: press keys programmatically, read display registers back
      (`src/luminary_agent/agc/dsky.py`, `client.py`)
- [x] **GATE 0:** you type `V16N65` from Python and watch the AGC's mission timer tick.
      Passing as `tests/integration/test_gate0_mission_timer.py`. Noun 65 = "SAMPLED AGC
      TIME (HRS,MIN,SEC)" (confirmed in `PINBALL_NOUN_TABLES.agc`); R3 tracked real wall
      time almost exactly (18.10s -> 20.10s over a 2.0s sleep).
      **Trap hit and fixed:** yaAGC's `SimExecute` loop blocks forever on the interactive
      debugger prompt reading stdin unless launched with `--nodebug` — without it the
      engine never executes a single cycle, so no keystroke or channel write is ever
      serviced. Not documented anywhere obvious; found by tracing `main.c` -> `SimExecute`
      after the socket accepted a connection but never reacted to input.
- [ ] Kill: no working `yaAGC` on any local path by end of week 2. (moot — closed week 1)

### Phase 1 — Plant and instruments (weeks 2–4) · Track A ← the real work
- [x] 3-DoF planar descent first (h, downrange, ḣ, v̇), RK4, 50 Hz (`plant/dynamics.py`).
      **Audit correction:** the first version was a *flat-Moon* model, which is wrong exactly where
      it matters. At PDI speed (~1.7 km/s) centrifugal relief v²/r ≈ 1.66 m/s² nearly cancels
      lunar gravity (1.62), so a flat plant plunges a vehicle that is nearly in orbit. Now polar
      about the Moon's centre (same state fields: tangential velocity, arc-length downrange).
      Guarded by a circular-orbit test — the check a flat model cannot pass.
- [x] DPS: throttleable 10–60% + fixed ~92.5% region, `ṁ = F/(g₀·Isp)`, Isp ≈ 311 s
      (`plant/propulsion.py`; masses/thrust are placeholder Apollo-11-class numbers,
      pending Phase 2 citations)
- [x] Lunar gravity, μ = 4.9028e12 m³/s², R = 1737.4 km (`plant/gravity.py`)
- [x] **IMU model** — specific force → PIPA pulse increments, stable-member frame → CDU angles.
      Most failure-prone module in the project. Unit-tested against analytic constant-acceleration
      cases *before* wiring it to the AGC (`plant/sensors.py`). Scale factors sourced from
      `external/virtualagc/Contributed/LM_Simulator/lm_simulator.tcl` (PIPA 0.0585 ft/s/pulse;
      CDU 360°/32768 counts, cross-checked against that file's independently-derivable
      "39.55078125 arcsec" comment).
- [ ] Landing radar with configurable lock-on delay and dropout
- [x] Wire plant ⇄ AGC, partially: RCS jets (ch 5/6), engine on/off (ch 11), and the
      throttle-update strobe (ch 14 bit 4) all read over the socket (`agc/actuators.py`).
      **Real gap found:** the DPS throttle *magnitude* (Luminary099's `THRUST` register,
      erasable address 055) is never broadcast over the socket at all — `agc_engine.h`
      marks 055-056 "spares" (no hardware-counter behaviour), and yaAGC's `ChannelOutput`
      (`agc_engine.c:659`) only ever fires from genuine channel writes, never from a plain
      memory write. Decided (with the user) not to patch the pinned emulator submodule for
      this; instead poll yaAGC's own `--dump-time` core-dump file, which is a complete text
      snapshot including all erasable memory (`agc/coredump.py`, `CoreDumpPoller`), verified
      end-to-end against a real running yaAGC in
      `tests/integration/test_coredump_against_real_yaagc.py`. **Calibration now closed:** three independent (count, force) pairs annotated in the
      flight-software source agree to 0.02% — `FMAXPOS` 3467 ↔ 43,454.7, `FMAXODD` 3841 ↔ 48,145.4,
      `FEXTRA` 4096 ↔ 51,330.9 — giving **12.533 N per count**. `FMAX` is thrust at the fixed 92.5%
      detent, so 100% is 46.98 kN, within 0.6% of the DPS's rated ~46.7 kN. This also exposed an
      error in my earlier placeholder (43.9 kN was FMAX mistaken for 100%); `propulsion.py` now
      derives `F_MAX_N` from it. The PADLOADS comment's "2.7 lbf/bit" is a 4% rounding of 2.82.
      **Second finding, bigger:** re-reading `THROTTLE_CONTROL_ROUTINES.agc`, the `THRUST` register
      is `PIF + PIFPSET` where `PIF = FC − FP` — a thrust **increment** (desired minus present),
      not a level, slewed at 32 counts/cs by the hardware. The plant therefore needs a
      `ThrottleActuator` that *integrates* the increments each `ch14 bit 4` strobe (~40 kN/s slew,
      ~1 s full-range), not a "read the throttle level" shortcut. My earlier framing (poll the
      register for the throttle) was wrong in kind, not just in units.
      IMU pulses now sent as real `UnprogrammedIncrement` packets (`agc/registers.py`:
      `pipa_pulse_packets`/`cdu_pulse_packets`, channel = `0x80 | register`, PINC/MINC for
      PIPA, PCDU/MCDU for CDU) and verified against a live yaAGC in
      `tests/integration/test_pipa_pulses_against_real_yaagc.py` (sent 17 pulses over the
      socket, read back 17 in PIPAX via the core dump).
- [x] Erasable-memory init via the V71/V72 update program (P27), not by poking memory
      (`agc/uplink.py`, `agc/symbols.py`). Verified against a live yaAGC
      (`tests/integration/test_uplink_p27.py`): a V71 block and a V72 scatter both land in
      erasable, and P27 correctly *refuses* (writes nothing) outside P00.
      **The ECADR question is closed:** `ECADR = bank·0400 + (addr & 0377)` for switched erasable
      (`E3,1733` → `01733`), the address itself for unswitched; names resolve from the assembler
      listing (`build.assemble` now saves it) so no address is ever hand-copied. Protocol limits
      are P27's, read from source: V71 ≤ 18 words (II ≤ 20 decimal, II = words + 2), V72 ≤ 9 pairs
      (II odd ≤ 19), data are unsigned octal at noun 01, `V33E` after the last entry is what makes
      P27 store. Traps hit: (1) **octal vs decimal** — P27 data words are octal keystrokes but
      V37's program number is decimal; typing `21` via an octal formatter selected P25 and quietly
      wandered through P31/P51/P63; (2) keys must be interleaved with stepping (see clock item).
      *Still to do for Gate 1:* double-precision scaling helpers (state vector, REFSMMAT are DP,
      2^28 / 2^-1 scaled) and read-modify-write for flag words (V72 overwrites the whole word).
- [ ] 6-DoF with RCS jet torques once 3-DoF closes
- [ ] **Gate 1 prerequisite ledger** (audit of `THE_LUNAR_LANDING.agc` P63 + `R02BOTH`; the
      one-line "load a state vector via V71" understated this badly). What P63 actually demands
      before it will burn, with the status of each:
      1. **`R02BOTH` IMU check** — needs `REFSMFLG` set in `FLAGWRD3` (REFSMMAT valid), else alarm
         220 and abort to P00; also `IMODES30` bit 9 (ISS initialised) or alarm 210. → load
         REFSMMAT + set the flag bit (V71/V72; read-modify-write, since V72 overwrites the word).
      2. **State vector + landing site + times** — `RLS`, `TLAND`, LM state vector, `TEPHEM`
         (`IGNALG` integrates forward to ignition). → V71 state-vector update (21 octal comps).
      3. **`R60LEM` auto-attitude maneuver** — Luminary commands a slew to burn attitude through
         the DAP and waits for the CDUs to converge. So the plant needs *attitude* (RCS jets that
         actually rotate the vehicle, feeding CDU angles back) — or the vehicle initialised already
         at burn attitude so the maneuver is a no-op. **This pulls 6-DoF (at least 3-axis
         attitude) *before* Gate 1, contradicting the order the plan currently lists.**
      4. **Hardware discretes on input channels 30-33** (inverted: 0 = present). yaAGC boots with
         only ch30 bit 15 (stable-member temp OK) asserted. P63 needs at least LR antenna
         position 1 (ch33 bit 6, else it prompts "crank the silly thing", code 500), and the DAP/
         engine paths read ENGINE ARMED (ch30 bit 3), AUTO THROTTLE (bit 5), LM-computer-has-control
         (bit 10), IMU operate (bit 9). → a `plant/discretes.py` nobody had listed.
      5. **CDU registers seeded** to the initial gimbal angles (2^15 counts/rev; 4-6k pulses through
         yaAGC's rate-limited CDU FIFO — fine in stepped mode).
      6. **`R51P63` prompt** at `ASTNRET` — `ENTER` continues (no star sightings needed).
      **Status (sub-gate 1a PASSED):** `plant/discretes.py` written from the channel
      documentation and *verified against the flight software* — Luminary's T4RUPT `IMUMON`
      mirrors what we write into `IMODES30` (polarity and bit positions confirmed live).
      `sim/loop.py` runs plant + IMU → AGC → clock → recorder; a 3 s coast at PDI speed holds
      altitude to <1 m, records 150 ticks, keeps plant/AGC time within 50 ms, raises no alarm.
      **Finding — cold boot raises alarm 1107** (phase-table failure): erasable starts zeroed, so
      the first restart finds an invalid phase table. FAILREG holds it until cleared. Not caused
      by anything we send (present at 0.1 s of AGC time, before any I/O). Fix is what a crew does
      after power-up: `V36E` fresh start (`SteppedDsky.fresh_start`). "No alarms" for every later
      gate therefore means *no alarm after a fresh start*. Left MODREG = -0 (fresh-start mode);
      P27 accepts it. **Decided for coasting (SUPERSEDED for P63 -- see the lunar-orientation finding below): REFSMMAT = identity**, so the stable member *is* the
      Moon-centred inertial frame and the PIPAs measure specific force along inertial X/Y
      (`sim/frames.py`: orbit in the X-Y plane, +X = local vertical at t0, +Y = direction of
      travel). This also corrected a design error: the IMU model had split specific force into
      local vertical/horizontal, but a stable-member accelerometer is inertial — the local
      vertical rotates as the vehicle moves along its orbit. `PipaAxes(x=PIPAX, y=PIPAY)`.
      **Sub-gate 1b progress.** DONE and verified against the flight software: a lunar-sphere
      LM state vector loads through P27 (`agc/state_vector.py`, `agc/scaling.py`) and Luminary's
      own `INTWAKEU` installs it — read back from the permanent `RRECTLEM/VRECTLEM/TETLEM`, never
      written by us. Load flag is `-2` (`077775`: negative = LM, |2| = lunar sphere); scales are
      position m B-27, velocity m/cs B-5, time cs B-28. The DP encoder is validated against
      constants the assembler itself wrote (golden vectors from a real yaYUL listing, including a
      negative), not against memory of the format. Scale conventions settled from flight-software
      arithmetic rather than comments (which disagreed): **`RLS` is stored B-27** (P57 does
      `VSL2` before `R-TO-RP` "gets RLS B-27"; P52LS undoes it with `VSR2`); `REFSMMAT` elements
      are stored halved (B1 — the only reading that lets a unit element fit).
      **STILL TO DO for 1b, and bigger than the ledger first said:**
      7. **The W-matrix pad loads.** `TLAND` and every braking/approach-phase *guidance target*
         (`RBRFG`, `VBRFG`, `ABRFG`, `JBRFG`, `RAPFG`, …) plus the throttle limits (`LOWCRIT`,
         `HIGHCRIT`, …) are mission pad loads (128 words, EBANK 5) — zero after a fresh start,
         which means P63 would aim at the origin. The repo has a documented catalogue with
         values, units and scale factors: `Luminary069/PADLOADS.agc` (43 landing entries).
         **Caveat to keep honest:** that is Luminary *69* — Apollo 10's software; Apollo 11's
         values differ. Same guidance family, so it is a consistent nominal scenario, but it is
         not "Apollo 11's pad load" and must not be described as one. → `agc/padloads.py`, parsed
         from that file, tested against it.
      8. `REFSMMAT` + `REFSMFLG` (read-modify-write of `FLAGWRD3`), `RLS`, and -- **corrected, this
         was wrong the first time** -- the Moon's orientation (see "lunar orientation" below). An
         earlier version of this item claimed `RP-TO-R` is identity to ~2 mrad; it is not.
      Useful oracle found: `V06N89`/`V06N43` make the flight software convert `RLS` / position
      back to lat-long-altitude, so a wrong scale shows up as an absurd altitude on the DSKY.
      **1b RESULT (exploratory, will become a test): `V37E63E` engages P63 with no alarm.**
      After fresh start, discretes, the landing pad loads, `REFSMMAT`+`REFSMFLG`, `RLS`, `TLAND` and
      an LM state vector (all through P27), `MODREG = 63`, display `P63`, `FAILREG` clear — so
      `R02BOTH` passed and P63 is running `IGNALG` (stop points in `INTEGRATION_INITIALIZATION`/
      `INTERPRETER`). Pad-load work: `agc/padloads.py` parses Luminary 69's catalogue (121 entries;
      all 26 landing ones resolve as erasable symbols in Luminary 99); **entries carry separate
      TWO-PHASE and ONE-PHASE landing-mode values — Apollo 11 used one-phase, so that is selected
      explicitly**; `TLAND` has no documented value ("launch date dependent") and is
      scenario-supplied. `agc/loads.py` batches ~70 words into the fewest P27 sessions; loading the
      full set and reading every word back takes ~57 s and raises no alarm. Parser bugs caught by
      tests along the way: the assembler's `B-n` sign convention, a `\b`/`*` regex backtrack that
      silently produced 0.0, and a bare `1DEC 3000` meaning an integer word (default B-14, B-28
      for DP). **Practical consequence: stepped mode is wall-clock-paced, so experiments that need
      minutes of AGC time cost minutes of real time** — budget for it, run long probes in the
      background, and keep the integration suite's slow tests few.
      **1b finding — alarm 1412 "DESCENT IGNALG NOT CONVERGING", diagnosed, not guessed.** The first
      P63 run (circular 15 km orbit) ran `IGNALG` for ~56 s of AGC time, then raised 1412. That is
      the flight software correctly rejecting an inconsistent scenario. `IGNALG` searches *along the
      state vector's own orbit* for the ignition time at which the vehicle is at the pad-loaded
      targets relative to the landing site: `RIGNZ` = −440 km ground range, `RIGNX` = −40.9 km
      "altitude" (checks out: 15 km at 440 km range is 15 − 440²/2R ≈ −40.7 km in the tangent-plane
      frame), `VIGN` = 16.995 m/cs = 1699.5 m/s. A circular orbit flies ~16 m/s under `VIGN` at
      *every* point, so no choice of time can null a constant offset. The scenario must be a
      descent **ellipse** with perilune speed ≈ 1699.5 m/s, and the site 440 km beyond perilune.
      → `plant/orbit.py` (`DescentOrbit.with_perilune_speed`), whose Kepler time-to-perilune is
      validated by integrating the RK4 plant for that time and arriving at perilune. Also aligned
      the plant's Moon radius with Luminary's `RSUBM` = 1,738,090 m: the flight software measures
      altitude above a sphere of exactly that radius, so a 690 m surface disagreement would show
      up as the wrong touchdown altitude.
      **1b finding -- how P63's ignition solver actually fails, and what it is telling us.** With a
      `snapshot -> resume` harness (each experiment ~1 min instead of ~4) the internals of `IGNALG`
      are observable (`NIGNLOOP`, `PIPTIME1`, `RGU`, `VGU`, all plain erasables). Two experiments:
      (a) circular orbit: 40 iterations, time guess stepping by a *constant -2621.4 s* (= 2^18 cs, a
      saturated correction), `RGU` swinging wildly, alarm 1412 (not converging). (b) descent
      ellipse + landing-site `REFSMMAT`: alarm 1406 (bad return from `ROOTPSRS`) at iteration 1.
      Reading `RGVGCALC`/`GUIDINIT`/`MOONMX` explained both. **(i) The guidance frame *is* the
      stable-member frame** (`CG` = identity in `IGNALG`, `RGU = CG*(R - LAND)`), so `REFSMMAT` must
      be the landing-site orientation, not identity; the loaded matrix reads back exactly as
      intended. **(ii) `RLS` is Moon-fixed and `RP-TO-R` applies the Moon's real orientation**
      (`MOONMX`: orbital elements + time since epoch; `TEPHEM` = ephemeris time at AGC zero).
      Evidence: `|LAND|` = 1,738,0xx m matches `|RLS|` (so the scales are right) but its
      *direction* in guidance coordinates is (-0.42, -0.22, +0.88) instead of (1, 0, 0) -- a
      ~115 degree rotation. `RLS`, `TLAND`, `RRECTLEM` and `REFSMMAT` all read back exactly.
      **Lunar orientation -- what has to be built (not yet done):** (1) port `MOONMX` (constants
      `BSUBO/BDOT/FSUBO/FDOT/NODIO/NODDOT/SINI/COSI`, `MOONRATE` are fixed-memory 2DECs in the
      source) to `plant/lunar_orientation.py`; the observed `LAND` above is a ready-made golden
      test. (2) Choose the plant's orbit plane as the Moon's *equatorial* plane in the AGC's
      reference frame (pole = row 3 of M), so lunar rotation is an in-plane rotation. (3) Compute
      `RLS = M(T) * R_site_ref` for a chosen site. (4) **The plant must rotate the surface too**:
      the site moves ~4.6 m/s inertially (omega_moon ~ 2.66e-6 rad/s) and the AGC computes velocity
      *relative to the surface* (`V - WM x R`). A plant that ignores it carries a ~4.6 m/s
      horizontal-velocity error into touchdown, against a 1.2 m/s limit -- a correctness
      requirement, not a refinement. Also set `TEPHEM` deliberately (V70/V73 path) so the epoch is
      a documented choice rather than an accident of a fresh start.
      **1b RESULT -- `IGNALG` CONVERGES (sub-gates 1b and the first half of 1c pass).** With the
      Moon-fixed `RLS = M(T)*(site)` from the ported `MOONMX`, the plant's orbit in the Moon's
      equatorial plane (`sim/frames.py: LunarFrame`), and a landing-site `REFSMMAT`, the first
      `IGNALG` iteration reads `RGU = (-42.6, -0.9, -436.3) km` against the pad-loaded targets
      `(-40.9, 0, -440) km` -- where the identity assumption had given `(2.4 Mm, 377 km, -2.0 Mm)`.
      The solver applies two small corrections (time guess 352.2 -> 349.9 s), the loop counter
      freezes at 38 (`DDUMGOOD` exits early: converged), and P63 proceeds to **`V06 N61` with no
      alarm**. `V06N61` is a crew acknowledgement prompt ("used by the crew in P63 to reset his
      event timer to agree with TIG") -- P63's first DSKY decision, and therefore the agent's.
      `TIG = 323.91 s` = `TDEC1 349.9 - ZOOMTIME 26 s`, exactly as `DDUMGOOD` computes it.
      **Two more of my own errors caught on the way:** (1) `dp_decode` assumed both words of a
      double-precision value share a sign; the AGC does not keep them normalised between
      operations, and `TIG` read mid-computation is `(0o2, 0o77206)` = `2*16384 - 377` = 32391 cs,
      which the old decoder read as ~651 s. That was plausible enough to waste time before the
      geometry ("at 651 s the vehicle is 68 km past the site") showed it couldn't be right --
      physical sanity checks on decoded values are worth doing. (2) My own porting tolerances were
      tighter than the flight software's 8-digit constants can support (`sin^2+cos^2 = 1 - 3.2e-9`).
      **Documented model gap:** the ported `M` reproduces the AGC's `LAND` direction to ~0.05%
      (~1 km); no sign/transposition variant reduces it (best 933 m across all 16), so it is
      recorded as a measured gap and not explained. The AGC stays the authority for where it
      believes the site is.
      **The P63 crew sequence, mapped through the flight software's own prompts** (each is a DSKY
      decision -- the agent's decision space, discovered rather than assumed):
      `V37E63E` -> ~60 s of `IGNALG` -> **`V06 N61`** ("reset your event timer to agree with TIG";
      answer `V33E`, proceed) -> **`V50 N25`, R1 = 14** (checklist code 00014: PROCEED = IMU fine
      align, needs star sightings; **ENTER = skip**) -> **`V50 N18`** (Luminary asks the crew to
      approve the **automatic maneuver to the burn attitude**, with the desired FDAI angles in
      R1-R3) -> `R60LEM` slews the vehicle -> LR antenna position (`ch33` bit 6, already
      supplied) -> countdown, ignition, engine on at minimum throttle, throttle-up after
      `ZOOMTIME` = 26 s. The first two prompts are answered from a script; `V50N18` is the wall.
      Also observed: `THRUST` already reads -4096 (a -BIT13 increment) as ignition prep begins.
      **Next wall = sub-gate 1d, attitude.** `R60LEM` needs a vehicle that rotates: jets on
      ch5/6 must torque a body whose gimbal angles feed back into the CDU registers. The
      cheaper route to sub-gate 1e (ignition) is to seed the CDU registers at the desired burn
      attitude so the maneuver is a no-op -- the desired angles are readable from the AGC
      (`THETAD`), the CDU is 2^15 counts/rev (~9.8k pulses for a 107 deg pitch, through yaAGC's
      rate-limited CDU FIFO). That is a stepping stone, not a substitute: attitude dynamics
      (6-DoF, or at minimum 3-axis rotation under RCS torque) is still required before the agent
      can be asked to fly anything through R60/R65/R66.
      **Sub-gate 1c PASSED -- P63 runs the whole pre-ignition sequence with no alarm.** Three
      more prerequisites found (each was a silent stall or a misleading alarm, not an error message):
      (1) **DAP mode switch must read AUTO** (`ch31` bit 14). `R60LEM` calls `G+N,AUTO` after
      PROCEED and, if it fails, silently re-requests the maneuver forever. (2) **A CSM state vector
      is required**: with `MUNFLAG` set (it is, in P63) `P41SPOT` runs `CSMPREC`, a precision
      integration of the *CSM's* state, before the LM's; on an all-zero CSM state it raises 1703
      "ignition time slipped". Loaded via V71 with flag `+2` (CSM, lunar sphere; the LM is `-2`).
      (3) The maneuver prompt is *two* prompts: `V50N18` (approve) -> static `V06N18` (running) ->
      `V50N18` again (**finished; ENTER ends R60**) -- I had read the second as a loop.
      With those, the run reaches: `V06N62` countdown displays -> **RCS ullage jets at TIG-7 s**
      (`ch5 = 0o210`) -> **`V99 N62` at TIG-4 s** (crew must enable the engine) -> throttle-up
      command `THRUST = +4096` (= `FLATOUT`) at `TIG + 26.9 s` = exactly `ZOOMTIME`.
      Then alarm 1406 from descent guidance -- expected: the plant wasn't running, so there was no
      engine and no acceleration for the guidance to see.
      **Next (sub-gates 1e/1f): close the loop through the burn.** Needs the `Simulation` loop
      running from ignition with: engine-enable answered (`V99N62` -> `V33E`), `ThrottleActuator`
      fed by the strobes, and the thrust *direction*. With no attitude dynamics the direction is
      taken as perfectly pointed: `IGNALG` points the body X axis along `R60VSAVE`/`UNFC/2`
      (the guidance's desired thrust unit vector, in stable-member axes), readable from the AGC.
      That is the "perfect pointing" stepping stone and must be labelled as such in any result.
      **1e/1f finding -- the PIPA pulse weight was wrong (mine, and it was hidden until the loop
      closed).** The first full burn ended in a crash, 200+ km short. Comparing the AGC's own belief
      (`RGU`/`VGU`, plain erasables) with the plant's truth showed *position* agreeing to <0.3% (so
      frames, `REFSMMAT`, the ported lunar orientation and site placement were all right) but the
      AGC's *velocity change* being exactly 0.498 of the truth: it sensed half the deceleration and
      under-braked. Cause: `PIPA_SCALE_MS` = 0.0585 "ft/s", from the Tcl LM_Simulator stub,
      unsourced as to units. Luminary's own constants give it exactly: `KPIP1 2DEC .0128` scales
      `DELV` (pulses x 2^-14) to units of 2^7 m/cs => **1.0e-4 m/cs = 0.01 m/s per pulse**. 0.0585 is
      the *Command Module's* 5.85 cm/s. After the fix `VGU` tracks truth: 231.8 vs 231.7 m/s. Lesson,
      twice over now: a constant from a contributed stub is a hypothesis, and the flight software's
      own arithmetic is the authority. The unit test now derives the value from `KPIP1`.
      **Also found while closing the loop (both mine):** (a) `CHAN14` bit 4 is a *latched level*
      (`WOR CHAN14 # TURN ON THRUST DRIVE` at fresh start), not a pulse -- counting rising edges
      missed every throttle command after the first; the trigger is now `TTHROT`, the clock stamp
      written with each command. (b) `UNFC/2` is rewritten every guidance pass, not on throttle
      changes; sampled on a 0.5 s cadence. A stale value read at ignition (cross-range garbage
      left by `IGNALG`) had been flown for 300 s, thrusting prograde.
      **1f RESULT -- a full powered descent flown by the original rope, with an honest open problem.**
      With the plant closed around Luminary 099 (no alarms during the burn): engine lights at 10%,
      `FLATOUT` to the 43,455 N detent at TIG+26 s, thrust pitch 92 -> 71 deg (retro), **P63 -> P64
      automatic phase switch at t = 577 s**, throttle-down 43 -> 15 kN, tangential speed 1707 ->
      **10 m/s**, vertical speed -> **+0.5 m/s at 177 m altitude**, propellant 15,000 -> 7,971 kg.
      Then the last ~30 s fail: pitch flips +-180 deg, thrust winds up to 43 kN, alarm 1410
      ("unintentional overflow in guidance"), P65, and the vehicle climbs away. **Diagnosed with the
      new checkpoint/resume (a 17 min run reproduces in ~1 min, deterministically):** the AGC
      believes it has a persistent **cross-range** error at the site (`RGU_y` ~ -130 to -170 m; true
      value 0 in the planar plant) -- from the documented ~1 km residual in the `MOONMX` port plus
      lunar rotation moving the site under the vehicle -- so `UNFC/2`, its thrust command, becomes
      *dominated by the out-of-plane component* (x 0.001 vs y 0.007 at t = 892). A planar plant
      drops that component, the in-plane remainder is ill-conditioned (hence the +-180 deg pitch),
      and the AGC never sees the correction it commands (no lateral acceleration reaches its PIPAs),
      so it winds up. **The plant cannot yet express an error the AGC is trying to fix.**
      Also noted: `MASS` in the AGC is a constant 6,804 kg (pad-load default) vs a true 8,100 ->
      7,500 kg; the guidance closes on acceleration so this scales consistently, but the loaded
      mass should be set deliberately.
      **Options, in the order I'd take them:** (1) *out-of-plane dynamics* -- add a lateral position
      and velocity so the plant obeys the full thrust vector (small: `a_lat = T*u_y/m - mu*z/r^3`),
      PIPAY then responds and the AGC's cross-range loop closes instead of winding up; (2) *remove the
      source*: read the AGC's own `LAND` after `IGNALG` and rotate `RLS` to cancel the port residual
      (two-pass, ~2 min), so the AGC's site and the plant's coincide; (3) judge the landing against
      the AGC's `LAND`, not the plant's own site. (1) is required regardless -- a real descent has
      cross-range; (2) makes the baseline clean.
      **1f FIXED -- the original rope lands the plant (t = 1037 s, zero alarms).** Touchdown at
      **0.76 m/s vertical, 0.41 m/s horizontal relative to the surface** (limits 3.0 / 1.2), 7,367 kg
      left. Two root causes, both found by inspecting the AGC's erasables against plant truth:
      (a) the plant had no out-of-plane channel -- now `Simulation` integrates a linearised lateral
      z from the out-of-plane part of `UNFC/2`, felt by PIPAY, so the cross-range loop closes (also
      a pitch guard: hold last pitch when the in-plane thrust part vanishes); (b) **Luminary 099
      moved P65/P66's constants (`V2FG` = (-3 ft/s,0,0), `TAUVERT` 600 B-14, `TAUROD` 300 B-12) from
      fixed memory (as in 069) to erasable pad loads that its source does not provide** -- left at
      zero, P65 divided by TAUVERT = 0, overflowed (alarm 1410) and Luminary then skips the throttle
      call, freezing thrust. Now loaded from 069's values in `prepare_landing`.
      **Caveats to carry into results:** touchdown is 301 m from the plant's own site (the AGC
      steers to its own `LAND`, the ~1 km MOONMX-port residual plus lateral drift; judging against
      the AGC's `LAND` is open); AGC `MASS` is 6,804 kg vs a true ~8,100; perfect pointing.
      **Viewer (Phase 1b, first cut):** `python -m luminary_agent.viz.replay episode.jsonl.gz out.html`
      -> one self-contained HTML (side elevation, auto-zoom to altitude, LM + thrust flame + velocity
      vector, altitude grid, instrument readouts, play/pause, 0.5-20x, scrubber; 1x default = normal
      speed replay of the saved log, no AGC needed). Terrain is a cosmetic profile; ground truth is
      the h = 0 line. Not yet: real terrain from a scenario, AGC/DSKY panel, alarms timeline.
      **Phase 3 started:** `scenarios/dispersions.py` (seeded truth-vs-belief dispersions, 3 tiers),
      `eval/score.py` (judged from plant state only), `eval/run_null.py` (NullAgent = pure
      Luminary, one scored JSON line per episode). **First finding:** without a landing-radar
      model, the AGC never learns a start-state error, so it is brutally sensitive -- a 0.32 m/s
      radial velocity error made pure Luminary hover at 406 m until propellant ran out; 1 m/s
      crashed 850 m short at 42 m/s; 2 m/s crashed 7.9 km short. ~700 m per m/s. Tiers are scaled
      accordingly; a landing-radar/LR-altitude channel (which is also the Apollo-11 decision
      scenario, 2.3) is the next plant feature for tiers where the null baseline must not just fail.
      **NullAgent at the recalibrated tiers (seed 0 each): all three land safely** (0.73-0.86 m/s
      vertical, ~0.4 m/s horizontal, zero alarms, 518-993 kg propellant left, 34-345 m from the
      plant's site). So at scales pure Luminary can absorb, the tiers are too easy for Gate 3, and
      at scales it cannot (0.3 m/s and up) the failure is uninformative because nothing can fix it.
      Harder tiers must come from axes an agent *can* act on: fuel margin (mass/propellant), engine
      degradation/stuck throttle, 1201/1202 overload, and -- once modelled -- landing radar. Note
      yaAGC's socket build stubs `RequestRadarData` (SocketAPI.c), so an LR needs RNRAD pulses
      injected in step with the radar gate (RADARUPT after 9 TIME5 counts with CHAN13 bit 4 set),
      the LR range/velocity discretes on CHAN33, and Luminary's R12 enables; sized as its own item.
      **Eval sets:** `eval/sets.py` -- FROZEN = 3 tiers x seeds 100-119 (60), DEV = 3 tiers x seeds
      0-4 (15), disjoint; `run_set --set frozen|dev`, `eval/report.py` prints per-tier summary.
      **Blocker found for the ROD (P66) channel -- the baselines the plan wants ("PIDAgent on the
      ROD channel", "ScriptedAgent: P63 -> P64 -> P66 takeover") cannot be built yet, for two
      independent reasons, both verified:**
      (1) *No delivery path.* Luminary counts ROD clicks in `DESCBITS`, reached only from MARKRUPT
      (CHAN16 bits 6/7). yaAGC's socket build sets no interrupt for a CHAN16 write (only CHAN15 ->
      KEYRUPT, 0173 -> UPRUPT; SocketAPI.c), and its debugger has no interrupt injection. Entering
      P66 also needs the ATT HOLD discrete (CHAN31 bit 13 clear) *and* a nonzero `RODCOUNT`
      (`STABL?`/`P66NOW?`). Prototyped: patching `RODCOUNT` = 1 in the stepped core file (what the
      trap would do) plus CHAN31 bit 13 clear does switch Luminary to P66 (`MODREG` = 102). A
      pause-boundary poke via core-dump resume is therefore feasible, as a documented deviation
      from "never poke".
      (2) *Missing pad loads.* Luminary 099's P66 law uses `RODSCALE`, `LAG/TAU`, `MAXFORCE`,
      `MINFORCE` (and `TAUROD`, loaded from 069), erasable "I" variables whose values appear in no
      source in the pinned repo (069 has different constants; 099 has no PADLOADS). At zero,
      P66 commanded minimum throttle (4.7 kN) and the LM fell. Apollo 11's real values must come
      from a sourced document (Luminary 1A pad-load listing / GSOP) -- not guessed.
      Until both are resolved, the sourceable scenario axes are those that need no new actuation:
      fuel margin, engine degradation, alarms, and (if modelled) the landing radar.
      **Manual takeover works, and it is the first scenario where a decision matters.** Luminary's
      polled R13 monitor (GUILDENSTERN) selects P67 when the auto-throttle discrete (CHAN30 bit 5)
      clears, with no ROD click needed (verified: `MODREG` = 103, AGC stops commanding thrust) --
      unlike ROD, this is deliverable through the socket. `policies/manual_lander.py` flies from the
      plant's truth (radar-like) inside the DPS limits; `run_set --pilot manual`. **Tier 3 = a
      navigation error the AGC cannot see (0.3 m/s, 100 m): pure Luminary 0/2 safe (vz 2.1/3.2,
      vh 19/13 m/s), manual takeover 2/2 safe (vz 0.33/0.40, vh 0.00).** Caveats: n = 2; the pilot
      does not steer to the site (site error ~600 m); its takeover rule is fixed (h <= 150 m or
      P65), not yet a decision; ROD (P66) remains blocked (see above). The pilot, not the AGC, is
      now the thing an LLM agent will replace: it decides *when* to take over and what to command.
      **Infrastructure added:** `run_descent`/`resume_descent` + `save_checkpoint` (AGC state via
      yaAGC's core dump, plus plant, actuator and loop bookkeeping), `on_second` hook for AGC-vs-truth
      comparison, non-fatal alarms with abort detected by Luminary leaving the landing programs,
      `plant/surface.py` (touchdown judged relative to the rotating surface: ~4.6 m/s of the
      inertial tangential speed at touchdown is the surface's own).
      **Consequence for scheduling:** the plan's kill criterion (Gate 1 by week 6, else
      `fallback_guidance/`) stands, but Gate 1 is now visibly a bundle of ~6 sub-gates. Track them:
      **1a** IMU alive, no alarms, P00 stable with plant coasting · **1b** REFSMMAT/state vector
      accepted (no 220/210) · **1c** V37E63E reaches `R60LEM` · **1d** attitude holds/slews with
      plant feedback · **1e** ignition, engine on, throttle register moves · **1f** braking phase
      descends monotonically. Do not report Gate 1 as one lump; report the highest sub-gate passed.
- [ ] **GATE 1:** from a P63 ignition state, Luminary drives the plant through braking phase,
      altitude decreases monotonically under AGC-commanded throttle, no AGC alarms.
- [ ] Kill: gate 1 not passed by end of week 6 → `fallback_guidance/` (Python Klumpp quadratic
      guidance + P66 rate-of-descent), identical plant / blackboard / policy interfaces.

### Phase 1b — Debug viewer + clock + recorder (parallel, week 2 onward) · Track A
- [x] `sim/clock.py` with `realtime` and `stepped` modes (§3.1), plus `agc/process.py` (the one
      launcher for both). Verified against a real yaAGC (`tests/integration/test_stepped_mode.py`):
      a 3 s pause causes no fast-forward; a paused world stays frozen (display unchanged over 2 s of
      wall-clock) and stepping advances the mission timer by exactly what the AGC executed; the
      stepped clock holds plant-time and AGC-time within 50 ms over 3 s of 50 Hz ticks by
      calibrating instructions-per-tick against `CycleCounter`.
      **Finding — I/O must be interleaved with stepping.** A keycode sits in channel 015 until
      Luminary's KEYRUPT handler reads it; a second key written before that overwrites it. Firing
      `V16N65E` back-to-back and then stepping loses keys (the display never rendered N65). Press a
      key, step ~3,000 instructions, press the next. Same rule for anything channel-shaped; PIPA
      counter increments are safe in bursts (each is consumed as read), keycodes are not.
- [x] `sim/recorder.py`: gzipped JSONL, one line per tick, self-describing header (§3.2)
      (`Recorder` refuses an empty header; `read_episode` streams, never loads the whole log)
- [ ] Rerun time-series: altitude, ḣ, horizontal v, throttle, fuel, tilt, channel traffic
- [ ] **Side-elevation profile with terrain line, LM marker, thrust vector, trajectory trail** —
      the "where am I relative to the ground" view (§3.3). Cheap, and the single most useful panel.
- [ ] `replay <log>` — play any recorded episode back at 1× (or any rate), no AGC needed
- [ ] Not the 3D scene, not the DSKY replica — those are Phase 5.

### Phase 2 — Domain research & taxonomy (week 4–5, overlaps) · Track A
- [ ] Turn §2 into `docs/flight-contexts.md` with a source citation per failure mode
- [ ] Reuse the Apollo/NTRS retrieval work to extract it; a structured taxonomy is a better
      output from that corpus than free-form Q&A, and it is a repo artifact in its own right
- [ ] For each mode: observable signature in telemetry/DSKY, required decision, time available
- [ ] **GATE 2:** every scenario knob in Phase 3 traces to a cited real occurrence.

### Phase 3 — Baselines and scenarios (weeks 5–6) · Track A
- [ ] `NullAgent` (pure Luminary — the reference trajectory), `ScriptedAgent` (Apollo 11
      timeline: P63 → P64 at hi-gate → P66 takeover), `PIDAgent` on the ROD channel
- [ ] Scenario generator over the §2 axes, 3 difficulty tiers × 20 seeds = **60 frozen episodes**,
      plus a separate 15-episode dev set you *are* allowed to tune on
- [ ] **GATE 3:** baselines run all 60 and fail a non-trivial fraction. If they land 60/60 the
      scenarios are too easy — make them harder now, not after the agent exists.

### Phase 4 — The agent (weeks 7–9) · Track B
Implement in this dependency order:
1. **Typed tool interface** — no shell. `read_telemetry`, `read_dsky`, `key_dsky(seq)`,
   `set_descent_rate`, `redesignate_site(az, el)`, `abort(stage)`, `hold()` (so "do nothing" is a
   first-class action).
2. **Hierarchical planner/executor.** Planner fires on phase transitions and anomalies plus a 5 s
   heartbeat, emitting an intent with a validity window; a deterministic executor realises it every
   tick and reports satisfied / violated / expired. This is what makes a 2 s-latency model viable.
3. **Blackboard summariser.** The LLM never sees raw telemetry — a deterministic ~200-token flight
   brief: phase, altitude, ḣ, horizontal v, fuel seconds, alarms, hazard assessment, time to next
   decision point. Token budget is a design parameter; measure it.
4. **Safety monitor with veto.** Deterministic envelope checks every tick, outside the LLM. Can
   override or abort. The agent cannot disable it. Veto count is a headline metric.
5. **Graceful degradation.** LLM timeout, malformed output after one repair, or Ollama crash → hold
   the last valid intent, scripted baseline takes over. Test by killing Ollama mid-descent.
6. **Reflection** after each episode → a short lesson from outcome + decision trace.
7. **Episodic memory** — retrieve k most similar past scenarios by initial conditions, inject their
   lessons. `sqlite` + `nomic-embed-text` via Ollama; no vector DB at this scale.
8. **Self-consistency on irreversible decisions only** — abort/no-abort gets 3 samples and a
   majority vote. Everything else single-shot; sampling everything triples latency for nothing.
- [ ] **GATE 4:** nominal scenario end-to-end, zero safety vetoes, zero fallback activations.

### Phase 5 — Full visualisation (week 10)
- [ ] 3D: lunar heightmap, LM body axes, thrust vector, trajectory ribbon, target and hazards
- [ ] DSKY replica showing the real AGC display registers — this is what proves the original
      software is genuinely in the loop
- [ ] Agent trace on the same timeline: intent, reasoning summary, tool call, vetoes
- [ ] **GATE 5:** scrub a crash and see AGC display, agent reasoning and 3D attitude at the moment
      it went wrong, in one window.

### Phase 6 — Validation (weeks 11–12)
**Per-episode success criteria** (mirroring LM design limits): vertical touchdown ≤ 3.0 m/s
(≤ 1.0 nominal), horizontal ≤ 1.2 m/s, tilt ≤ 12° on ≤ 6° slope, within 100 m of target and clear
of hazards, fuel remaining > 0 with the margin logged.

**Metrics:** success rate, soft-landing rate, mean/σ touchdown speed, site error, fuel margin,
vetoes per episode, fallback activations, LLM calls per episode, decision latency, total tokens.
In `stepped` mode, report decision latency as **wall-clock cost per decision** and **sim-time
elapsed while thinking (= 0)** separately — collapsing them hides the whole point.

**Comparisons:** null · scripted · PID/MPC · LLM agent; plus two model sizes (4B vs 8B — the
scaling curve for agentic control on a laptop is genuinely under-reported); plus **realtime vs
stepped for the same policy on the same seeds** — the delta is a direct measurement of what
real-time pressure costs an 8B model, which is a publishable number in its own right and is
available to nobody who only built one clock mode.

**Ablations over the frozen 60:** no reflection · no memory · no safety monitor (expect worse;
report honestly) · no hierarchical split · flat prompt vs blackboard summary · no self-consistency.

- [ ] Bootstrap CIs over seeds; 60 episodes is small — say so
- [ ] `make reproduce` regenerates every number and figure from logs
- [ ] **GATE 6:** results table + ablation table + 4 figures, reproducible from a clean clone.

---

## 6. Repository layout (single project)

```
luminary-agent/
├── README.md                     # 90-second demo GIF at the top
├── pyproject.toml                # uv, single package
├── Makefile                      # setup / agc / run / eval / replay / reproduce
├── external/virtualagc/          # git submodule, pinned, never edited
├── src/luminary_agent/
│   ├── agc/          client.py channels.py dsky.py registers.py coredump.py
│   │                 actuators.py uplink.py build.py
│   ├── plant/        dynamics.py propulsion.py gravity.py sensors.py terrain.py
│   ├── sim/          loop.py clock.py blackboard.py events.py recorder.py replay.py
│   ├── policies/
│   │   ├── base.py               # the Agent protocol — define in Track A
│   │   ├── null.py scripted.py pid.py
│   │   └── llm/      planner.py executor.py reflector.py memory.py
│   │                 tools.py backend.py prompts/
│   ├── safety/       monitor.py
│   ├── viz/          rerun_viewer.py profile.py dsky_panel.py figures.py
│   ├── scenarios/    generator.py definitions/*.yaml
│   └── eval/         metrics.py runner.py report.py
├── tests/            unit (sensors, dynamics) + integration (gate criteria)
├── docs/             architecture.md agc-integration.md flight-contexts.md
│                     agentic-patterns.md results.md
└── results/          logs/ figures/ tables/
```

Every policy implements the same protocol so swapping is a config line. Prompts are versioned
files with a hash logged per episode. Every episode log is self-describing (scenario seed, policy
config, model hash, git SHA, **clock mode**) — otherwise the results table rots within a week.

---

## 7. Milestones

| Week | Track A (now) | Track B (after course) | Gate |
|---|---|---|---|
| 1 | Repo + yaAGC running Luminary 099 | — | Mission timer read from Python |
| 2–4 | Plant, IMU, closed loop + clock/recorder/debug viewer | — | AGC-commanded descent, no alarms |
| 4–5 | Flight-context taxonomy from NTRS | — | Every knob traces to a cited event |
| 5–6 | Baselines + 60 frozen scenarios | — | Baselines fail some |
| 7–9 | — | Agent: tools, hierarchy, safety, memory | Nominal landing, no vetoes |
| 10 | Full 3D + DSKY replay | — | Scrub a crash in one window |
| 11–12 | — | Eval + ablations | Reproducible results table |

Slip budget: 2 weeks. If Phase 1 eats it, take the fallback guidance path — do not extend.

---

## 8. What makes this defensible rather than a toy

- The original 1969 rope is *actually executing* and its DSKY output is visible in the replay.
  Verifiable on screen, not claimed in a README.
- The scenario set is derived from documented Apollo failure modes with citations, not invented.
- The agent works under a real latency constraint that forces a hierarchical design, and the
  ablation quantifies what that hierarchy buys. Better: the same policy runs with the constraint
  (`realtime`) and without it (`stepped`, §3.1), so the cost of real-time pressure is *measured*
  rather than asserted — and pausing does not weaken the claim, it turns it into a result.
- Any episode can be replayed exactly, at true speed, with the AGC display, the terrain, the
  trajectory and the agent's reasoning on one timeline (§3.2, §3.3). Nothing has to be taken on
  trust; the failure is on screen at the tick it happened.
- The safety layer has veto power over the model, and you report how often it fires.
- 60 frozen seeds, four policies, six ablations, bootstrap CIs.
- Runs on one laptop, no API key, and `make reproduce` proves it.
- If the agent underperforms, the environment and benchmark stand alone as the contribution.

## 9. Traps

- Hand-patching erasable memory instead of using the uplink path — kills reproducibility and the
  historical claim at once.
- 6-DoF before 3-DoF closes: you will not be able to separate an integrator bug from an IMU sign
  error from a wrong channel bit.
- Letting the LLM see raw telemetry — token cost explodes, quality drops, latency budget dies.
- Tuning on the frozen 60. That is what the 15-episode dev set is for.
- Building the polished 3D viewer in week 3 because it is more fun than the IMU model. It is, and
  it is also how this project dies. The Phase 1b *debug* viewer is the exception — build that,
  including the 2D terrain profile (§3.3), which is an hour of work and answers the only question
  that matters early. The 3D scene, the textured Moon and the DSKY replica are Phase 5. If you
  find yourself picking colours before Gate 1 has passed, stop.
- Letting wall-clock assumptions leak outside `sim/clock.py` — a `time.sleep` in the plant or a
  timestamp taken in a policy, and `stepped` and `replay` modes quietly stop meaning anything.
- Believing `stepped` mode makes the run deterministic enough to re-simulate bit-exactly. Replay
  the log; do not re-run and expect the same numbers.
- Waiting for the course to finish before starting. Track A is 8 of the 12 weeks.
