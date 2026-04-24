# MenuTitle: Offset Geometric Outlines
# -*- coding: utf-8 -*-
from __future__ import annotations
# -------------------------------------------------------------------
# SETTINGS
# -------------------------------------------------------------------
INSET          = 20     # Units to contract inward (positive = contract, negative = expand)
ANGLE_SNAP     = 10     # Tolerance in degrees for snapping to 0/45/90/135/180
SELECTED_ONLY  = True   # True = selected glyphs only, False = whole font
FLATTEN            = True   # Remove overlaps before contracting
FLATTEN_BACKGROUND = False  # Remove overlaps in background before contracting
CREATE_NEW_LAYER       = True        # Write result to a new layer instead of editing in place
NEW_LAYER_NAME         = "Offset"    # Base name for the new layer
NEW_LAYER_INCLUDE_VALS = True        # Append INSET and ANGLE_SNAP values to layer name
INCLUDE_BACKGROUND     = True   # Copy background paths into the new layer
OFFSET_BACKGROUND      = True   # Also apply the same contraction to the background paths
# -------------------------------------------------------------------
import math
from Foundation import NSPoint
from GlyphsApp import Glyphs, Message, GSOFFCURVE, GSLayer
# -------------------------------------------------------------------
# Safe attribute getter — returns [] if attr missing or inaccessible
# -------------------------------------------------------------------
def safe_list(obj, attr):
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return []
        return list(val)
    except Exception:
        return []
# -------------------------------------------------------------------
# Layer naming
# -------------------------------------------------------------------
def build_base_name():
    if not NEW_LAYER_INCLUDE_VALS:
        return NEW_LAYER_NAME
    sign = "minus" if INSET >= 0 else "plus"
    return "{}_{}{}__angle{}".format(NEW_LAYER_NAME, sign, abs(INSET), ANGLE_SNAP)
def unique_layer_name(glyph, base_name):
    existing = set(l.name for l in glyph.layers if l.name)
    counter = 1
    while True:
        candidate = "{}_{}".format(base_name, str(counter).zfill(3))
        if candidate not in existing:
            return candidate
        counter += 1
# -------------------------------------------------------------------
# Geometry helpers
# -------------------------------------------------------------------
def snap_angle(angle_deg, tolerance=ANGLE_SNAP):
    snaps = [0, 45, 90, 135, 180, 225, 270, 315, 360]
    closest = min(snaps, key=lambda s: abs(angle_deg - s))
    if abs(angle_deg - closest) <= tolerance:
        return closest % 360
    return angle_deg
def angle_between(p1, p2):
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    return math.degrees(math.atan2(dy, dx)) % 360
def contour_winding(on_curve_nodes):
    """Returns signed area; positive = counter-clockwise, negative = clockwise."""
    area = 0.0
    n = len(on_curve_nodes)
    for i in range(n):
        j = (i + 1) % n
        area += on_curve_nodes[i].position.x * on_curve_nodes[j].position.y
        area -= on_curve_nodes[j].position.x * on_curve_nodes[i].position.y
    return area
def contour_bounds(contour):
    """Return (minX, minY, maxX, maxY) bounding box for a contour."""
    on_curve = [nd for nd in contour.nodes if nd.type != GSOFFCURVE]
    if not on_curve:
        return (0, 0, 0, 0)
    xs = [nd.position.x for nd in on_curve]
    ys = [nd.position.y for nd in on_curve]
    return (min(xs), min(ys), max(xs), max(ys))
def bounds_contains(outer, inner):
    """Check if outer bounding box fully contains inner bounding box."""
    return (outer[0] <= inner[0] and outer[1] <= inner[1] and
            outer[2] >= inner[2] and outer[3] >= inner[3])
def point_in_contour(point, contour):
    """Ray-casting algorithm to test if a point is inside a contour."""
    on_curve = [nd for nd in contour.nodes if nd.type != GSOFFCURVE]
    if len(on_curve) < 3:
        return False
    
    x, y = point.x, point.y
    n = len(on_curve)
    inside = False
    
    j = n - 1
    for i in range(n):
        xi, yi = on_curve[i].position.x, on_curve[i].position.y
        xj, yj = on_curve[j].position.x, on_curve[j].position.y
        
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    
    return inside
