# The map build pipeline

**Status: the publish half is built and proven; the compile half is not.**

## What works

`split-pack.py` — bootstraps the per-role archives from Xonotic's bundled pk3s. This produced the
published `maps-2026.07` release (one shared archive + 31 per-map), and the game repo's
`data/maps.lock.json` pins its output. It also carries the per-item licence notices out of `sources/`
into whichever archive holds the art they cover, which is a correctness requirement rather than a
nicety — see its docstring.

`q3map2.toolchain` — the compiler pin plus each map's own compile flags, lifted from its
`.map.options`. Per-map flags are deliberate authoring decisions and get passed through unchanged.

## What is not built, and the decision it needs

`.github/workflows/build-maps.yml.draft` is a complete workflow — build q3map2 once, matrix one job per
map so each gets its own 6-hour budget, publish per-role archives — **parked as `.draft` so it cannot
run**, because it calls two scripts that do not exist: `build-map.py` and `publish.py`.

`build-map.py` was written and then deleted, because it was wrong in a way worth recording.
**`.map.options` is not a q3map2 command line.** It is argv for upstream's Perl wrapper,
`misc/tools/xonotic-map-compiler`, and the semantics are entirely different:

- `-bsp`, `-light`, `-vis`, `-minimap` are *mode selectors*: they choose which phase's flag list the
  following flags accumulate into. They are not standalone invocations separated by `+`.
- `-sRGB` is a wrapper concept that expands to `-sRGBtex -sRGBcolor` on the bsp phase and
  `-sRGBtex -sRGBcolor -sRGBlight` on light.
- `-scale <n>` sets a wrapper `scalefactor`, not a q3map2 flag.
- Ordering, per-phase timeouts and a `-minmax` override read out of `<map>.mapinfo` are all wrapper
  behaviour (`xonotic-map-compiler-optionsfile` supplies the last one).

Treating the file as q3map2 flags produces invalid invocations — a stage of just `-sRGB` does nothing,
and `-scale 0.9` lands on the wrong phase. So the compile step has to either **use upstream's wrapper**
(vendor the two Perl scripts; adds a Perl dependency, and they are GPL so that is fine) or **port its
semantics deliberately**. That is a decision, not a detail, which is why nothing is committed that
pretends to do it.

Until then, map archives are produced by `split-pack.py` from the shipped pk3s, which is sufficient for
the frozen 0.8.6 set and blocks nothing in the game repo.
