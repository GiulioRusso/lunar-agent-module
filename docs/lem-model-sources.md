# LEM model: where the shape comes from

The vehicle drawn by the simulator is `src/luminary_agent/lem/lem_mesh.npz`: a **9,127-triangle,
75 KB, flat-shaded mesh** built once from NASA's public 3D model of the Apollo Lunar Module. The
simulator loads that small file at run time (`lem.mesh.load_lem_mesh()`); it never reads the
original GLB. Antennas and dishes are removed; the descent stage, ascent stage, four legs with
struts and footpads, ladder, engine bell and the RCS thruster clusters are kept.

## Source and licence

- **Source:** NASA 3D Resources, "Apollo Lunar Module",
  https://science.nasa.gov/3d-resources/apollo-lunar-module/ . The file is
  `docs/Apollo Lunar Module.glb` (Draco-compressed glTF, ~97k triangles, exported from Blender).
- **Credit:** NASA.
- **Licence: not yet confirmed.** The page was named by the repository owner; it has not been
  fetched from here (no network). NASA-produced media is generally not copyrighted, but the
  statement on the model's own page is what counts.
  **TODO (owner): paste the licence/usage statement from that page here** and keep the credit line.
  Until then, do not redistribute `lem_mesh.npz` or the GLB outside this repository.

## How the mesh is made (reproducible, no hand edits)

`uv run --with DracoPy python -m luminary_agent.lem.glb_mesh "docs/Apollo Lunar Module.glb"`

1. Decode every primitive; rotate to the model frame; rescale so the overall height is 7.04 m.
2. Drop specks (< 5 cm), everything whose lowest point is above the ascent-stage roof (antennas,
   dishes) and thin tall rods in the roof region (whips).
3. Simplify each part by vertex clustering (cell = 15 % of its middle extent, 3-12 cm), keeping the
   material colour of every face.

`python -m luminary_agent.lem.glb_reference` writes `docs/lem-glb-reference.json` (silhouette
hulls, pad layout, profile of the *full* model, antennas included), which `tests/unit/
test_lem_mesh.py` compares the mesh against.

Frame: metres, `+x` forward (toward the ladder leg), `+y` left, `+z` up, footpad soles at `z = 0`.
The mesh is 6.36 m tall without antennas (7.04 m with them), 9.0 m across the footpad rims.

## What is and is not verified

| Item | Value | Status |
|---|---|---|
| Overall height incl. antennas | 7.04 m (23 ft 1 in) | **[doc]** not checked; Apollo 11 press kit reportedly 22 ft 11 in (6.99 m) |
| Gear span, footpad rims | 9.0 m in the mesh | **[doc]** published 9.07-9.42 m depending on what is measured; the mesh agrees with the low end |
| Leg layout: 4 legs at 0/90/180/270°, ladder on the forward leg | as in the mesh | consistent with photographs recalled and with the NASA model |
| Descent-stage width | ~5.8 m in the mesh | **conflict**, see below |

`[doc]` = a published source is named but **has not been opened and checked**. The recalled
figures come from memory of: (1) NASA Apollo 11 Press Kit (Release 69-83K); (2) Grumman *Apollo
Lunar Module News Reference*; (3) NASA *Apollo Operations Handbook, LM-10 and Subsequent, Vol. I*;
(4) NTRS Lunar Module structure and landing-gear reports; (5) NASM LM-2 / LM-9 object records.

**Unresolved conflict.** The absolute scale here rests on "overall height = 7.04 m". At that scale
the NASA model's descent stage is ~5.8 m across, while I remember ~4.2 m for the real stage. Scaled
so the stage is 4.2 m, the model would be ~5.0 m tall and ~6.4 m across, far below the published
7.04 / 9.07 m. Either the remembered stage width or the remembered height/span is wrong, or the
NASA model is not to scale; I cannot tell without a dimensioned drawing. The **shape** (proportions
between parts) is NASA's; the **absolute size** is a choice pinned to the published height. It
matters only for how big the vehicle looks next to the terrain grid, not for the simulation.

## Checklist for a human

- [ ] Paste the licence statement from the NASA page (see above).
- [ ] Check overall height and gear span against source 1 or 2 (page/table number here).
- [ ] Check the stage widths against source 2 or 3 to settle the conflict.
