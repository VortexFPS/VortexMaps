#!/usr/bin/env python3
"""Split Xonotic's bundled compiled-map pk3s into the per-role archives the game fetches.

One-off bootstrap for the 0.8.6 stock set. Xonotic ships all 31 compiled maps in a single 597 MB
xonotic-20230620-maps.pk3, which is past GitHub's 100 MB per-file limit for git and throws away any
chance of updating one map without re-downloading all of them. This produces what
VortexArena/data/maps.lock.json pins instead:

    shared-<version>.pk3     art no single map owns  (~405 MB: dds/, models/, sound/, scripts/, env/)
    <map>.pk3   x31   that map's own files    (~191 MB total, median ~4 MB)

Why split by role rather than purely per map: 68% of the pack is shared art. Naive per-map archives
would either duplicate that 405 MB across 31 maps, or need per-map dependency analysis. See the
restructure plan section 5.3.1.

Source material in the pack (.map, .ase, .obj and q3map2 residue) is NOT packaged — it belongs in
sources/, and shipping it to players was never intended.

    python build/split-pack.py <maps.pk3> [nexcompat.pk3 ...] --out builds/q3map2 --version 2026.07
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import sys
import zipfile

# Extensions that are build input or compiler residue, never runtime content.
SOURCE_EXT = {".map", ".ase", ".obj", ".cache", ".hardwired", ".options", ".sh", ".rb", ".bat"}

# A file belongs to map <x> if it is maps/<x>.*, maps/<x>/*, */map_<x>/*, or gfx/<x>_mini.*
RE_MAP_DIR = re.compile(r"(?:^|/)map_([^/]+)/")
RE_MINI = re.compile(r"^gfx/(.+?)_mini\.[a-z0-9]+$")


def classify(name: str, bsps: set[str]) -> tuple[str, str | None]:
    """Return (kind, map_name). kind is 'source', 'map' or 'shared'.

    `bsps` is the set of map stems that actually have a .bsp, and it is the authority. Without it,
    every stray maps/*.txt mints its own bogus archive: maps/atelier-info.txt, bromine_effectinfo.txt,
    campaignxonoticbeta.txt and tutorial_bot.txt produced four one-file "maps" that are not maps. The
    first two belong to a real map by prefix; the other two are game-wide data and belong in shared.
    """
    low = name.lower()
    if pathlib.PurePosixPath(low).suffix in SOURCE_EXT:
        return "source", None

    m = RE_MAP_DIR.search(low)
    if m and m.group(1) in bsps:
        return "map", m.group(1)
    m = RE_MINI.match(low)
    if m and m.group(1) in bsps:
        return "map", m.group(1)

    if low.startswith("maps/"):
        rest = low[len("maps/") :]
        if not rest:
            return "shared", None
        stem = rest.split("/")[0].split(".")[0]
        if stem in bsps:
            return "map", stem
        # A decorated stem like "atelier-info" or "bromine_effectinfo" belongs to the map it names.
        # Longest match wins so a hypothetical "foo" never steals "foobar"'s files.
        owners = sorted((b for b in bsps if stem.startswith(b)), key=len, reverse=True)
        if owners:
            return "map", owners[0]
        return "shared", None

    return "shared", None


# Filenames that are a licence, credit or attribution notice sitting next to the art it covers.
RE_NOTICE = re.compile(r"(licen[cs]e|_gpl|copying|credit|readme|sources\.txt)", re.IGNORECASE)


def find_notices(sources: pathlib.Path) -> dict[str, pathlib.Path]:
    """Map each notice's archive-relative path to its file in sources/.

    These notices sit beside the art in the SOURCE tree, which players never fetch, while the art they
    cover does ship. Without carrying them across, a release distributes (for one real example) 503
    files of Philip Klevestav's GPLv2-or-later textures with his copyright notice left behind. See the
    restructure plan section 5.3.1.
    """
    found: dict[str, pathlib.Path] = {}
    if not sources.is_dir():
        return found
    for p in sources.rglob("*"):
        if p.is_file() and RE_NOTICE.search(p.name):
            found[p.relative_to(sources).as_posix()] = p
    return found


def notice_targets(rel: str, buckets: dict[str, list[str]]) -> list[str]:
    """Which bucket keys carry art the notice at `rel` covers.

    Matches on the notice's directory, allowing for the dds/ prefix the compiled art uses: a notice at
    textures/phillipk1x/_GPL.txt covers dds/textures/phillipk1x/*. A notice directly in maps/ covers
    the map named by its stem.
    """
    parent = pathlib.PurePosixPath(rel).parent.as_posix()
    stem = pathlib.PurePosixPath(rel).name.split(".")[0].lower()

    if parent in ("", "maps"):
        # maps/atelier.license.txt, maps/trident.LICENSE -> that map's bucket
        return [f"map:{stem}"] if f"map:{stem}" in buckets else []

    prefixes = (f"{parent}/", f"dds/{parent}/")
    return [key for key, names in buckets.items()
            if any(n.lower().startswith(prefixes) for n in names)]


def sha256_and_size(path: pathlib.Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packs", nargs="+", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--version", required=True, help="label for the shared archive, e.g. 2026.07")
    ap.add_argument("--sources", type=pathlib.Path, default=pathlib.Path("sources"),
                    help="source tree to lift per-item licence notices from")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for p in args.packs:
        if not p.is_file():
            sys.exit(f"error: no such pack: {p}")

    # name -> (pack, ZipInfo). Later packs win on a collision, matching mount precedence.
    entries: dict[str, tuple[pathlib.Path, zipfile.ZipInfo]] = {}
    collisions = 0
    for p in args.packs:
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                if info.filename in entries:
                    collisions += 1
                entries[info.filename] = (p, info)
    print(f"{len(entries)} entries across {len(args.packs)} pack(s), {collisions} name collisions")

    # The .bsp set is the authority on what counts as a map (see classify()).
    bsps = {pathlib.PurePosixPath(n.lower()).stem for n in entries if n.lower().endswith(".bsp")}
    print(f"  {len(bsps)} maps have a .bsp")

    buckets: dict[str, list[str]] = collections.defaultdict(list)
    dropped = 0
    for name in entries:
        kind, mapname = classify(name, bsps)
        if kind == "source":
            dropped += 1
        elif kind == "map":
            buckets[f"map:{mapname}"].append(name)
        else:
            buckets["shared"].append(name)

    maps = sorted(k[4:] for k in buckets if k.startswith("map:"))
    if set(maps) != bsps:
        sys.exit(
            "error: map buckets disagree with the .bsp set\n"
            f"  buckets without a bsp: {sorted(set(maps) - bsps)}\n"
            f"  bsps without a bucket: {sorted(bsps - set(maps))}"
        )
    print(f"  shared      {len(buckets['shared']):5d} files")
    print(f"  per-map     {sum(len(v) for k, v in buckets.items() if k != 'shared'):5d} files "
          f"across {len(maps)} maps")
    print(f"  source/residue dropped {dropped} files (they belong in sources/)")

    # Route each per-item licence notice into every archive carrying art it covers.
    notices = find_notices(args.sources)
    routing: dict[str, list[tuple[str, pathlib.Path]]] = collections.defaultdict(list)
    unrouted: list[str] = []
    for rel, path in sorted(notices.items()):
        targets = notice_targets(rel, buckets)
        if not targets:
            unrouted.append(rel)
            continue
        for key in targets:
            routing[key].append((rel, path))
    print(f"\n{len(notices)} notices in sources/: "
          f"{sum(len(v) for v in routing.values())} placements across {len(routing)} archives")
    for key in sorted(routing):
        label = key[4:] if key.startswith("map:") else key
        print(f"    {label:22s} <- {', '.join(r for r, _ in routing[key])}")
    if unrouted:
        print(f"  {len(unrouted)} notices cover no shipped art (source-only, not packaged):")
        for rel in unrouted:
            print(f"    {rel}")

    if args.dry_run:
        print("\ndry-run: nothing written")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    openpacks = {p: zipfile.ZipFile(p) for p in args.packs}

    def write_archive(archive: pathlib.Path, names: list[str], bucket_key: str) -> None:
        tmp = archive.with_suffix(".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
            for n in sorted(names):
                src, info = entries[n]
                out.writestr(info.filename, openpacks[src].read(n))
            for rel, path in routing.get(bucket_key, []):
                out.writestr(rel, path.read_bytes())
        tmp.replace(archive)

    shared_archive = args.out / f"shared-{args.version}.pk3"
    write_archive(shared_archive, buckets["shared"], "shared")
    digest, size = sha256_and_size(shared_archive)
    manifest["shared"] = {"file": shared_archive.name, "sha256": digest, "size": size}
    print(f"\nwrote {shared_archive.name}  {size / 2**20:.1f} MB")

    for name in maps:
        archive = args.out / f"{name}.pk3"
        write_archive(archive, buckets[f"map:{name}"], f"map:{name}")
        digest, size = sha256_and_size(archive)
        manifest[name] = {"file": archive.name, "sha256": digest, "size": size}

    per_map_total = sum(v["size"] for k, v in manifest.items() if k != "shared")
    sizes = sorted(v["size"] for k, v in manifest.items() if k != "shared")
    print(f"wrote {len(maps)} per-map archives, {per_map_total / 2**20:.1f} MB total, "
          f"median {sizes[len(sizes) // 2] / 2**20:.1f} MB")

    (args.out / "manifest.json").write_bytes(
        (json.dumps({"schema": 1, "version": args.version, "archives": manifest}, indent=2) + "\n").encode()
    )
    print(f"wrote {args.out / 'manifest.json'}")
    for z in openpacks.values():
        z.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
