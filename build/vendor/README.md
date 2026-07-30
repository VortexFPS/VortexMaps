# Vendored map compiler

`xonotic-map-compiler` and `xonotic-map-compiler-optionsfile`, copied **unmodified** from Xonotic's
`misc/tools/` at 0.8.6. GPL v3 or later, © the Xonotic contributors — the same grant as the rest of the
content here (see `data/licenses/` in VortexArena).

## Why vendored rather than reimplemented

Because `sources/maps/<map>.map.options` is argv for *this wrapper*, not a q3map2 command line, and the
difference is not cosmetic:

- `-bsp`, `-vis`, `-light`, `-minimap` are **mode selectors**. They choose which phase's flag list the
  following flags accumulate into. They are not separate invocations delimited by `+`.
- `-sRGB` expands to `-sRGBtex -sRGBcolor` on the bsp phase and adds `-sRGBlight` to light.
- `-scale <n>` sets a wrapper `scalefactor`, driving a separate `-scale` pass over the built `.bsp`
  followed by a rename. It is not a q3map2 flag.
- Per-phase timeouts, phase ordering (`-order`), and a `-minmax` override read out of
  `<map>.mapinfo` (that last one supplied by `-optionsfile`) are all wrapper behaviour.

An earlier attempt read the options as q3map2 flags. A dry-run showed what that costs: erbium's custom
`-samplesize`/`-bouncescale` flags silently vanished, and `-sRGB` became a phantom fifth stage that
would have run q3map2 with no phase at all. Reimplementing this correctly means porting ~316 lines of
semantics with no test to check it against; vendoring a proven GPL script means neither.

Same reasoning as not forking q3map2 for PNG support: the existing tool already does the job.

## How it is driven

The wrapper fabricates a Xonotic-style layout rather than requiring one. It `chdir`s into the map's
directory and symlinks `<tmpdir>/data` → the map's parent, then passes q3map2 **two** `-fs_basepath`
entries: that tmpdir, and `$XONOTICDIR`. So our type-rooted `sources/` works as-is, with no overlay.

Two consequences worth knowing:

1. **It needs working symlinks**, so it runs on the Linux CI runner. On a Windows dev box it needs
   developer mode or an elevated shell.
2. **`$XONOTICDIR` must point at a tree containing the game's core data**, because a few texture sets a
   map references live there rather than in map sources. Measured across all 31 maps: exactly **one** of
   54 referenced sets is core-only (`domination`, 1.4 MB), plus core's `scripts/` at 124 KB. So the CI
   job sparse-checks out just those from VortexArena rather than the whole 900 MB content tree.

Configuration goes in `~/.xonotic-map-compiler`, which the script `do`s after its own defaults — that is
the supported override hook, so the vendored copies stay byte-identical to upstream and a future
refresh is a straight recopy. `build/map-compiler-config.pl` is what CI installs there.
