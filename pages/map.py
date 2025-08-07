import streamlit as st
import pydeck as pdk
import pandas as pd
import numpy as np
from shelf_map.shelf_map_handler import ShelfMapHandler

def to_float(x):
    try:
        return float(x)
    except:
        return 0.0

def shelves_are_adjacent(a, b, tol=1e-7):
    ax1, ay1, aw, ah = map(to_float, (a['x_pct'], a['y_pct'], a['w_pct'], a['h_pct']))
    bx1, by1, bw, bh = map(to_float, (b['x_pct'], b['y_pct'], b['w_pct'], b['h_pct']))
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    return not (ax2 < bx1 - tol or bx2 < ax1 - tol or ay2 < by1 - tol or by2 < ay1 - tol)

def build_clusters(locs):
    n = len(locs)
    visited = [False] * n
    clusters = []
    for i in range(n):
        if not visited[i]:
            cluster = []
            queue = [i]
            visited[i] = True
            while queue:
                curr = queue.pop(0)
                cluster.append(curr)
                for j in range(n):
                    if not visited[j] and shelves_are_adjacent(locs[curr], locs[j]):
                        visited[j] = True
                        queue.append(j)
            clusters.append(cluster)
    return clusters

def color_for_idx(idx):
    COLORS = [
        "#dc3545", "#0275d8", "#5cb85c", "#f0ad4e", "#9b59b6", "#333333", "#800080", "#008080",
        "#FFD700", "#E67E22", "#C0392B", "#16A085", "#7B241C", "#1ABC9C",
    ]
    hexcol = COLORS[idx % len(COLORS)]
    # Convert HEX to RGB for pydeck
    rgb = tuple(int(hexcol[i:i+2], 16) for i in (1, 3, 5))
    return rgb, hexcol

def make_rectangle(x, y, w, h, deg):
    """
    Returns the four corners of a rectangle (counterclockwise)
    given its top-left x, y, width, height, and rotation (deg).
    All values in normalized (0–1) floor units.
    Note: Deck.gl expects [lng, lat] so x is lon, y is lat.
    """
    cx = x + w / 2
    cy = y + h / 2
    rad = np.deg2rad(deg)
    cos, sin = np.cos(rad), np.sin(rad)
    # Rectangle corners relative to center (counterclockwise from top-left)
    corners = np.array([
        [-w/2, -h/2],
        [ w/2, -h/2],
        [ w/2,  h/2],
        [-w/2,  h/2]
    ])
    # Apply rotation
    rotated = np.dot(corners, np.array([[cos, -sin],[sin, cos]]))
    # Shift to absolute center
    abs_pts = rotated + [cx, cy]
    # pydeck wants [lng, lat] (so: x, y)
    return abs_pts.tolist()

def shelf_map_pydeck(shelf_locs, clusters):
    # Build polygons and labels for all shelves, color by cluster
    polygons = []
    labels = []
    cluster_map = {}
    color_map = {}
    for ci, clist in enumerate(clusters):
        rgb, hexcol = color_for_idx(ci)
        for idx in clist:
            cluster_map[idx] = ci
            color_map[ci] = (rgb, hexcol)
    for idx, row in enumerate(shelf_locs):
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        coords = make_rectangle(x, y, w, h, deg)
        # Deck.gl: must close the polygon (repeat the first point at the end)
        coords.append(coords[0])
        ci = cluster_map[idx]
        rgb = color_map[ci][0]
        label = str(row.get('label') or row.get('locid') or idx)
        # Polygon for shelf
        polygons.append({
            "polygon": coords,
            "label": label,
            "locid": row.get('locid'),
            "fill_color": list(rgb) + [150],  # semi-transparent
            "line_color": list(rgb) + [255]
        })
        # Text label: center of shelf
        cx = x + w / 2
        cy = y + h / 2
        labels.append({
            "position": [cx, cy],
            "text": label,
            "color": [0,0,0,255],  # black text
        })
    poly_df = pd.DataFrame(polygons)
    label_df = pd.DataFrame(labels)
    # Create layers
    polygon_layer = pdk.Layer(
        "PolygonLayer",
        data=poly_df,
        get_polygon="polygon",
        get_fill_color="fill_color",
        get_line_color="line_color",
        pickable=True,
        auto_highlight=True,
    )
    label_layer = pdk.Layer(
        "TextLayer",
        data=label_df,
        get_position="position",
        get_text="text",
        get_color="color",
        get_size=18,
        get_alignment_baseline="'center'",
        get_text_anchor="'middle'",
        pickable=False,
    )
    # Compose deck
    view_state = pdk.ViewState(
        longitude=0.5, latitude=0.5, zoom=6, min_zoom=4, max_zoom=20, pitch=0, bearing=0,
    )
    r = pdk.Deck(
        layers=[polygon_layer, label_layer],
        initial_view_state=view_state,
        map_provider=None,    # disables basemap
        tooltip={"text": "{label}"},
        height=550,
    )
    return r

# ---- STREAMLIT APP ----

st.set_page_config(layout="centered")
st.title("🗺️ Shelf Map (Deck.gl view)")

map_handler = ShelfMapHandler()
shelf_locs = map_handler.get_locations()
clusters = build_clusters(shelf_locs)

# Deck.gl map view:
st.pydeck_chart(shelf_map_pydeck(shelf_locs, clusters))

st.markdown("---")
st.markdown("### 🟦 Cluster Details (clusters with ≥ 15 shelves)")
for i, cluster in enumerate(clusters):
    if len(cluster) < 15:
        continue
    rgb, hexcol = color_for_idx(i)
    st.markdown(
        f"<div style='display:inline-block;width:1.5em;height:1.5em;background:{hexcol};border-radius:4px;margin-right:0.5em;vertical-align:middle;'></div>"
        f"<b>Cluster {i+1}</b> <span style='color:{hexcol};font-size:1em;'>{hexcol}</span> <span style='color:#888;font-size:0.96em'>(count: {len(cluster)})</span>",
        unsafe_allow_html=True
    )
    locids = [shelf_locs[idx]['locid'] for idx in cluster]
    st.table({"locid": [str(locid) for locid in locids]})
