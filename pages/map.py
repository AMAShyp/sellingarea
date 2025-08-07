import streamlit as st
import plotly.graph_objects as go
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
    rgba = "rgba({}, {}, {}, 0.22)".format(
        int(hexcol[1:3],16), int(hexcol[3:5],16), int(hexcol[5:7],16)
    )
    return rgba, hexcol

def map_with_clusters(locs, clusters):
    import math
    shapes = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    cluster_map = {}
    color_map = {}
    for ci, clist in enumerate(clusters):
        rgba, hexcol = color_for_idx(ci)
        for idx in clist:
            cluster_map[idx] = ci
            color_map[ci] = (rgba, hexcol)
    for idx, row in enumerate(locs):
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        min_x = min(min_x, x)
        min_y = min(min_y, y_draw)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y_draw + h)
        fill = color_map[cluster_map[idx]][0]
        line = dict(width=1.2, color="#888")
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
        else:
            import math
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
    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=460, margin=dict(l=12, r=12, t=10, b=5), plot_bgcolor="#f8f9fa")
    expand_x = (max_x - min_x) * 0.07
    expand_y = (max_y - min_y) * 0.07
    fig.update_xaxes(visible=False, range=[min_x - expand_x, max_x + expand_x], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[min_y - expand_y, max_y + expand_y], scaleanchor="x", scaleratio=1, fixedrange=True)
    return fig, color_map

def fit_fontsize_for_shelf(w, h, text, base_size=14, min_size=8, max_size=20):
    shelf_area = max(w * h, 1e-7)
    norm_area = shelf_area / (0.10 * 0.06) # normalized
    font_size = base_size * (norm_area ** 0.35)
    if len(text) > 7:
        font_size *= 2
    return int(max(min(font_size, max_size), min_size))

def offset_label(x, y, w, h, deg=0, offset_frac=0.32):
    """
    Offset label to outside top-right of the shelf (offset_frac: as proportion of diagonal)
    Works for both rotated and non-rotated shelves.
    """
    import math
    cx = x + w/2
    cy = 1 - (y + h/2)
    # Offset direction: 45° (top right) relative to the rectangle orientation
    angle = math.radians(deg + 45)
    # Diagonal length for proportional offset
    diag = (w**2 + h**2) ** 0.5
    dx = math.cos(angle) * diag * offset_frac
    dy = math.sin(angle) * diag * offset_frac
    return cx + dx, cy + dy

def map_for_cluster(cluster, shelf_locs, color, hexcol):
    import math
    shapes = []
    labels_x = []
    labels_y = []
    labels_text = []
    labels_size = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for idx in cluster:
        row = shelf_locs[idx]
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx = x + w/2
        cy = 1 - (y + h/2)
        y_draw = 1 - y - h
        min_x = min(min_x, x)
        min_y = min(min_y, y_draw)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y_draw + h)
        fill = color
        line = dict(width=1.5, color=hexcol)
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
        label = str(row.get('locid', idx))
        fontsize = fit_fontsize_for_shelf(w, h, label)
        lx, ly = offset_label(x, y, w, h, deg, offset_frac=0.37)
        labels_x.append(lx)
        labels_y.append(ly)
        labels_text.append(label)
        labels_size.append(fontsize)
    fig = go.Figure()
    fig.update_layout(
        shapes=shapes,
        height=230,
        margin=dict(l=8, r=8, t=8, b=8),
        plot_bgcolor="#f8f9fa"
    )
    expand_x = (max_x - min_x) * 0.14
    expand_y = (max_y - min_y) * 0.14
    fig.update_xaxes(visible=False, range=[min_x - expand_x, max_x + expand_x], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[min_y - expand_y, max_y + expand_y], scaleanchor="x", scaleratio=1, fixedrange=True)
    for x, y, txt, size in zip(labels_x, labels_y, labels_text, labels_size):
        fig.add_trace(go.Scatter(
            x=[x], y=[y],
            mode='text',
            text=[txt],
            textfont=dict(color=hexcol, size=size, family='monospace'),
            textposition="middle center",
            hoverinfo="text+name",
            showlegend=False
        ))
    return fig

# ---- STREAMLIT APP ----

st.set_page_config(layout="centered")
st.title("🗺️ Shelf Map")

map_handler = ShelfMapHandler()
shelf_locs = map_handler.get_locations()

clusters = build_clusters(shelf_locs)
fig, color_map = map_with_clusters(shelf_locs, clusters)
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown("### 🟦 Cluster Details (clusters with ≥ 15 shelves)")

for i, cluster in enumerate(clusters):
    if len(cluster) < 15:
        continue
    rgba, hexcol = color_for_idx(i)
    st.markdown(
        f"<div style='display:inline-block;width:1.5em;height:1.5em;background:{hexcol};border-radius:4px;margin-right:0.5em;vertical-align:middle;'></div>"
        f"<b>Cluster {i+1}</b> <span style='color:{hexcol};font-size:2em;'>{hexcol}</span> <span style='color:#888;font-size:2em'>(count: {len(cluster)})</span>",
        unsafe_allow_html=True
    )
    locids = [shelf_locs[idx]['locid'] for idx in cluster]
    st.table({"locid": [str(locid) for locid in locids]})
    st.plotly_chart(map_for_cluster(cluster, shelf_locs, rgba, hexcol), use_container_width=True)
