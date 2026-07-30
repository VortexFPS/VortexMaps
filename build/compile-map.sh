#!/usr/bin/env bash
# Compile one classic map, then move q3map2's output into builds/q3map2/<map>/.
#
#   build/compile-map.sh stormkeep
#   DRY_RUN=1 build/compile-map.sh stormkeep      # print the wrapper invocation, run nothing
#
# This is our replacement for upstream's misc/tools/xonotic-map-compiler-optionsfile, which cannot be
# vendored as-is: it invokes the compiler through the hardcoded relative path `misc/tools/...`, a layout
# we do not have. It is 16 lines and does exactly two things, both reproduced here:
#
#   1. Lift the flags out of <map>.map.options, stripping # comments. Those flags are argv for the
#      WRAPPER, not for q3map2 - see build/vendor/README.md - so they are passed through verbatim and
#      must not be reordered or "normalised".
#   2. If <map>.mapinfo carries a `size` line, append `-minimap + -minmax <size>` so the minimap is
#      framed to the map's declared bounds rather than to its geometry.
#
# The wrapper supplies q3map2's basepaths itself, including a tmpdir symlink to the map's parent, which
# is why our type-rooted sources/ needs no overlay. VORTEXARENA_ROOT and VORTEXMAPS_Q3MAP2 come from
# ~/.xonotic-map-compiler (build/map-compiler-config.pl).
set -euo pipefail

map="${1:?usage: compile-map.sh <mapname>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$root/sources/maps"
out="$root/builds/q3map2/$map"

[ -f "$src/$map.map" ] || { echo "error: no source at sources/maps/$map.map" >&2; exit 1; }

# 1. flags from the options file
flags=()
if [ -f "$src/$map.map.options" ]; then
    while read -r tok; do flags+=("$tok"); done < <(grep '^-' "$src/$map.map.options" | cut -d'#' -f1 | tr -s ' \t' '\n' | grep .)
else
    echo "note: no $map.map.options - using the wrapper's per-phase defaults"
    flags=(-bsp -light -vis -minimap)
fi

# 2. the -minmax override, from the map's declared size
if [ -f "$src/$map.mapinfo" ]; then
    size="$(grep '^size ' "$src/$map.mapinfo" 2>/dev/null | head -1 | cut -d' ' -f2- || true)"
    if [ -n "$size" ]; then
        # shellcheck disable=SC2206  # deliberate word splitting: size is six numbers
        flags+=(-minimap + -minmax $size)
        echo "minimap framed to the declared size: $size"
    fi
fi

echo "compiling $map with: ${flags[*]}"
if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "DRY_RUN: would run perl build/vendor/xonotic-map-compiler sources/maps/$map ${flags[*]}"
    exit 0
fi

cd "$root"
perl build/vendor/xonotic-map-compiler "sources/maps/$map" "${flags[@]}"

# q3map2 writes beside the source. Move the products out so sources/ stays clean and publish.py has
# one place to look. Type-rooted inside the per-map dir, because that is the shape the archives need.
mkdir -p "$out/maps"
moved=0
for f in "$src/$map.bsp" "$src/$map.srf" "$src/$map.prt" "$src/$map.lin"; do
    [ -f "$f" ] && { mv "$f" "$out/maps/"; moved=$((moved + 1)); }
done
for f in "$src/$map"_mini.*; do
    [ -f "$f" ] && { mkdir -p "$out/gfx"; mv "$f" "$out/gfx/"; moved=$((moved + 1)); }
done
# External lightmap pages land in sources/maps/<map>/lm_*.
if [ -d "$src/$map" ]; then
    shopt -s nullglob
    pages=("$src/$map"/lm_*)
    if [ ${#pages[@]} -gt 0 ]; then
        mkdir -p "$out/maps/$map"
        mv "${pages[@]}" "$out/maps/$map/"
        moved=$((moved + ${#pages[@]}))
    fi
    shopt -u nullglob
fi
# Carry the map's authored runtime companions across; they ship with the BSP, not with the sources.
for ext in mapinfo waypoints waypoints.hardwired race.waypoints rtlights; do
    [ -f "$src/$map.$ext" ] && cp "$src/$map.$ext" "$out/maps/"
done

# .srf and .prt are q3map2 scratch, not shipped.
rm -f "$out/maps/$map.srf" "$out/maps/$map.prt" "$out/maps/$map.lin"

[ "$moved" -gt 0 ] || { echo "error: q3map2 reported success but produced no output for $map" >&2; exit 1; }
echo "$map: $moved product(s) -> builds/q3map2/$map/"
find "$out" -type f | sed 's|^|  |'
