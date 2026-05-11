#!/usr/bin/env python3
"""Extract CSS properties from a Figma node."""

import os
import sys
import json
import math
import argparse
import urllib.parse
from figma_common import (
    load_account, figma_get, parse_figma_url,
    rgba_to_hex, figma_length,
)


def _convert_color(paint):
    """Convert a single Figma paint to CSS color string."""
    if not paint.get("visible", True):
        return None

    color = paint.get("color", {})
    r = color.get("r", 0)
    g = color.get("g", 0)
    b = color.get("b", 0)
    a = color.get("a", 1) * paint.get("opacity", 1)
    return rgba_to_hex(r, g, b, a)


def _convert_gradient(paint):
    """Convert a Figma gradient paint to CSS gradient string."""
    if not paint.get("visible", True):
        return None

    handles = paint.get("gradientHandlePositions", [])
    stops = paint.get("gradientStops", [])
    if len(handles) < 2 or not stops:
        return None

    start, end = handles[0], handles[1]
    angle_rad = math.atan2(end["y"] - start["y"], end["x"] - start["x"])
    angle_deg = round(math.degrees(angle_rad) + 90) % 360

    stop_parts = []
    for stop in stops:
        color = stop.get("color", {})
        css_color = rgba_to_hex(
            color.get("r", 0), color.get("g", 0),
            color.get("b", 0), color.get("a", 1),
        )
        position = round(stop.get("position", 0) * 100)
        stop_parts.append(f"{css_color} {position}%")

    return f"linear-gradient({angle_deg}deg, {', '.join(stop_parts)})"


def _convert_fills(fills, is_text=False):
    """Convert Figma fills to CSS background or color properties."""
    if not fills:
        return {}

    css = {}
    for fill in reversed(fills):
        if not fill.get("visible", True):
            continue

        fill_type = fill.get("type", "")

        if fill_type == "SOLID":
            color = _convert_color(fill)
            if not color:
                continue
            if is_text:
                css["color"] = color
            else:
                css["background-color"] = color

        elif fill_type.startswith("GRADIENT_"):
            gradient = _convert_gradient(fill)
            if gradient:
                css["background"] = gradient

    return css


def _convert_strokes(node):
    """Convert Figma strokes to CSS border properties."""
    strokes = node.get("strokes", [])
    if not strokes:
        return {}

    weight = node.get("strokeWeight", 1)

    for stroke in strokes:
        if not stroke.get("visible", True):
            continue
        if stroke.get("type") != "SOLID":
            continue

        color = _convert_color(stroke)
        if not color:
            continue

        return {"border": f"{figma_length(weight)} solid {color}"}

    return {}


