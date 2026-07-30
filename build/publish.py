#!/usr/bin/env python3
"""Package compiled map output into the per-role archives the game fetches, and emit the manifest.

    python build/publish.py builds/q3map2 --out dist --version 2026.08 --sources sources

The counterpart to split-pack.py: same output shape and the same licence-notice routing, but reading
from per-map build directories (what build-map runs produce) rather than from Xonotic's bundled pk3s.
The classification and archive-writing logic is imported from split-pack.py rather than duplicated,
because the two agreeing is the point — the game's data/maps.lock.json cannot tell which produced a
given archive, so they must produce the same thing.

Output, per the restructure plan section 5.3.1:

    shared-<version>.zip     art no single map owns
    <map>-q3map2.zip   xN    that map's own files
    manifest.json            what data/maps.lock.json is generated from
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def load_split_pack():
    """Import split-pack.py by path — its filename is not a valid module name."""
    spec = importlib.util.spec_from_file_location("split_pack", HERE / "split-pack.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["split_pack"] = module  # @dataclass resolves the module by name
    spec.loader.exec_module(module)
    return module


def main() -> int:
    sp = load_split_pack()

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builds", type=pathlib.Path, help="directory of per-map build output")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--sources", type=pathlib.Path, default=HERE.parent / "sources")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.builds.is_dir():
        sys.exit(f"error: no build directory at {args.builds}")

    # Flatten the build tree into archive-relative paths, exactly the shape split-pack sees from a pk3.
    files: dict[str, pathlib.Path] = {}
    for path in sorted(args.builds.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(args.builds).as_posix()
        # build-map.py writes builds/q3map2/<map>/..., so strip the per-map directory: the archive
        # content must be type-rooted (maps/, dds/, scripts/), not nested under the map name.
        parts = rel.split("/", 1)
        files[parts[1] if len(parts) == 2 else rel] = path

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

    maps = sorted(k[4:] for k in buckets if k.startswith("map:"))
    if set(maps) != bsps:
        sys.exit(
            "error: map buckets disagree with the .bsp set\n"
            f"  buckets without a bsp: {sorted(set(maps) - bsps)}\n"
            f"  bsps without a bucket: {sorted(bsps - set(maps))}"
        )
    print(f"  shared   {len(buckets['shared']):5d} files")
    print(f"  per-map  {sum(len(v) for k, v in buckets.items() if k != 'shared'):5d} files")
    if dropped:
        print(f"  dropped  {dropped} build-residue files")

    # Same notice routing as split-pack: these sit beside the art in sources/, which players never
    # fetch, while the art ships. See split-pack.py's find_notices docstring.
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

    shared = args.out / f"shared-{args.version}.zip"
    write(shared, buckets["shared"], "shared")
    digest, size = sp.sha256_and_size(shared)
    manifest["shared"] = {"file": shared.name, "sha256": digest, "size": size}
    print(f"\nwrote {shared.name}  {size / 2**20:.1f} MB")

    for name in maps:
        archive = args.out / f"{name}-q3map2.zip"
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
