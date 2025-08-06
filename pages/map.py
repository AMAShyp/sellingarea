import streamlit as st
import plotly.graph_objects as go
from shelf_map.shelf_map_handler import ShelfMapHandler

def to_float(x):
    try:
        return float(x)
    except:
        return 0.0

def shelves_are_adjacent(a, b, tol=1e-7):
    # Accepts shelf dicts. Works for axis-aligned rectangles only.
    ax1, ay1, aw, ah = map(to_float, (a['x_pct'], a['y_pct'], a['w_pct'], a['h_pct']))
    bx1, by1, bw, bh = map(to_float, (b['x_pct'], b['y_pct'], b['w_pct'], b['h_pct']))
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    # Check for rectangles touching or overlapping (using <= and >= with tolerance)
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
        "rgba(220,53,69,0.27)",     # red
        "rgba(2,117,216,0.22)",     # blue
        "rgba(92,184,92,0.21)",     # green
        "rgba(240,173,78,0.17)",    # orange
        "rgba(155,89,182,0.19)",    # purple
        "rgba(51,51,51,0.14)",      # gray
        "rgba(128,0,128,0.18)",     # violet
        "rgba(0,128,128,0.18)",     # teal
    ]
    return COLORS[idx % len(COLORS)]

def map_with_clusters(locs, clusters=None):
    import math
    shapes = []
    label_x, label_y, label_text = [], [], []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    cluster_map = {}
    if clusters:
        for ci, clist in enumerate(clusters):
            for idx in clist:
                cluster_map[idx] = ci
    for idx, row in enumerate(locs):
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        min_x = min(min_x, x)
        min_y = min(min_y, y_draw)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y_draw + h)
        fill = color_for_idx(cluster_map[idx]) if clusters else "rgba(180,180,180,0.11)"
        line = dict(width=1.2, color="#888")
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            abs_pts = [(cx + u * cos - v * sin, cy + u * sin + v * cos) for u, v in pts]
            min_x = min([min_x] + [p[0] for p in abs_pts])
            min_y = min([min_y] + [p[1] for p in abs_pts])
            max_x = max([max_x] + [p[0] for p in abs_pts])
            max_y = max([max_y] + [p[1] for p in abs_pts])
            path = "M " + " L ".join(f"{x_},{y_}" for x_, y_ in abs_pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        label_x.append(cx)
        label_y.append(cy)
        label_text.append(row.get("label", row["locid"]))

    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=460, margin=dict(l=12, r=12, t=10, b=5), plot_bgcolor="#f8f9fa")
    expand_x = (max_x - min_x) * 0.07
    expand_y = (max_y - min_y) * 0.07
    fig.update_xaxes(visible=False, range=[min_x - expand_x, max_x + expand_x], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[min_y - expand_y, max_y + expand_y], scaleanchor="x", scaleratio=1, fixedrange=True)
    fig.add_scatter(
        x=label_x, y=label_y, text=label_text,
        mode="text",
        textposition="middle center",
        textfont=dict(size=13, color="#19375a", family="monospace"),
        showlegend=False,
        hoverinfo="none",
        name="LocID Labels"
    )
    return fig

st.set_page_config(layout="centered")
st.title("🗺️ Shelf Map")

map_handler = ShelfMapHandler()
shelf_locs = map_handler.get_locations()

cluster_mode = st.checkbox("Show shelf clusters (by physical neighborhood/alignment)", value=False)

if cluster_mode:
    clusters = build_clusters(shelf_locs)
    fig = map_with_clusters(shelf_locs, clusters)
    st.info(f"Detected {len(clusters)} shelf clusters (connected shelf groups) on map.")
else:
    fig = map_with_clusters(shelf_locs, None)

st.plotly_chart(fig, use_container_width=True)
