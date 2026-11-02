"""luminary-agent: a flight director closing the loop around the real Apollo 11 flight software.

Package map (each sub-folder is a Python package; read the module docstrings for details):

    agc/        talking to the emulated Apollo Guidance Computer (yaAGC): build it, start it,
                exchange I/O-channel packets over TCP, type on its keyboard (DSKY), read its memory
    plant/      the simulated Lunar Module and Moon: physics, engine, sensors, radar, terrain
    sim/        the closed loop tying plant and AGC together, one 20 ms tick at a time, plus the
                pre-ignition setup, the snapshot cache, the episode log and the agent interface
    policies/   who makes decisions (null = pure Luminary, scripted = fixed takeover rule)
    safety/     the deterministic monitor that can override any policy
    scenarios/  seeded per-episode differences between the real world and what the AGC was told
    eval/       run one or many episodes in parallel, score them, print tables
    viz/        the pygame window: live view during a run, or replay of a recorded log
    lem/        the 3-D Lunar Module mesh drawn by the window
    __main__.py the `luminary` command line (fly / view / eval / agc / snapshot)
"""
