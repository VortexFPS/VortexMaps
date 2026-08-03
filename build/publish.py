#!/usr/bin/env python3
"""Package compiled map output into the per-role archives the game fetches, and emit the manifest.

    python build/publish.py builds/q3map2 --out dist --version 2026.08 --sources sources

THE pipeline entry point: a release is produced by compiling sources/ with q3map2 and packaging the
result here. Nothing reads Xonotic's repositories — the one-off bootstrap that did (build/split-pack.py)
has been retired, and its classification half now lives in build/packlib.py.

Output, per the restructure plan section 5.3.1:

    shared-<version>.pk3     art no single map owns
    <map>.pk3   xN    that map's own files
    manifest.json            what data/maps.lock.json is generated from
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import packlib as sp

HERE = pathlib.Path(__file__).resolve().parent


# sources/ holds LOSSLESS MASTERS beside the shipped derivatives: .png next to .jpg/.dds, .wav next to
# .ogg. The release must carry the derivative only — the engine reads that, and shipping both roughly
# doubles the affected content (sources/textures alone is 2975 files / 1.2 GB against the 168 loose
# textures upstream actually ships). Keyed on what upstream ships: dds, jpg, ogg.
#
# Deliberately a PREFERENCE, not a denylist: a master with no derivative IS the shipped form and passes
# through. That is what keeps this from becoming the next silent drop — the same failure mode that cost
# us .waypoints.cache. See VortexArena planning/bot-ai-parity-2026-08-03.md.
MASTER_FORMATS = {
    ".png": (".dds", ".jpg"),
    ".tga": (".dds", ".jpg"),
    ".jpg": (".dds",),   # a .jpg is itself the shipped form for skyboxes/levelshots, but a texture that
                         # HAS a .dds ships compressed only — upstream keeps just the 168 without one
    ".wav": (".ogg",),
}


def shipped_counterpart(rel: str, files: dict, art_from: pathlib.Path) -> bool:
    """True when `rel` is a master whose shipped derivative is already available, so skip it."""
    stem, dot, ext = rel.rpartition(".")
    if not dot:
        return False
    for alt in MASTER_FORMATS.get("." + ext.lower(), ()):
        if alt == ".dds":
            if f"dds/{stem}{alt}" in files:
                return True
        elif f"{stem}{alt}" in files or (art_from / f"{stem}{alt}").is_file():
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builds", type=pathlib.Path, help="per-map q3map2 output (builds/q3map2)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--sources", type=pathlib.Path, default=HERE.parent / "sources")
    ap.add_argument("--dds", type=pathlib.Path, default=None,
                    help="compressed texture tree from compress-textures.sh (builds/dds), already "
                         "type-rooted as dds/textures/...")
    ap.add_argument("--art-from", type=pathlib.Path, default=None,
                    help="source tree to copy the non-compressible shipped art from: scripts/, env/, "
                         "sound/, models/ meshes. Normally the same as --sources")
    ap.add_argument("--expect-packs", type=int, default=None,
                    help="fail unless exactly this many archives are produced (31 for the stock set: "
                         "30 maps from sources/maps/*.map, plus the shared archive)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.builds.is_dir():
        sys.exit(f"error: no build directory at {args.builds}")

    # Flatten every input into archive-relative paths — the shape classify() expects.
    files: dict[str, pathlib.Path] = {}

    # 1. q3map2 output: builds/q3map2/<map>/<type-rooted>. Strip the per-map directory, because archive
    #    content must be type-rooted (maps/, gfx/) rather than nested under the map name.
    for path in sorted(args.builds.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(args.builds).as_posix()
        parts = rel.split("/", 1)
        files[parts[1] if len(parts) == 2 else rel] = path

    # 2. Compressed textures. Already type-rooted (dds/textures/..., dds/models/...), so they merge in
    #    as-is and the existing classifier splits them: dds/textures/map_boil/* to boil's archive,
    #    dds/textures/exx/* to the shared one.
    if args.dds is not None:
        if not args.dds.is_dir():
            sys.exit(f"error: --dds given but no directory at {args.dds}")
        for path in sorted(args.dds.rglob("*")):
            if path.is_file():
                files.setdefault(path.relative_to(args.dds).as_posix(), path)

    # 3. The shipped art that is neither compiled nor compressed: shader scripts, skybox JPEGs, sounds,
    #    and model meshes. Without these a rebuilt archive has geometry and compressed textures but no
    #    materials to apply them with. Sources (.map, .ase, .map.options) are excluded by classify().
    #
    #    `maps` is in this list for the AUTHORED, NON-COMPILED files that live beside each .map:
    #    <map>.waypoints and <map>.waypoints.hardwired (the bot navigation graph, and the map author's
    #    hand-placed jump/teleport/drop links that no tracewalk can re-derive), plus <map>.mapinfo and the
    #    levelshot. q3map2 emits none of them, so without this a rebuilt map ships a .bsp with no bot
    #    graph at all: bots fall back to deriving links by tracewalk at load, which drops every hardwired
    #    link and leaves a large share of a map's waypoints as nodes a bot can walk into and never out of.
    #    The true sources in the same directory (.map, .map.options, .rb, .pl) are dropped by classify().
    #    Compiled output still wins — this gather is setdefault and builds/ is read first.
    #    See VortexArena planning/bot-ai-parity-2026-08-03.md D1/D2.
    if args.art_from is not None:
        if not args.art_from.is_dir():
            sys.exit(f"error: --art-from given but no directory at {args.art_from}")
        SHIPPED_ART = ("scripts", "env", "cubemaps", "sound", "models", "gfx", "maps", "textures")
        for top in SHIPPED_ART:
            base = args.art_from / top
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(args.art_from).as_posix()
                if shipped_counterpart(rel, files, args.art_from):
                    continue
                files.setdefault(rel, path)

    if not files:
        sys.exit(f"error: {args.builds} contains no files")

    bsps = {pathlib.PurePosixPath(n.lower()).stem for n in files if n.lower().endswith(".bsp")}
    print(f"{len(files)} files, {len(bsps)} maps with a .bsp")
    if not bsps:
        sys.exit("error: no .bsp in the build output — nothing was compiled")

    buckets: dict[str, list[str]] = collections.defaultdict(list)
    dropped = 0
    for name in files:
        kind, mapname = sp.classify(name, bsps)
        if kind == "source":
            dropped += 1
        elif kind == "map":
            buckets[f"map:{mapname}"].append(name)
        else:
            buckets["shared"].append(name)

    # CONSERVATION: every runtime file that entered the pipeline must leave it in exactly one archive.
    #
    # This is the guard the pipeline was missing. Upstream Xonotic has no packaging step at all — its
    # .pk3dir IS the shipped pk3, so nothing can be lost in transit. We split by role (a 597 MB single
    # asset means changing one map re-downloads all 31), and the split needs a classifier, and a
    # classifier that DROPS by extension is silently lossy: `.waypoints.cache` and `.waypoints.hardwired`
    # sat on that drop list for the life of the repo, so every shipped map carried bot waypoints with no
    # links and no hand-authored jumps. Nothing failed; the files just were not there.
    #
    # So: reconcile. Anything classify() drops must match an explicitly reviewed pattern. A new file type
    # nobody thought about fails the build instead of vanishing from the release.
    unaccounted = sorted(n for n in files if sp.classify(n, bsps)[0] == "source"
                         and not sp.is_known_drop(n))
    if unaccounted:
        sys.exit(
            "error: these files were dropped as 'source' but match no reviewed drop pattern.\n"
            "       Either add them to packlib.KNOWN_DROPS with a reason, or stop dropping them.\n"
            + "".join(f"  {n}\n" for n in unaccounted[:40])
            + (f"  ... and {len(unaccounted) - 40} more\n" if len(unaccounted) > 40 else "")
        )

    maps = sorted(k[4:] for k in buckets if k.startswith("map:"))
    if set(maps) != bsps:
        sys.exit(
            "error: map buckets disagree with the .bsp set\n"
            f"  buckets without a bsp: {sorted(set(maps) - bsps)}\n"
            f"  bsps without a bucket: {sorted(bsps - set(maps))}"
        )

    # The game pins an exact pack list in data/maps.lock.json, and a release with fewer packs does not
    # fail anywhere downstream — the fetcher just installs what it is told about, and the missing maps
    # quietly stop existing. So assert the count here, where we still know what we built.
    produced = len(maps) + 1  # + the shared archive
    if args.expect_packs is not None and produced != args.expect_packs:
        sys.exit(
            f"error: produced {produced} archives, expected {args.expect_packs}.\n"
            f"       maps built: {len(maps)} ({', '.join(maps)})\n"
            "       Every shipped map builds from sources/maps/<map>.map, so a short count means a\n"
            "       compile failed silently or a .map went missing from sources/."
        )
    print(f"  shared   {len(buckets['shared']):5d} files")
    print(f"  per-map  {sum(len(v) for k, v in buckets.items() if k != 'shared'):5d} files")
    if dropped:
        print(f"  dropped  {dropped} build-residue files")

    # Notice routing: these sit beside the art in sources/, which players never fetch, while the art
    # ships. See packlib.find_notices' docstring.
    notices = sp.find_notices(args.sources)
    routing: dict[str, list[tuple[str, pathlib.Path]]] = collections.defaultdict(list)
    unrouted = []
    for rel, path in sorted(notices.items()):
        targets = sp.notice_targets(rel, buckets)
        if not targets:
            unrouted.append(rel)
        for key in targets:
            routing[key].append((rel, path))
    print(f"  {len(notices)} notices, {sum(len(v) for v in routing.values())} placements")
    if unrouted:
        print(f"  {len(unrouted)} notice(s) cover no shipped art: {', '.join(unrouted)}")

    if args.dry_run:
        print("\ndry-run: nothing written")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}

    def write(archive: pathlib.Path, names: list[str], key: str) -> None:
        import zipfile

        tmp = archive.with_suffix(".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
            for n in sorted(names):
                out.write(files[n], n)
            for rel, path in routing.get(key, []):
                out.writestr(rel, path.read_bytes())
        tmp.replace(archive)

    shared = args.out / f"shared-{args.version}.pk3"
    write(shared, buckets["shared"], "shared")
    digest, size = sp.sha256_and_size(shared)
    manifest["shared"] = {"file": shared.name, "sha256": digest, "size": size}
    print(f"\nwrote {shared.name}  {size / 2**20:.1f} MB")

    for name in maps:
        archive = args.out / f"{name}.pk3"
        write(archive, buckets[f"map:{name}"], f"map:{name}")
        digest, size = sp.sha256_and_size(archive)
        manifest[name] = {"file": archive.name, "sha256": digest, "size": size}

    per = sorted(v["size"] for k, v in manifest.items() if k != "shared")
    print(f"wrote {len(maps)} per-map archives, {sum(per) / 2**20:.1f} MB total, "
          f"median {per[len(per) // 2] / 2**20:.1f} MB")

    (args.out / "manifest.json").write_bytes(
        (json.dumps({"schema": 1, "version": args.version, "archives": manifest}, indent=2) + "\n").encode()
    )
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
