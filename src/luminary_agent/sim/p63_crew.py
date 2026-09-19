"""The crew's part of starting P63, answered through the DSKY (APOLLO_AGENT_PLAN.md ledger).

Mapped from the flight software's own prompts, each of which is a decision an agent will
eventually make:

  V37E 63E          start the landing program; IGNALG runs ~60 s (no display)
  V06 N61           "reset your event timer to agree with TIG"            -> V33E  (proceed)
  V50 N25, R1=14    checklist 00014: PROCEED = IMU fine align (needs star sightings),
                    ENTER = skip                                          -> ENTR
  V50 N18           "please perform automatic maneuver" to the burn attitude -> V33E
  V06 N18 (static)  the maneuver is running (KALCMANU)
  V50 N18 (again)   the maneuver is finished; ENTER ends R60             -> ENTR

Preconditions this cannot supply itself: the DAP mode switch at AUTO (plant/discretes.py --
without it R60LEM re-requests the maneuver forever, silently), and a CSM state vector
(sim/landing_scenario.py -- without it P41SPOT's CSMPREC raises alarm 1703).

Attitude: there is no attitude dynamics yet, so the CDU registers are *seeded* at the desired
burn attitude (Luminary's THETAD) before the maneuver is approved. R60LEM then finds the vehicle
already there and the maneuver is a no-op. That is a stepping stone, not a vehicle that rotates.
"""

from __future__ import annotations

from luminary_agent.agc.cdu import desired_gimbal_counts, seed_cdus
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import SymbolTable

CHUNK_STEPS = 20_000  # ~0.4 s of AGC time per look at the display


class CrewProcedureError(RuntimeError):
    pass


async def wait_for_display(
    agc: AgcProcess,
    client: AgcClient,
    verb: int,
    noun: int,
    max_chunks: int = 400,
    seen_verb: int | None = None,
) -> None:
    """Step until the DSKY shows V<verb> N<noun> (having first shown `seen_verb`, if given)."""
    seen = seen_verb is None
    for _ in range(max_chunks):
        await agc.step(CHUNK_STEPS)
        d = client.dsky
        if seen_verb is not None and d.verb_number == seen_verb:
            seen = True
        if seen and d.verb_number == verb and d.noun_number == noun:
            return
    d = client.dsky
    raise CrewProcedureError(
        f"waited for V{verb} N{noun}, last saw V{d.verb_number} N{d.noun_number} "
        f"R1={d.r1} R2={d.r2} R3={d.r3}"
    )


async def start_p63(
    agc: AgcProcess, client: AgcClient, symbols: SymbolTable
) -> tuple[int, int, int]:
    """Run the P63 crew prompts to the point where ignition preparation proceeds unattended.

    Returns the burn-attitude gimbal counts the CDUs were seeded to.
    """
    dsky = SteppedDsky(agc, client)
    await dsky.verb(37)
    await dsky.enter_decimal(63)

    await wait_for_display(agc, client, verb=6, noun=61)  # IGNALG done
    await dsky.verb(33)  # proceed

    await wait_for_display(agc, client, verb=50, noun=25)
    await dsky.key("ENTR", 8_000)  # skip the fine alignment

    await wait_for_display(agc, client, verb=50, noun=18)
    burn_attitude = desired_gimbal_counts(await agc.coredump(), symbols)
    await seed_cdus(client, agc, burn_attitude)
    await dsky.verb(33)  # approve the automatic maneuver

    await wait_for_display(agc, client, verb=50, noun=18, seen_verb=6)  # maneuver finished
    await dsky.key("ENTR", 8_000)  # end R60
    return burn_attitude
