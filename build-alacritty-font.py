#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools==4.61.1"]
# ///
"""Combine installed Fantasque Nerd Font and WenKai for Alacritty."""

import argparse
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable


FAMILY = "Alacritty Fantasque WenKai Mono"
STYLES = ("Regular", "Bold", "Italic", "BoldItalic")


def rename(font, donor, style):
    names = font["name"]
    display_style = "Bold Italic" if style == "BoldItalic" else style
    values = {
        0: names.getDebugName(0) + "\n" + donor["name"].getDebugName(0),
        1: FAMILY,
        2: display_style,
        3: f"{FAMILY}-{style}-1.0",
        4: f"{FAMILY} {display_style}",
        6: f"AlacrittyFantasqueWenKaiMono-{style}",
        16: FAMILY,
        17: display_style,
    }
    names.names = [n for n in names.names if n.nameID not in (18, 21, 22)]
    for name_id, value in values.items():
        for record in list(names.names):
            if record.nameID == name_id:
                names.removeNames(
                    nameID=name_id,
                    platformID=record.platformID,
                    platEncID=record.platEncID,
                    langID=record.langID,
                )
        names.setName(value, name_id, 3, 1, 0x409)
        names.setName(value, name_id, 0, 4, 0)


def build(base_path, donor, output, style):
    font = TTFont(base_path)
    base_map = font.getBestCmap()
    additions = {
        code: glyph for code, glyph in donor.getBestCmap().items()
        if code not in base_map
    }
    glyph_set = donor.getGlyphSet()
    scale = font["head"].unitsPerEm / donor["head"].unitsPerEm
    cell = font["hmtx"][base_map[ord(" ")]][0]
    order = font.getGlyphOrder()[:]
    imported = {}
    for glyph_name in sorted(set(additions.values())):
        new_name = f"wenkai.{glyph_name}"
        if new_name in order:
            raise ValueError(f"Glyph name collision: {new_name}")
        advance = donor["hmtx"][glyph_name][0]
        width = round(advance * (2 * cell) / donor["head"].unitsPerEm)
        shift = (width - advance * scale) / 2
        recording = DecomposingRecordingPen(glyph_set)
        glyph_set[glyph_name].draw(recording)
        pen = TTGlyphPen(None)
        recording.replay(TransformPen(pen, (scale, 0, 0, scale, shift, 0)))
        glyph = pen.glyph()
        glyph.recalcBounds(font["glyf"])
        font["glyf"][new_name] = glyph
        font["hmtx"][new_name] = (width, getattr(glyph, "xMin", 0))
        order.append(new_name)
        imported[glyph_name] = new_name

    if len(order) > 65535:
        raise ValueError("Combined font exceeds TrueType glyph limit")
    font.setGlyphOrder(order)
    new_map = {code: imported[name] for code, name in additions.items()}
    for table in font["cmap"].tables:
        if table.isUnicode() and table.format in (4, 12):
            table.cmap.update({
                code: name for code, name in new_map.items()
                if table.format == 12 or code < 0xFFFF
            })
    if not any(t.format == 12 and t.isUnicode()
               for t in font["cmap"].tables):
        table = CmapSubtable.newSubtable(12)
        table.platformID, table.platEncID, table.language = 3, 10, 0
        table.cmap = base_map | new_map
        font["cmap"].tables.append(table)
    rename(font, donor, style)
    path = output / f"AlacrittyFantasqueWenKaiMono-{style}.ttf"
    font.save(path)
    verify(base_path, path, new_map)
    print(f"{path}: verified original glyphs; added {len(new_map)} characters")


def verify(base_path, path, additions):
    with TTFont(base_path) as base, TTFont(path) as merged:
        assert merged.getBestCmap() == base.getBestCmap() | additions
        for name in base.getGlyphOrder():
            assert base["hmtx"][name] == merged["hmtx"][name], name
            assert (base["glyf"][name].compile(base["glyf"])
                    == merged["glyf"][name].compile(merged["glyf"])), name
        for attr in ("ascent", "descent", "lineGap"):
            assert getattr(base["hhea"], attr) == getattr(merged["hhea"], attr)
        for char in "中文你好，。！？":
            assert ord(char) in merged.getBestCmap(), char


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fonts", type=Path, default=Path.home() / "Library/Fonts"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    collection = TTCollection(args.fonts / "LXGWHybrid.ttc", lazy=True)
    donors = {
        f["name"].getDebugName(2): f for f in collection.fonts
        if f["name"].getDebugName(1) == "LXGW WenKai Mono GB"
    }
    if set(donors) != {"Regular", "Bold"}:
        raise ValueError("Expected regular and bold LXGW WenKai Mono GB")
    for style in STYLES:
        base = args.fonts / f"FantasqueSansMNerdFontMono-{style}.ttf"
        donor = donors["Bold" if "Bold" in style else "Regular"]
        build(base, donor, args.output, style)
    collection.close()


if __name__ == "__main__":
    main()