def contour_centroid(contour):
    """Get approximate center point of a contour."""
    on_curve = [nd for nd in contour.nodes if nd.type != GSOFFCURVE]
    if not on_curve:
        return NSPoint(0, 0)
    avg_x = sum(nd.position.x for nd in on_curve) / len(on_curve)
    avg_y = sum(nd.position.y for nd in on_curve) / len(on_curve)
    return NSPoint(avg_x, avg_y)
def determine_contour_nesting(contours):
    """
    Determine nesting level for each contour.
    Returns a list of integers: 0 = outermost, 1 = inside one contour, etc.
    Even nesting = outer/fill, Odd nesting = inner/hole (counter).
    """
    n = len(contours)
    if n == 0:
        return []
    
    bounds_list = [contour_bounds(c) for c in contours]
    nesting_levels = [0] * n
    
    for i in range(n):
        level = 0
        centroid = contour_centroid(contours[i])
        
        for j in range(n):
            if i == j:
                continue
            # Quick bounds check first
            if bounds_contains(bounds_list[j], bounds_list[i]):
                # More accurate point-in-polygon test
                if point_in_contour(centroid, contours[j]):
                    level += 1
        
        nesting_levels[i] = level
    
    return nesting_levels
def offset_point(p_prev, p_curr, p_next, inset_distance):
    in_angle  = snap_angle(angle_between(p_prev, p_curr))
    out_angle = snap_angle(angle_between(p_curr, p_next))
    in_nx  = math.cos(math.radians(in_angle  - 90))
    in_ny  = math.sin(math.radians(in_angle  - 90))
    out_nx = math.cos(math.radians(out_angle - 90))
    out_ny = math.sin(math.radians(out_angle - 90))
    avg_nx = in_nx + out_nx
    avg_ny = in_ny + out_ny
    length = math.sqrt(avg_nx ** 2 + avg_ny ** 2)
    if length < 1e-6:
        return NSPoint(p_curr.x + in_nx * inset_distance,
                       p_curr.y + in_ny * inset_distance)
    avg_nx /= length
    avg_ny /= length
    dot = in_nx * avg_nx + in_ny * avg_ny
    if abs(dot) < 1e-6:
        dot = 1e-6
    miter_scale = min(1.0 / dot, 4.0)
    offset = inset_distance * miter_scale
    return NSPoint(p_curr.x + avg_nx * offset,
                   p_curr.y + avg_ny * offset)
# -------------------------------------------------------------------
# Core contour operation
# -------------------------------------------------------------------
def contract_contour(contour, inset_distance, is_counter=False):
    """
    Contract a single contour.
    
    Args:
        contour: The contour to offset
        inset_distance: Base offset amount (positive = contract)
        is_counter: If True, this is an inner counter (hole) - invert direction
    """
    on_curve = [nd for nd in contour.nodes if nd.type != GSOFFCURVE]
    if len(on_curve) < 3:
        return
    winding = contour_winding(on_curve)
    
    # Base direction from winding
    effective_inset = -inset_distance if winding > 0 else inset_distance
    
    # If this is a counter (hole), we need to invert the offset direction
    # to maintain consistent stroke width
    if is_counter:
        effective_inset = -effective_inset
    n = len(on_curve)
    new_positions = []
    for i in range(n):
        p_prev = on_curve[(i - 1) % n].position
        p_curr = on_curve[i].position
        p_next = on_curve[(i + 1) % n].position
        new_positions.append(
            offset_point(p_prev, p_curr, p_next, effective_inset)
        )
    idx = 0
    for nd in contour.nodes:
        if nd.type != GSOFFCURVE:
            nd.position = new_positions[idx]
            idx += 1
def contract_layer_contours(layer, inset_distance):
    """
    Contract all contours in a layer, properly handling nested contours.
    """
    paths = safe_list(layer, "paths")
    if not paths:
        return
    
    # Determine nesting levels for all contours
    nesting_levels = determine_contour_nesting(paths)
    
    for i, path in enumerate(paths):
        # Odd nesting level = counter (hole), Even = outer contour
        is_counter = (nesting_levels[i] % 2) == 1
        contract_contour(path, inset_distance, is_counter)
# -------------------------------------------------------------------
# Flatten helpers
# -------------------------------------------------------------------
def flatten_layer(layer):
    all_nodes = []
    for path in safe_list(layer, "paths"):
        for node in path.nodes:
            all_nodes.append(node)
    if all_nodes:
        layer.selection = all_nodes
        layer.removeOverlap()
