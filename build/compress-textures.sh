#!/usr/bin/env bash
# Compress the source textures to DDS, producing the art half of a shippable map archive.
#
#   build/compress-textures.sh                    # all of textures/ and models/
#   build/compress-textures.sh --dry-run          # list what would be converted, run nothing
#   build/compress-textures.sh --only map_boil    # just the paths matching a substring
#
# q3map2 produces a map's geometry; it does not produce its art. This is the other half: the textures a
# map references ship as DDS (S3TC/DXT block-compressed), which the game hands to the GPU still
# compressed — re-encoding them as PNG would enlarge them on disk and multiply their VRAM footprint by
# four to eight. See the restructure plan section 4.3.
#
# Both halves land in the same per-role split, and no new classification is needed: the archive
# classifier already keys on `map_<name>/` anywhere in a path, so dds/textures/map_boil/* goes to boil's
# archive and dds/textures/exx/* goes to the shared one.
#
# Wraps the vendored cached-converter.sh, which does the part worth not reimplementing: for each texture
# it tries several DXT formats and picks by measured PSNR rather than by a fixed rule. Its cache is
# content-addressed, so a re-run after editing one texture recompresses one texture.
#
# env:
#   DDS_TOOL   compressor for cached-converter (default nvcompress; also compressonator, crunch, s2tc)
#   CACHEDIR   the converter's cache (default ~/.xonotic-cached-converter)
#   JOBS       parallel conversions (default: nproc)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sources="$root/sources"
out="$root/builds/dds"

dry_run=0
only=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=1; shift ;;
        --only) only="${2:?--only needs a substring}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

: "${DDS_TOOL:=nvcompress}"
: "${CACHEDIR:=$HOME/.xonotic-cached-converter}"
: "${JOBS:=$(nproc 2>/dev/null || echo 4)}"

# textures/ and models/ only. env/ is deliberately excluded: skyboxes ship as JPEG, which is what
# upstream's pack does too (it has dds/textures and dds/models, and no dds/env).
mapfile -t images < <(cd "$sources" && find textures models -type f \
    \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.tga' \) 2>/dev/null | sort)

if [ -n "$only" ]; then
    filtered=()
    for f in "${images[@]}"; do [[ "$f" == *"$only"* ]] && filtered+=("$f"); done
    images=("${filtered[@]+"${filtered[@]}"}")
fi

if [ "${#images[@]}" -eq 0 ]; then
    echo "no source images found${only:+ matching '$only'}" >&2
    exit 1
fi

echo "${#images[@]} source image(s) to compress with $DDS_TOOL (cache: $CACHEDIR)"
if [ "$dry_run" = 1 ]; then
    printf '  %s\n' "${images[@]:0:10}"
    [ "${#images[@]}" -gt 10 ] && echo "  ... and $(( ${#images[@]} - 10 )) more"
    echo "DRY_RUN: nothing written"
    exit 0
fi

for tool in "$DDS_TOOL" convert compare; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "error: '$tool' not on PATH." >&2
        echo "       needs a DXT compressor plus ImageMagick — the converter picks the DXT format by" >&2
        echo "       measuring PSNR, so 'compare' is not optional. On Debian/Ubuntu:" >&2
        echo "         sudo apt-get install libnvtt-bin imagemagick" >&2
        exit 1
    }
done

# The converter must be executable. Git tracks the exec bit, but a Windows checkout does not set it, so
# a local `chmod +x` can easily fail to reach the repository. When that happens xargs exits 126
# ("found but not executable") and the only visible symptom is `printf: write error: Broken pipe` from
# the pipe feeding it — which says nothing about the cause. Check up front instead.
converter="$root/build/vendor/cached-converter.sh"
if [ ! -x "$converter" ]; then
    echo "error: $converter is not executable." >&2
    echo "       fix it in git, not just on disk:" >&2
    echo "         git update-index --chmod=+x build/vendor/cached-converter.sh" >&2
    exit 1
fi

mkdir -p "$CACHEDIR"

# cached-converter.sh writes output relative to its cwd, as dds/<path>.dds. So it runs inside sources/
# and the dds/ tree it produces is moved out afterwards — sources/dds/ is gitignored to keep an
# interrupted run from looking like tracked content.
cd "$sources"
rm -rf dds

# Only DDS. The converter can also do jpeg/webp/ogg; those would re-encode content we deliberately
# settled on (PNG sources, JPEG skyboxes) so they stay off.
export do_dds=true do_jpeg=false do_jpeg_if_not_dds=false \
       do_webp=false do_webp_if_not_dds=false do_ogg=false \
       del_src=false dds_tool="$DDS_TOOL" CACHEDIR="$CACHEDIR"

# xargs rather than a bash loop: the converter takes many files per invocation, so batching cuts
# process startup, and -P gives parallelism the script does not have itself.
printf './%s\n' "${images[@]}" \
    | xargs -d '\n' -n 64 -P "$JOBS" "$converter" \
    2> >(grep -vE '^Handling |^selfprofile_counter_' >&2 || true)

if [ ! -d dds ]; then
    echo "error: the converter produced no dds/ tree" >&2
    exit 1
fi

produced=$(find dds -type f -name '*.dds' | wc -l)
mkdir -p "$out"
rm -rf "$out/dds"
mv dds "$out/dds"

echo
echo "compressed $produced texture(s) -> builds/dds/dds/"
du -sh "$out/dds" | sed 's|^|  |'
