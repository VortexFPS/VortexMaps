#!/usr/bin/env python3
"""Convert q3map2's external lightmap pages from TGA to PNG, losslessly.

q3map2 can only write external lightmaps as uncompressed TGA. For a map whose internal lightmap lump is
empty these pages are the entire lighting solution, and at 1024x1024 RGB they dominate the archive: 3.1 MB
each, two per map on stormkeep. PNG stores the same pixels 37% smaller than the .pk3's own deflate manages
on the raw TGA, because PNG filters each scanline against its neighbour and smooth lighting gradients are
exactly what that predicts well.

Every page is verified pixel-identical before its TGA is removed, and the script fails the build rather
than leaving a half-converted directory. That strictness is not ceremony:

  * Odd-numbered pages are DELUXEMAPS. Slot k's lightmap is lm_{2k} and its deluxe partner is lm_{2k+1}
    (game/MapLoader.cs:1084 in VortexArena). A deluxemap texel is a packed light DIRECTION vector, not a
    colour, so any perturbation rotates the incident-light direction and tilts the shading. The result
    still looks like lighting — just subtly wrong lighting, with nothing to compare against.
  * The load-bearing check is the pixel round-trip: decode the PNG we just wrote and compare it byte for
    byte against the source decode. That catches an encoder bug, a mode/palette mishap, or a short write.
    The header read alongside it is a weaker check than it looks, and worth being clear about — Pillow
    parses the same 18 bytes, so the two cannot really disagree about dimensions. It earns its place only
    by pinning the bit depth and rejecting a truncated header early, not as an independent decoder.
    (A genuinely independent cross-check DID matter in VortexArena tools/data/convert-tga.py, because
    ffmpeg has its own TGA parser and misreported a Xonotic page as 300x216 pal8 when the header said
    256x512 24bpp. Pillow does not share that bug, so the same trick buys much less here.)

Usage: lightmaps-to-png.py <dir-holding-lm_*.tga>
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the workflow installs Pillow
    sys.exit("error: Pillow is required to convert lightmap pages (pip install Pillow)")


def tga_header_dimensions(path: Path) -> tuple[int, int, int]:
    """Read width/height/bit-depth straight out of the 18-byte TGA header.

    Deliberately independent of the image library: a decoder that misparses the file would otherwise
    produce a PNG that matches its own wrong decode, and the verification would pass on garbage.
    """
    head = path.read_bytes()[:18]
    if len(head) < 18:
        raise ValueError(f"{path.name}: truncated TGA header ({len(head)} bytes)")
    width, height, depth = struct.unpack_from("<HHB", head, 12)
    return width, height, depth


def convert(page: Path) -> tuple[int, int]:
    """Convert one page in place, returning (tga_bytes, png_bytes). Raises on any mismatch."""
    declared_w, declared_h, declared_depth = tga_header_dimensions(page)

    with Image.open(page) as src:
        if (src.width, src.height) != (declared_w, declared_h):
            raise ValueError(
                f"{page.name}: the TGA header says {declared_w}x{declared_h} but the decoder read "
                f"{src.width}x{src.height}. Refusing to convert — one of the two is wrong and a PNG "
                f"written from the bad decode would be silently corrupt lighting."
            )
        # Lightmaps are 24bpp RGB; deluxe pages likewise (a packed direction in the RGB channels).
        if declared_depth not in (24, 32):
            raise ValueError(f"{page.name}: unexpected TGA bit depth {declared_depth} (want 24 or 32)")

        mode = "RGBA" if declared_depth == 32 else "RGB"
        original = src.convert(mode)
        reference = original.tobytes()

    out = page.with_suffix(".png")
    original.save(out, "PNG", optimize=True)

    with Image.open(out) as check:
        if check.convert(mode).tobytes() != reference:
            out.unlink(missing_ok=True)
            raise ValueError(f"{page.name}: PNG round-trip is not pixel-identical — TGA kept, build failed")

    tga_bytes, png_bytes = page.stat().st_size, out.stat().st_size
    page.unlink()  # only now: verification passed
    return tga_bytes, png_bytes


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return int(bool(sys.stderr.write(f"usage: {Path(argv[0]).name} <dir-holding-lm_*.tga>\n"))) or 2

    directory = Path(argv[1])
    if not directory.is_dir():
        sys.stderr.write(f"error: {directory} is not a directory\n")
        return 1

    pages = sorted(directory.glob("lm_*.tga"))
    if not pages:
        # Not an error: a map with internal lightmaps has no external pages. But say so, because
        # "converted 0 pages" and "there were none to convert" must not look the same in a build log.
        already = len(list(directory.glob("lm_*.png")))
        print(f"  lightmaps: no TGA pages in {directory} ({already} PNG already present)")
        return 0

    total_tga = total_png = 0
    for page in pages:
        try:
            tga_bytes, png_bytes = convert(page)
        except Exception as exc:  # noqa: BLE001 - any failure must fail the build, with the reason
            sys.stderr.write(f"error: {exc}\n")
            return 1
        total_tga += tga_bytes
        total_png += png_bytes
        print(f"  lightmaps: {page.name} -> {page.with_suffix('.png').name} "
              f"({tga_bytes:,} -> {png_bytes:,} B)")

    # Say what the percentage compares, because the honest number for archive size is smaller than this
    # one: measured on stormkeep, PNG is 68% under the raw TGA but only 37% under the TGA once the .pk3's
    # deflate has had a go at it. The second figure is the one that shows up in a download.
    saved = 100 * (1 - total_png / total_tga) if total_tga else 0
    print(f"  lightmaps: {len(pages)} page(s), {total_tga:,} -> {total_png:,} B "
          f"({saved:.0f}% under the uncompressed TGA; less once packed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