def flatten_background(layer):
    try:
        bg = layer.background
        all_nodes = []
        for path in safe_list(bg, "paths"):
            for node in path.nodes:
                all_nodes.append(node)
        if all_nodes:
            bg.selection = all_nodes
            bg.removeOverlap()
    except Exception:
        pass
# -------------------------------------------------------------------
# Build the new layer — preserving width, metrics keys, background
# -------------------------------------------------------------------
def copy_paths(src_layer, dst_layer):
    for path in safe_list(src_layer, "paths"):
        dst_layer.paths.append(path.copy())
def copy_components(src_layer, dst_layer):
    for comp in safe_list(src_layer, "components"):
        dst_layer.components.append(comp.copy())
def copy_anchors(src_layer, dst_layer):
    for anchor in safe_list(src_layer, "anchors"):
        try:
            dst_layer.anchors.append(anchor.copy())
        except Exception:
            pass
def copy_guidelines(src_layer, dst_layer):
    for guide in safe_list(src_layer, "guidelines"):
        try:
            dst_layer.guidelines.append(guide.copy())
        except Exception:
            pass
def copy_background(src_layer, dst_layer):
    try:
        src_bg = src_layer.background
        dst_bg = dst_layer.background
        for path in safe_list(src_bg, "paths"):
            dst_bg.paths.append(path.copy())
        for comp in safe_list(src_bg, "components"):
            dst_bg.components.append(comp.copy())
    except Exception:
        pass
def make_new_layer(glyph, source_layer, layer_name, master):
    new_layer = GSLayer()
    new_layer.name = layer_name
    new_layer.associatedMasterId = master.id
    new_layer.width = source_layer.width
    for key in ("leftMetricsKey", "rightMetricsKey", "widthMetricsKey"):
        try:
            val = getattr(source_layer, key, None)
            if val:
                setattr(new_layer, key, val)
        except Exception:
            pass
    glyph.layers.append(new_layer)
    copy_paths(source_layer, new_layer)
    copy_components(source_layer, new_layer)
    copy_anchors(source_layer, new_layer)
    copy_guidelines(source_layer, new_layer)
    if INCLUDE_BACKGROUND:
        copy_background(source_layer, new_layer)
    return new_layer
# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def run():
    font = Glyphs.font
    if not font:
        Message("No font open!", "Error")
        return
    master = font.selectedFontMaster
    base_name = build_base_name()
    if SELECTED_ONLY:
        tab = font.currentTab
        layers = list(tab.selectedLayers) if tab else []
        if not layers and font.selectedLayers:
            layers = list(font.selectedLayers)
        glyphs_to_process = [l.parent for l in layers if l.parent]
    else:
        glyphs_to_process = list(font.glyphs)
    if not glyphs_to_process:
        Message("No glyphs selected.", "Error")
        return
    font.disableUpdateInterface()
    count = 0
    try:
        for glyph in glyphs_to_process:
            source_layer = glyph.layers[master.id]
            if not source_layer or not safe_list(source_layer, "paths"):
                continue
            if CREATE_NEW_LAYER:
                layer_name = unique_layer_name(glyph, base_name)
                working_layer = make_new_layer(glyph, source_layer, layer_name, master)
            else:
                working_layer = source_layer
            if FLATTEN:
                flatten_layer(working_layer)
            if INCLUDE_BACKGROUND and FLATTEN_BACKGROUND:
                flatten_background(working_layer)
            # Use the new nesting-aware contraction
            contract_layer_contours(working_layer, INSET)
            if INCLUDE_BACKGROUND and OFFSET_BACKGROUND:
                try:
                    bg = working_layer.background
                    bg_paths = safe_list(bg, "paths")
                    if bg_paths:
                        bg_nesting = determine_contour_nesting(bg_paths)
                        for i, path in enumerate(bg_paths):
                            is_counter = (bg_nesting[i] % 2) == 1
                            contract_contour(path, INSET, is_counter)
                except Exception:
                    pass
            working_layer.updateMetrics()
            count += 1
    finally:
        font.enableUpdateInterface()
    if CREATE_NEW_LAYER:
        suffix = " on new layer '{}_001'".format(base_name)
    else:
        suffix = " on master layer"
    Message("Contracted {} glyph(s) by {} units{}.".format(count, INSET, suffix), "Done")
run()
