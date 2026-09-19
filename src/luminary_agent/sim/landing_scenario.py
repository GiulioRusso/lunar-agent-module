"""Build a P63-ready landing scenario in a live (stepped) AGC.

The order matters and each step is something a crew or the ground would do, all through the
flight software's own paths: fresh start, hardware discretes, mission pad loads, REFSMMAT (+flag),
the landing site (RLS, TLAND), and the LM state vector. Nothing is written to memory directly.

Geometry (all derived from Luminary's own targets, see plant/orbit.py and sim/frames.py):
  * the start is on a descent ellipse whose perilune -- the ignition point -- has altitude
    15.4 km and speed VIGN = 1699.52 m/s, `time_to_perilune` before ignition;
  * the landing site is RIGNZ = 440,015 m of ground range beyond perilune;
  * TLAND is perilune + GUIDDURN (664.4 s), the guidance duration Luminary subtracts to get its
    first ignition-time guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.landing_setup import (
    REFSMBIT_MASK,
    refsmmat_words,
    rls_words,
    set_flag_bit,
    tland_words,
)
from luminary_agent.agc.loads import padload_words, plan_loads, run_plan
from luminary_agent.agc.padloads import load_padloads
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.state_vector import load_csm_state_vector, load_lm_state_vector
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.agc.uplink import Updater
from luminary_agent.plant.discretes import Discretes
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.lunar_orientation import Mat
from luminary_agent.plant.orbit import DescentOrbit
from luminary_agent.sim.frames import LunarFrame

VIGN_MS = 1_699.5218  # 16.9952 m/cs, Luminary pad load
RIGNZ_M = 440_015.0  # ground range from ignition to the site, pad load
GUIDDURN_S = 664.4  # THE_LUNAR_LANDING.agc
PERILUNE_ALT_M = 15_400.0
CSM_ALT_M = 111_000.0  # ~60 nmi circular parking orbit
NU0_RAD = -0.29  # true anomaly at the start: ~5 minutes before perilune


@dataclass(frozen=True)
class DescentScenario:
    perilune_alt_m: float = PERILUNE_ALT_M
    perilune_speed_ms: float = VIGN_MS
    nu0_rad: float = NU0_RAD
    mass_kg: float = 15_000.0
    ground_range_m: float = RIGNZ_M

    @property
    def orbit(self) -> DescentOrbit:
        return DescentOrbit.with_perilune_speed(self.perilune_alt_m, self.perilune_speed_ms)

    @property
    def start_state(self) -> PlanarState:
        return self.orbit.state_at(self.nu0_rad, self.mass_kg)

    @property
    def time_to_perilune_s(self) -> float:
        return self.orbit.time_to_perilune_s(self.nu0_rad)

    @property
    def theta_site(self) -> float:
        """Site angle in the plant plane: the arc to perilune plus the ground range beyond it."""
        return -self.nu0_rad + self.ground_range_m / R_MOON


@dataclass(frozen=True)
class LandingSetup:
    scenario: DescentScenario
    frame: LunarFrame
    refsmmat: Mat
    now_cs: int
    t_land_cs: int


async def prepare_landing(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    scenario: DescentScenario | None = None,
) -> LandingSetup:
    """Take a freshly-booted stepped AGC to the moment just before `V37E63E`."""
    scenario = scenario or DescentScenario()
    dsky = SteppedDsky(agc, client)
    updater = Updater(agc, client)

    await dsky.fresh_start()
    await client.write_channels(Discretes(lr_position_1=True).channel_words())
    await agc.step(60_000)  # T4RUPT mirrors the discretes within 480 ms

    entries = {n: p.words for n, p in load_padloads().items() if p.is_landing and p.words}
    await run_plan(updater, plan_loads(padload_words(symbols, entries)))
    await set_flag_bit(updater, agc, symbols, "FLAGWRD3", REFSMBIT_MASK)

    now_cs = (await agc.coredump()).clock_cs
    t_land_cs = now_cs + round((scenario.time_to_perilune_s + GUIDDURN_S) * 100)
    frame = LunarFrame.from_moon(t_land_cs)
    refsmmat = frame.landing_refsmmat(scenario.theta_site)

    await updater.v71(symbols.ecadr("REFSMMAT"), refsmmat_words(refsmmat))
    await updater.v71(symbols.ecadr("RLS"), rls_words(frame.rls(scenario.theta_site, t_land_cs)))
    await updater.v71(symbols.ecadr("TLAND"), tland_words(t_land_cs))
    sv = frame.state_vector(scenario.start_state, float(now_cs))
    await load_lm_state_vector(updater, symbols, sv)
    await agc.step(80_000)  # let INTWAKEU install the state vector

    # The CSM, in a circular lunar orbit in the same plane and near the LM's start point.
    v_csm = math.sqrt(MU_MOON / (R_MOON + CSM_ALT_M))
    csm = PlanarState(CSM_ALT_M, 0.0, 0.0, v_csm, 28_000.0)
    await load_csm_state_vector(updater, symbols, frame.state_vector(csm, float(now_cs)))
    await agc.step(80_000)
    return LandingSetup(scenario, frame, refsmmat, now_cs, t_land_cs)
