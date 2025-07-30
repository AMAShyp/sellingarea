import math, time, logging, inspect
import streamlit as st
import plotly.graph_objects as go
from PIL import Image

from shelf_map.shelf_map_handler import ShelfMapHandler
from shelf_map.shelf_map_utils   import shelf_selector, item_locator

log  = logging.getLogger("shelfmap"); log.setLevel(logging.INFO)
handler = ShelfMapHandler()

def _img_ratio(path: str = "assets/shelf_map.png") -> float:
    try:
        with open(path, "rb") as f:
            f.seek(16)
            width = int.from_bytes(f.read(4), "big")
            height = int.from_bytes(f.read(4), "big")
        return height / width
    except Exception:
        return 1.0

PNG_RATIO = _img_ratio()

@st.cache_data(ttl=3600)
def load_locations():
    return handler.get_locations()

@st.cache_resource
def load_bg():
    return Image.open("assets/shelf_map.png")

def inside(px: float, py: float, row: dict) -> bool:
    w = float(row["w_pct"])
    h = float(row["h_pct"])
    cx = float(row["x_pct"]) + w / 2
    cy = 1 - (float(row["y_pct"]) + h / 2)  # flip Y once
    try:
        px = float(px)
        py = float(py)
    except Exception:
        return False
    dx, dy = px - cx, py - cy
    deg = float(row.get("rotation_deg") or 0.0)
    if deg:
        rad = -math.radians(deg)
        cos, sin = math.cos(rad), math.sin(rad)
        dx, dy = dx * cos - dy * sin, dx * sin + dy * cos
    return abs(dx) <= w/2 and abs(dy) <= h/2

def map_tab():
    st.title("🗺️ Interactive Shelf Map")
    t0 = time.time()

    show_png = st.checkbox("Show floor-plan image", value=True)
    locs  = load_locations()
    if not locs or len(locs) == 0:
        st.error("No shelf locations found! Please check your shelf map data.")
        return

    img   = load_bg() if show_png else None

    col_shelf, col_name, col_barcode = st.columns(3)
    with col_shelf:
        dropdown = shelf_selector(locs)

    item_loc, item_id, searched = item_locator(handler, col_name, col_barcode)

    highlight = st.session_state.get("shelfmap_highlight")
    if isinstance(highlight, str):
        highlight = [highlight]

    not_found = False

    if item_loc:
        new = item_loc if isinstance(item_loc, list) else [item_loc]
        if new != highlight:
            highlight = new
            st.session_state["shelfmap_highlight"] = highlight
    elif searched:
        highlight = None
        st.session_state.pop("shelfmap_highlight", None)
        not_found = True
    elif dropdown and highlight != [dropdown]:
        highlight = [dropdown]
        st.session_state["shelfmap_highlight"] = highlight

    title_hi = ", ".join(highlight) if isinstance(highlight, list) else highlight
    msg = "This item is not available in shelves" if not_found else (f"Highlight: {title_hi}" if highlight else "No shelf highlighted")
    st.caption(f"⌛ {msg} ({time.time()-t0:.2f}s)")

    # Draw rectangles & halo
    shapes = []
    for row in locs:
        x = float(row["x_pct"])
        y = float(row["y_pct"])
        w = float(row["w_pct"])
        h = float(row["h_pct"])
        deg = float(row.get("rotation_deg") or 0.0)
        cx = x + w/2
        cy = 1 - (y + h/2)
        y = 1 - y - h  # flip Y for drawing
        is_hi = highlight and row["locid"] in highlight
        fill  = "rgba(26,188,156,0.15)" if not is_hi else "rgba(255,128,0,0.25)"
        line  = dict(width=2 if is_hi else 1,
                     color="#FF8000" if is_hi else "#1ABC9C")

        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y, x1=x+w, y1=y+h,
                               line=line, fillcolor=fill))
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            path = "M " + " L ".join(
                f"{cx+u*cos-v*sin},{cy+u*sin+v*cos}" for u, v in pts) + " Z"
            shapes.append(dict(type="path", path=path,
                               line=line, fillcolor=fill))

        if is_hi:
            r = max(w, h) * 0.65
            shapes.append(dict(type="circle", xref="x", yref="y",
                               x0=cx - r, x1=cx + r, y0=cy - r, y1=cy + r,
                               line=dict(color="#FF8000", width=2, dash="dot")))

    # Plotly figure
    fig = go.Figure()
    if img is not None:
        fig.add_layout_image(dict(
            source=img, xref="x", yref="y",
            x=0, y=1, sizex=1, sizey=1,
            xanchor="left", yanchor="top", layer="below"))

    fig.update_layout(shapes=shapes, height=700,
                      margin=dict(l=0,r=0,t=0,b=0))
    fig.update_xaxes(visible=False, range=[0,1], constrain="domain")
    fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=PNG_RATIO)

    # Add cover points for clicking
    step = 0.01
    grid = [i * step for i in range(int(1 / step) + 1)]
    cover_x = []
    cover_y = []
    for x in grid:
        cover_x.extend([x] * len(grid))
        cover_y.extend(grid)
    fig.add_trace(go.Scatter(
        x=cover_x, y=cover_y, mode="markers",
        marker=dict(size=1, opacity=0),
        hoverinfo="none", showlegend=False))

    st.plotly_chart(fig, key="shelfmap", height=700)

    # Shelf panel if highlighted
    if highlight:
        title = ", ".join(highlight) if isinstance(highlight, list) else str(highlight)
        st.subheader(f"📍 {title}")
        if isinstance(highlight, list) and len(highlight) == 1:
            shelf = highlight[0]
            stock = handler.get_stock_by_location(shelf)
            if stock is not None and not stock.empty:
                st.dataframe(stock, use_container_width=True)
            else:
                st.info("No items on this shelf.")

    # Item panel if searched
    if item_id:
        item_stock = handler.get_stock_for_item(item_id)
        st.markdown("---")
        st.subheader("📝 Item Availability")
        if item_stock is not None and not item_stock.empty:
            st.dataframe(item_stock, use_container_width=True)
        else:
            st.info("Item not found on shelf.")

# --- Always call map_tab for Streamlit pages ---
map_tab()
