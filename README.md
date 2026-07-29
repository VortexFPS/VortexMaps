# VortexMaps

Map sources for [Vortex Arena](https://github.com/VortexFPS/VortexArena), and the pipeline that turns
them into the map archives the game fetches.

Nothing here is needed to *play* the game, or to build it. The game repository fetches compiled map
archives from this repository's releases; it never reads this tree. Clone this only to author or
rebuild a map.

## Layout

```
sources/          Radiant/editor inputs — never shipped to players
  maps/           .map geometry, .map.options compile flags, .mapinfo, .waypoints, .rtlights
  textures/       source textures (PNG)  — 17 map_<name>/ sets + 36 shared sets
  models/         .ase / .md3 / .obj prefabs
  scripts/        .shader material scripts + shaderlist.txt
  env/            skybox sets
  sound/          map-specific audio

build/
  q3map2.toolchain   what each stock map was actually compiled with (see "Reproducibility")

builds/           generated, gitignored — published as release assets, never committed
```

`sources/` is **type-rooted**, mirroring the shape Xonotic content is authored in and the shape q3map2
expects. It deliberately is *not* split per map. Measuring the tree is what settled that: of 4,193
content files only 589 (14%) are attributable to a single map, 86% is shared, only 17 of the 31 maps
have any dedicated texture directory, and no map references zero shared sets — each pulls 10–16 of the
36 shared sets. Maps are views over a shared library, not modular units. A per-map split would have
filed 86% of the tree into one bucket and made a build-time overlay mandatory, because q3map2 resolves
`textures/foo/bar` relative to a single game directory. Type-rooted `sources/` **is** a valid q3map2
game directory, so no overlay is needed.

A consequence worth knowing: third-party Xonotic maps drop straight in, because this is the shape they
already ship in.

## Textures are PNG, not TGA

The whole tree was re-encoded from TGA to PNG: 2,940 MiB down to 1,204 MiB, with every file verified by
comparing decoded pixels rather than trusting the encoder's exit code.

This is transparent to q3map2. Its image loader (`tools/quake3/q3map2/image.c`) probes
`.tga` → `.png` → `.jpg` → `.dds`, so a shader naming `textures/map_stormkeep/brickfloor` finds the PNG
with no edit to any `.map`, `.shader` or compile flag. libpng is a hard dependency of the q3map2 build
(`find_package(PNG REQUIRED)`), not an option. The game's own VFS probes in the same order, for the same
reason.

One file needed an independent decoder: `textures/phillipk1x/trim/pk01_trims01b_glow.tga` is a valid
256×512 24-bit TGA that ffmpeg misreports as 300×216 paletted. It was converted with PIL and verified
against the raw header. The converter now cross-checks ffmpeg against the TGA header and refuses rather
than writing a wrong PNG.

## Reproducibility

`build/q3map2.toolchain` records the compiler version and flags for each stock map, taken from its
`.map.options`. It is **not** a single pin, because the history does not support one: the 31 stock maps
were compiled with **29 distinct q3map2 versions** between them, and with widely varying flags —
`-samplesize`, `-bouncescale`, `-exposure`, `-areascale`, `-scale`, `-dirty`.

So the shipped BSPs are historical artifacts rather than reproducible build output. A rebuild produces a
correct, playable map with *different* lightmaps. That is fine for the escape-hatch case (rebuilding when
a release asset is unavailable) and it is worth knowing before treating any rebuild as a byte-for-byte
baseline.

## Licensing

The content is Xonotic's, under GPL version 3 or any later version — see
[`VortexArena/data/licenses/`](https://github.com/VortexFPS/VortexArena/tree/main/data/licenses) for the
grant and the licence texts.

Some items carry their own notice next to the art, and those notices matter because they cover work
Team Xonotic redistributes without owning:

- `textures/phillipk1x/_GPL.txt`, `textures/phillipk2x/_GPL.txt` — Philip Klevestav's Quake IV texture
  sets, relicensed GPL v2 or later, © 2003–2010. **503 files of this art ship in the compiled packs.**
- `maps/atelier.license.txt` — GPL v3 or later, © 2011 Pawel 'ShadoW' Chrapka
- `maps/trident.LICENSE`, `models/xonotic_jumppad01/…_readme.txt`, `sound/map_xoylent/sources.txt`,
  `textures/map_boil/credit.png`

**The publish step must copy these into the archives carrying the art they cover.** They live in a tree
players never fetch, while the art does ship — so without that step a release distributes those textures
with the copyright notice left behind here.
