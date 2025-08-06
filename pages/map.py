import streamlit as st
import plotly.graph_objects as go
from shelf_map.shelf_map_handler import ShelfMapHandler

def map_with_textlabels(locs):
    import math
    shapes = []
    label_x = []
    label_y = []
    label_text = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    any_loc = False

    for row in locs:
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        min_x = min(min_x, x)
        min_y = min(min_y, y_draw)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y_draw + h)
        any_loc = True
        fill = "rgba(180,180,180,0.13)"
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
    if any_loc:
        expand_x = (max_x - min_x) * 0.07
        expand_y = (max_y - min_y) * 0.07
        fig.update_xaxes(visible=False, range=[min_x - expand_x, max_x + expand_x], constrain="domain", fixedrange=True)
        fig.update_yaxes(visible=False, range=[min_y - expand_y, max_y + expand_y], scaleanchor="x", scaleratio=1, fixedrange=True)
    else:
        fig.update_xaxes(visible=False, range=[0, 1], constrain="domain", fixedrange=True)
        fig.update_yaxes(visible=False, range=[0, 1], scaleanchor="x", scaleratio=1, fixedrange=True)
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

fig = map_with_textlabels(shelf_locs)
st.plotly_chart(fig, use_container_width=True)
