# The map build pipeline

**Status: publishing works and produced the live release. Compiling works. Turning a fresh compile into
a shippable archive does not yet — see "the remaining gap".**

## The pieces

| | what it does |
|---|---|
| `vendor/xonotic-map-compiler` | upstream's Perl wrapper, vendored unmodified. Drives q3map2 through the phases each map's `.map.options` asks for. See `vendor/README.md` |
| `map-compiler-config.pl` | the wrapper's config, installed to `~/.xonotic-map-compiler`. All paths from the environment, so the vendored copy stays byte-identical to upstream |
| `compile-map.sh` | compiles one map and moves the products into `builds/q3map2/<map>/`. Replaces upstream's `-optionsfile` script, which hardcodes a `misc/tools/` path we do not have |
| `publish.py` | packages build output into per-role archives + manifest. Shares its classification and notice routing with `split-pack.py` by importing it, so the two cannot drift |
| `split-pack.py` | bootstraps the same archives from Xonotic's shipped pk3s. **This produced the live `maps-2026.07`** |
| `q3map2.toolchain` | the compiler pin, plus each map's own flags for reference |

## Why the wrapper is vendored rather than reimplemented

`.map.options` is argv for the wrapper, not a q3map2 command line, and the difference is not cosmetic:
`-bsp`/`-light`/`-vis`/`-minimap` are **mode selectors** choosing which phase's flag list follows;
`-sRGB` expands to `-sRGBtex -sRGBcolor` on bsp and adds `-sRGBlight` on light; `-scale <n>` drives a
separate pass over the built `.bsp` and a rename. Verified by watching real invocations: the wrapper
turned `-bsp + -light + -vis + -minimap + -sRGB` into a light phase carrying
`-lightmapsize 1024 … -sRGBtex -sRGBcolor -sRGBlight`, and `boil`'s `-scale 0.8` into a `-scale` pass
followed by `boil_s.bsp` → `boil.bsp`.

An earlier attempt read the options as q3map2 flags. A dry-run showed the cost: erbium's custom flags
silently vanished and `-sRGB` became a phantom stage that would have run q3map2 with no phase at all.
Same reasoning as not forking q3map2 for PNG support — the existing tool already does the job.

## How the paths resolve (and why one repo is not enough)

The wrapper fabricates a Xonotic-style layout instead of requiring one: it `chdir`s into the map's
directory and symlinks `<tmpdir>/data` → the map's parent, then hands q3map2 **two** `-fs_basepath`
entries. Verified by instrumenting a stub compiler:

```
basepath <tmpdir>            -> exposes textures/exx, textures/map_stormkeep, scripts  (i.e. sources/)
basepath $VORTEXARENA_ROOT   -> exposes data/core.pk3dir as a pack
```

So the symlink half is **entirely inside this repo** and needs nothing else. The second basepath is a
genuine cross-repo dependency, but a small one: measured across all 31 maps, exactly **one** of 54
referenced texture sets lives only in the game's core content (`domination`, 1.4 MB), plus core's
`scripts/` at 124 KB. q3map2 reads `.pk3dir` as a pack (netradiant `tools/quake3/common/vfs.c:240`), so
pointing a basepath at a VortexArena checkout is enough — no unpacking. Both repos are public, so CI
clones it with `actions/checkout` anonymously: **no token, no secret, no submodule.** The workflow takes
a blobless sparse checkout of `data/core.pk3dir` and caches it, so 31 matrix jobs do not each re-clone.

Note it needs **working symlinks**, so it runs on the Linux runner. On a Windows dev box it wants
developer mode or an elevated shell.

## The remaining gap: nothing fills the shared archive on a fresh build

Found by running the chain end to end against a stubbed compiler. **q3map2 produces a map's geometry,
not its art.** A build yields `maps/<map>.bsp`, external lightmap pages and a minimap — that is all. The
shared archive comes out empty, because the textures a map references are not build output; in the
shipped pack they are **DDS**, produced by a separate compression pass over the PNG sources. Upstream
has the tool: `misc/tools/compress-texture`.

The classic pipeline is really two independent halves:

```
sources/**.png  ──[compress-texture]──►  dds/…             ─┐
sources/**.map  ──[q3map2 via wrapper]──►  .bsp, lm_*, mini ├──► archives
sources/scripts, models, sound  ──(copied)──────────────────┘
```

`split-pack.py` sidesteps this by taking the *already-compiled* art out of Xonotic's shipped pk3s —
correct for the frozen 0.8.6 set, and what `maps-2026.07` was built from. A rebuild-from-sources needs
the compression half wired before its output is shippable, or a rebuilt map arrives with geometry and no
textures.

**So what the workflow is good for today is verifying a map still compiles.** That is worth having — it
catches a source edit that breaks the build — and it is not the same as producing a release. It only
publishes on a `maps-*` tag, so a routine run cannot mistake one for the other.