def _convert_typography(node):
    """Convert Figma text style properties to CSS typography."""
    style = node.get("style", {})
    if not style:
        return {}

    css = {}

    font_family = style.get("fontFamily")
    if font_family:
        css["font-family"] = f'"{font_family}", sans-serif'

    font_size = style.get("fontSize")
    if font_size:
        css["font-size"] = figma_length(font_size)

    font_weight = style.get("fontWeight")
    if font_weight:
        css["font-weight"] = str(int(font_weight))

    line_height = style.get("lineHeightPx")
    line_height_unit = style.get("lineHeightUnit", "")
    if line_height_unit == "AUTO":
        pass
    elif line_height:
        css["line-height"] = figma_length(line_height)

    letter_spacing = style.get("letterSpacing")
    if letter_spacing and letter_spacing != 0:
        css["letter-spacing"] = figma_length(letter_spacing)

    align_map = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}
    text_align = style.get("textAlignHorizontal")
    if text_align and text_align in align_map:
        css["text-align"] = align_map[text_align]

    decoration_map = {"UNDERLINE": "underline", "STRIKETHROUGH": "line-through"}
    decoration = style.get("textDecoration")
    if decoration and decoration in decoration_map:
        css["text-decoration"] = decoration_map[decoration]

    case_map = {"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}
    text_case = style.get("textCase")
    if text_case and text_case in case_map:
        css["text-transform"] = case_map[text_case]

    fills = node.get("fills", [])
    fill_css = _convert_fills(fills, is_text=True)
    css.update(fill_css)

    return css


def _convert_layout(node):
    """Convert Figma auto-layout to CSS flexbox properties."""
    layout_mode = node.get("layoutMode")
    if not layout_mode or layout_mode == "NONE":
        return {}

    css = {"display": "flex"}

    if layout_mode == "HORIZONTAL":
        css["flex-direction"] = "row"
    elif layout_mode == "VERTICAL":
        css["flex-direction"] = "column"

    spacing = node.get("itemSpacing")
    if spacing and spacing > 0:
        css["gap"] = figma_length(spacing)

    primary_map = {
        "MIN": "flex-start", "CENTER": "center",
        "MAX": "flex-end", "SPACE_BETWEEN": "space-between",
    }
    primary = node.get("primaryAxisAlignItems")
    if primary and primary in primary_map:
        css["justify-content"] = primary_map[primary]

    counter_map = {
        "MIN": "flex-start", "CENTER": "center",
        "MAX": "flex-end", "BASELINE": "baseline",
    }
    counter = node.get("counterAxisAlignItems")
    if counter and counter in counter_map:
        css["align-items"] = counter_map[counter]

    if node.get("layoutWrap") == "WRAP":
        css["flex-wrap"] = "wrap"

    pt = node.get("paddingTop", 0)
    pr = node.get("paddingRight", 0)
    pb = node.get("paddingBottom", 0)
    pl = node.get("paddingLeft", 0)

    if pt or pr or pb or pl:
        if pt == pr == pb == pl:
            css["padding"] = figma_length(pt)
        elif pt == pb and pr == pl:
            css["padding"] = f"{figma_length(pt)} {figma_length(pr)}"
        else:
            css["padding"] = f"{figma_length(pt)} {figma_length(pr)} {figma_length(pb)} {figma_length(pl)}"

    return css


def _convert_size(node):
    """Convert Figma sizing to CSS width/height."""
    css = {}
    bbox = node.get("absoluteBoundingBox", {})

    h_sizing = node.get("layoutSizingHorizontal", "FIXED")
    v_sizing = node.get("layoutSizingVertical", "FIXED")

    if h_sizing == "FIXED" and "width" in bbox:
        css["width"] = figma_length(bbox["width"])
    elif h_sizing == "FILL":
        css["flex"] = "1"

    if v_sizing == "FIXED" and "height" in bbox:
        css["height"] = figma_length(bbox["height"])

    min_w = node.get("minWidth")
    max_w = node.get("maxWidth")
    min_h = node.get("minHeight")
    max_h = node.get("maxHeight")

    if min_w:
        css["min-width"] = figma_length(min_w)
    if max_w:
        css["max-width"] = figma_length(max_w)
    if min_h:
        css["min-height"] = figma_length(min_h)
    if max_h:
        css["max-height"] = figma_length(max_h)

    return css


def _convert_border_radius(node):
    """Convert Figma corner radius to CSS border-radius."""
    corners = node.get("rectangleCornerRadii")
    if corners and any(c > 0 for c in corners):
        tl, tr, br, bl = corners
        if tl == tr == br == bl:
            return {"border-radius": figma_length(tl)}
        return {"border-radius": f"{figma_length(tl)} {figma_length(tr)} {figma_length(br)} {figma_length(bl)}"}

    radius = node.get("cornerRadius")
    if radius and radius > 0:
        return {"border-radius": figma_length(radius)}

    return {}


def _convert_effects(node):
    """Convert Figma effects to CSS shadow/blur properties."""
    effects = node.get("effects", [])
    if not effects:
        return {}

    css = {}
    shadows = []
    for effect in effects:
        if not effect.get("visible", True):
            continue

        effect_type = effect.get("type", "")
        color = effect.get("color", {})
        css_color = rgba_to_hex(
            color.get("r", 0), color.get("g", 0),
            color.get("b", 0), color.get("a", 1),
        )
        offset = effect.get("offset", {})
        ox = figma_length(offset.get("x", 0))
        oy = figma_length(offset.get("y", 0))
        radius = figma_length(effect.get("radius", 0))
        spread = effect.get("spread", 0)

        if effect_type == "DROP_SHADOW":
            shadow = f"{ox} {oy} {radius}"
            if spread:
                shadow += f" {figma_length(spread)}"
            shadow += f" {css_color}"
            shadows.append(shadow)

        elif effect_type == "INNER_SHADOW":
            shadow = f"inset {ox} {oy} {radius}"
            if spread:
                shadow += f" {figma_length(spread)}"
            shadow += f" {css_color}"
            shadows.append(shadow)

        elif effect_type == "LAYER_BLUR":
            css["filter"] = f"blur({radius})"

        elif effect_type == "BACKGROUND_BLUR":
            css["backdrop-filter"] = f"blur({radius})"

    if shadows:
        css["box-shadow"] = ", ".join(shadows)

    return css


def extract_css_from_node(node):
    """Extract all CSS properties from a Figma node."""
    node_type = node.get("type", "")
    is_text = node_type == "TEXT"

    css = {}
    typography = {}
    effects = {}

    if not is_text:
        css.update(_convert_layout(node))
        css.update(_convert_fills(node.get("fills", [])))
        css.update(_convert_strokes(node))

    css.update(_convert_size(node))
    css.update(_convert_border_radius(node))

    effect_css = _convert_effects(node)
    effects.update(effect_css)

    opacity = node.get("opacity")
    if opacity is not None and opacity < 1:
        css["opacity"] = str(round(opacity, 2))

    if node.get("clipsContent"):
        css["overflow"] = "hidden"

    if is_text:
        typography = _convert_typography(node)

    result = {
        "node_id": node.get("id", ""),
        "name": node.get("name", ""),
        "type": node_type,
    }

    if css:
        result["css"] = css
    if typography:
        result["typography"] = typography
    if effects:
        result["effects"] = effects

    return result


def main():
    parser = argparse.ArgumentParser(description="Extract CSS from a Figma node")
    parser.add_argument("url", nargs="?", help="Figma URL with node-id")
    parser.add_argument("--file", help="File key")
    parser.add_argument("--node", help="Node ID (e.g. 12:34)")
    parser.add_argument("--nodes", nargs="+", help="Multiple node IDs for batch extraction (single API call)")
    parser.add_argument("--with-children", action="store_true", help="Include direct children CSS")
    parser.add_argument("--refresh", action="store_true", help="Bypass cache for this call and re-fetch from Figma")
    args = parser.parse_args()

    if args.refresh:
        os.environ["FIGMA_SKILL_REFRESH"] = "1"

    file_key = args.file
    node_id = args.node
    if args.url:
        file_key, node_id = parse_figma_url(args.url)

    node_ids = args.nodes or ([node_id] if node_id else [])

    if not file_key or not node_ids:
        print("Provide a Figma URL with node-id, --file and --node, or --file and --nodes", file=sys.stderr)
        sys.exit(1)

    cfg = load_account()
    encoded_ids = ",".join(urllib.parse.quote(nid) for nid in node_ids)
    data = figma_get(cfg["token"], f"/v1/files/{file_key}/nodes?ids={encoded_ids}&geometry=paths", account=cfg["name"])

    nodes = data.get("nodes", {})
    results = []
    for nid in node_ids:
        node_data = nodes.get(nid)
        if not node_data or not node_data.get("document"):
            print(f"Node {nid} not found", file=sys.stderr)
            continue

        doc = node_data["document"]
        result = extract_css_from_node(doc)

        if args.with_children and "children" in doc:
            result["children"] = [
                extract_css_from_node(child)
                for child in doc["children"]
            ]

        if "_cache" in node_data:
            result["_cache"] = node_data["_cache"]

        results.append(result)

    if len(node_ids) == 1 and len(results) == 1:
        print(json.dumps(results[0], indent=2))
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
