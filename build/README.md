# The map build pipeline

**Status: all three halves are wired. The compression pass has not run for real yet — no DXT
compressor exists on the dev box — so its first execution will be on CI.**

## The pieces

| | what it does |
|---|---|
| `vendor/xonotic-map-compiler` | upstream's Perl wrapper, **unmodified**. Drives q3map2 through the phases each map's `.map.options` asks for |
| `vendor/cached-converter.sh` | upstream's asset converter, **unmodified**. PSNR-picked DXT format per texture, content-addressed cache |
| `vendor/compress-texture` | upstream's compressor front-end. **One edit**, marked `VORTEX DIVERGENCE` — see the bug below |
| `map-compiler-config.pl` | the wrapper's config, installed to `~/.xonotic-map-compiler`. All paths from the environment, so the vendored copies need no edits |
| `compile-map.sh` | compiles one map, moves products into `builds/q3map2/<map>/`. Replaces upstream's `-optionsfile` script, which hardcodes a `misc/tools/` path we do not have |
| `compress-textures.sh` | compresses `textures/` and `models/` to `builds/dds/dds/…` |
| `publish.py` | merges the three inputs into per-role archives + manifest. Imports `split-pack.py` for classification and notice routing, so the two cannot drift |
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

## The three halves, and why all three are needed

q3map2 produces a map's geometry, not its art. A shippable archive needs three inputs, and missing any
one of them fails quietly rather than loudly:

```
sources/**.{png,jpg}  ──[compress-textures.sh]──►  dds/textures, dds/models   ─┐
sources/**.map        ──[compile-map.sh -> wrapper -> q3map2]──►  .bsp, lm_*, mini  ├──► publish.py ──► archives
sources/{scripts,env,sound,models,gfx}  ──(copied verbatim)────────────────────┘
```

- **Geometry only** would ship a map that loads with no textures.
- **Geometry + textures** would ship a map with textures and no `.shader` files to apply them with —
  which is why `publish.py` takes `--art-from` as well.
- The classifier needs no new rules for any of it: it already keys on `map_<name>/` anywhere in a path,
  so `dds/textures/map_boil/*` goes to boil's archive and `dds/textures/exx/*` to the shared one.

`compress-textures.sh` wraps the vendored `cached-converter.sh`, which does the part worth not
reimplementing: for each texture it tries several DXT formats and picks by **measured PSNR** rather than
by a fixed rule. Its cache is content-addressed, so editing one texture recompresses one texture. DDS
rather than PNG is deliberate — the game hands these to the GPU still compressed, and re-encoding would
enlarge them on disk and multiply VRAM by four to eight (restructure section 4.3).

`env/` is excluded on purpose: skyboxes ship as JPEG, matching upstream's pack, which has `dds/textures`
and `dds/models` and no `dds/env`.

### A bug found in the vendored compressor

`compress-texture`'s nvcompress path mapped `dxt3 -> -bc3` and `dxt5 -> -bc5`. The correspondence is
DXT1=BC1, **DXT3=BC2, DXT5=BC3**, and `-bc5` is ATI2/3Dc — a two-channel format for normal maps, so a
dxt5 request produced a file with no usable colour. The PSNR picker would normally reject that in favour
of dxt1, which is exactly why it stayed hidden: it degrades quality silently instead of failing. Fixed
in the vendored copy and marked `VORTEX DIVERGENCE`; it is the only edit in that file.

### What is verified, and what is not

Verified locally: file discovery (3,229 images), the `--only` filter, the wrapper's real q3map2
invocations through a stub, `compile-map.sh`'s product handling, and `publish.py` merging all three
inputs (994 files -> 638 shared, 7 per-map, 349 prefab sources correctly dropped).

**Not verified: the compression itself.** No DXT compressor and no ImageMagick `compare` exists on this
machine, so `compress-textures.sh` has never actually compressed anything here. Its first real run will
be the CI job. Expect that run to need a tweak.
