#!/usr/bin/env python3
"""Shared packaging logic for the map release: how a file is classified, and where its licence goes.

Imported by build/publish.py, which is the ONLY pipeline entry point — a release is produced by
compiling sources/ with q3map2 and packaging the result. Nothing here reads Xonotic's repositories.

    shared-<version>.pk3     art no single map owns
    <map>.pk3   xN           that map's own files
    manifest.json            what VortexArena's data/maps.lock.json is generated from

Historical note: this file began as build/split-pack.py, a one-off bootstrap that converted Xonotic's
bundled 597 MB xonotic-*-maps.pk3 into the per-map archives the game fetches. That migration is done and
its entry point is gone; only the classification half survived, because publish.py needs it. The bootstrap
is also where a long-lived bug lived — `.waypoints.cache` and `.waypoints.hardwired` sat on the drop list
as presumed compiler residue, so every shipped map carried bot waypoints with no links. See KNOWN_DROPS
and VortexArena planning/bot-ai-parity-2026-08-03.md.
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
#
# NOT in this set, though the names invite it: .waypoints.cache and .waypoints.hardwired. Those are
# bot navigation data the SERVER reads at runtime (waypoint_load_links / waypoint_load_hardwiredlinks),
# not q3map2 residue — q3map2 emits no .cache or .hardwired at all. Excluding them shipped maps whose
# waypoint graph had to be re-derived by tracewalk at load, which loses ~26% of the links and every
# hand-authored jump/teleport link, and leaves 29% of a map's waypoints as dead ends bots walk into and
# never out of. See VortexArena planning/bot-ai-parity-2026-08-03.md D1/D2. Verified against the
# upstream pack: every .cache and .hardwired member in it is a waypoint companion, so there is nothing
# with these extensions that legitimately belongs in sources/.
SOURCE_EXT = {".map", ".ase", ".obj", ".options", ".sh", ".rb", ".bat"}

# Every extension above, plus the handful of bare filenames that are build tooling rather than content.
# publish.py reconciles against this: anything classify() drops that is NOT covered here fails the build.
# The point is that dropping content becomes a REVIEWED decision with a reason attached, instead of the
# silent default for any file type nobody happened to think about. That silence is what cost us the
# waypoint caches and hardwired links on every map in the set.
KNOWN_DROPS = {
    ".map":     "Radiant level source; the .bsp is what ships",
    ".ase":     "model source; the compiled mesh ships",
    ".obj":     "model source; the compiled mesh ships",
    ".options": "q3map2 per-map compile switches (<map>.map.options)",
    ".sh":      "build tooling",
    ".rb":      "build tooling",
    ".bat":     "build tooling",
    ".pl":      "build tooling (bgs-maker.pl)",
}


def is_known_drop(name: str) -> bool:
    """Is dropping `name` a decision someone made on purpose (see KNOWN_DROPS)?"""
    return pathlib.PurePosixPath(name.lower()).suffix in KNOWN_DROPS

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
