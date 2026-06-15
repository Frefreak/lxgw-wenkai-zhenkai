#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools>=4.50"]
# ///
"""
Build a hybrid CJK font *family* whose REGULAR weight is LXGW WenKai (a light,
calligraphic Kai) and whose BOLD weight is LXGW ZhenKai (a heavier Kai).

WHY THIS WORKS (the one idea worth learning here)
--------------------------------------------------
A font "family" is NOT defined by any config file. It is defined entirely by
metadata baked into each font file's `name`, `OS/2` and `head` tables. CoreText
(macOS), DirectWrite (Windows) and fontconfig/FreeType (Linux) all group two
separate files into ONE family when those files share a family name but
advertise different weights.

So if we take two unrelated fonts and:
    * label WenKai  ->  family "<FAMILY>",  weight 400  (Regular)
    * label ZhenKai ->  family "<FAMILY>",  weight 700  (Bold)
then ANY app that renders <FAMILY> and asks for bold is handed ZhenKai for
free -- real bold strokes, no synthetic faux-bold smearing, no per-app config.
This is the cross-platform equivalent of the Linux fontconfig "alias zhenkai
as wenkai bold" trick, done by editing the fonts instead of a rules file.

WHAT WE DO **NOT** DO
---------------------
We do not move or redraw a single glyph. In both fonts the CJK ideographs are
already full-width (advance == 1 em), so terminal column alignment is preserved
automatically. "Monospace" in a terminal is mostly an *advertised* property, so
we only flip the two flags an app might inspect (`post.isFixedPitch` and the
PANOSE proportion byte). The rare proportional glyphs -- Latin letters, some
punctuation -- are normally supplied by your primary mono font anyway, so
ZhenKai's versions of them seldom get used.

Run:  ./build.py        (or: uv run build.py)
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Any

# fonttools is declared in the inline script block above and installed by
# `uv run`; a plain type checker won't see it, so silence just that one rule.
from fontTools.ttLib import TTFont  # pyright: ignore[reportMissingImports]

# --------------------------------------------------------------- config -----
# The merged family name you will reference in Ghostty / CSS / anywhere.
FAMILY = "LXGW WenKai ZhenKai Mono GB"

HERE = Path(__file__).parent
SRC = HERE / "fonts"   # downloaded upstream originals (git-ignored)
OUT = HERE / "dist"    # the two .ttf files we produce (git-ignored)

# Pinned upstream releases -> reproducible builds.
WENKAI_URL = "https://github.com/lxgw/LxgwWenkaiGB/releases/download/v1.522/LXGWWenKaiMonoGB-Regular.ttf"
ZHENKAI_URL = "https://github.com/lxgw/LxgwZhenKai/releases/download/v0.825/LXGWZhenKaiGB-Regular.ttf"

# `name` table IDs we rewrite (OpenType spec, "name" table).
NAME_FAMILY = 1       # legacy family name (used by 4-style RIBBI grouping)
NAME_SUBFAMILY = 2    # legacy subfamily: must be Regular/Bold/Italic/Bold Italic
NAME_UNIQUE = 3       # font Unique ID: MUST differ from the source fonts, or
                      # CoreText may dedup ours against the originals and serve
                      # the wrong file (a font-priority / shadowing bug).
NAME_FULL = 4         # human-readable full name
NAME_PS = 6           # PostScript name: ASCII, no spaces, must be unique
NAME_TYPO_FAMILY = 16     # "typographic" family (overrides 1 if present)
NAME_TYPO_SUBFAMILY = 17  # "typographic" subfamily (overrides 2 if present)

# OS/2.fsSelection bits and head.macStyle bits (these two must stay consistent).
FS_ITALIC, FS_BOLD, FS_REGULAR = 0x001, 0x020, 0x040
MAC_BOLD, MAC_ITALIC = 0x01, 0x02


def download(url: str, dest: Path) -> Path:
    """Fetch `url` to `dest` once; reuse the cached copy on later runs."""
    if dest.exists():
        print(f"  cached  {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetch   {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "lxgw-hybrid-build"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)  # stream -- these files are ~10-18 MB
    return dest


def set_name(font: TTFont, name_id: int, value: str) -> None:
    """Write one `name` record for both the platforms that matter, after
    clearing any stale records with the same ID. value must be ASCII so the
    Mac (platformID 1) record can encode it."""
    name = font["name"]
    name.removeNames(nameID=name_id)
    name.setName(value, name_id, 3, 1, 0x409)  # Windows, Unicode BMP, en-US
    name.setName(value, name_id, 1, 0, 0)      # Mac, Roman, en


def retag(src: Path, *, style: str, weight: int, bold: bool, out: Path) -> None:
    """Re-label one source font as a member of FAMILY at the given weight."""
    font = TTFont(src)
    # fontTools decompiles these tables from the binary at load time, so their
    # fields (usWeightClass, macStyle, isFixedPitch, ...) are populated
    # dynamically and have no static type. Annotate the handles as Any so the
    # field access below type-checks.
    os2: Any = font["OS/2"]
    head: Any = font["head"]
    post: Any = font["post"]

    # 1. Naming -- make both files claim the SAME family, different subfamily.
    ps_name = f"{FAMILY.replace(' ', '')}-{style}"      # ASCII, no spaces, unique
    set_name(font, NAME_FAMILY, FAMILY)
    set_name(font, NAME_SUBFAMILY, style)               # "Regular" / "Bold"
    set_name(font, NAME_UNIQUE, ps_name)                # break the dedup tie
    set_name(font, NAME_FULL, f"{FAMILY} {style}")
    set_name(font, NAME_PS, ps_name)
    # Drop the typographic names so our simple RIBBI grouping (1/2) wins and
    # the two files collapse into a single Regular+Bold family.
    font["name"].removeNames(nameID=NAME_TYPO_FAMILY)
    font["name"].removeNames(nameID=NAME_TYPO_SUBFAMILY)

    # 2. Weight class: 400 = Regular, 700 = Bold. This is what "ask for bold"
    #    actually selects.
    os2.usWeightClass = weight

    # 3. Style bits. OS/2.fsSelection and head.macStyle encode the same fact in
    #    two places and renderers cross-check them, so set both coherently.
    os2.fsSelection &= ~(FS_ITALIC | FS_BOLD | FS_REGULAR)
    os2.fsSelection |= FS_BOLD if bold else FS_REGULAR
    head.macStyle &= ~(MAC_BOLD | MAC_ITALIC)
    if bold:
        head.macStyle |= MAC_BOLD

    # 4. Advertise "monospaced" without touching any advance width. CJK glyphs
    #    are already full-width; this just satisfies an app that filters on the
    #    flag (e.g. a terminal's font picker).
    post.isFixedPitch = 1
    if getattr(os2, "panose", None) is not None:
        os2.panose.bProportion = 9  # PANOSE proportion 9 == Monospaced

    out.parent.mkdir(parents=True, exist_ok=True)
    font.save(out)
    print(f"  wrote   {out.name:42} weight={weight}  {'Bold' if bold else 'Regular'}")


def cjk_advance(path: Path, ch: str = "一") -> tuple[int, int]:
    """Return (advance_width, units_per_em) for a representative CJK glyph
    (default U+4E00 '一'). Used only for the alignment sanity check below."""
    font = TTFont(path)
    cmap: Any = font.getBestCmap()        # dynamic codepoint -> glyph-name map
    hmtx: Any = font["hmtx"]
    head: Any = font["head"]
    glyph_name = cmap[ord(ch)]
    return hmtx[glyph_name][0], head.unitsPerEm


def main() -> None:
    print("Downloading sources:")
    wen = download(WENKAI_URL, SRC / "LXGWWenKaiMonoGB-Regular.ttf")
    zhen = download(ZHENKAI_URL, SRC / "LXGWZhenKaiGB-Regular.ttf")

    # Prove to ourselves we really don't need to re-metricize: the full-width
    # CJK advance (relative to the em) should match between the two fonts.
    wa, wu = cjk_advance(wen)
    za, zu = cjk_advance(zhen)
    print("\nCJK '一' full-width advance:")
    print(f"  WenKai   {wa}/{wu} em  =  {wa / wu:.3f} em")
    print(f"  ZhenKai  {za}/{zu} em  =  {za / zu:.3f} em")
    if abs(wa / wu - za / zu) > 0.001:
        print("  ! mismatch -- bold CJK columns might drift; re-metricizing needed")
    else:
        print("  -> identical: bold CJK will align with regular. No glyph edits.")

    print("\nBuilding family:", FAMILY)
    stem = FAMILY.replace(" ", "")
    retag(wen, style="Regular", weight=400, bold=False, out=OUT / f"{stem}-Regular.ttf")
    retag(zhen, style="Bold", weight=700, bold=True, out=OUT / f"{stem}-Bold.ttf")

    print("\nInstall:")
    print(f"  cp {OUT}/*.ttf ~/Library/Fonts/")
    print("\nThen reference a SINGLE family -- bold resolves to ZhenKai automatically:")
    print(f'  font-family = "{FAMILY}"      # in Ghostty: no font-family-bold needed')


if __name__ == "__main__":
    main()
