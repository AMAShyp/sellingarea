import streamlit as st
import pandas as pd
from datetime import date
from selling_area.shelf_handler import ShelfHandler
from shelf_map.shelf_map_handler import ShelfMapHandler
import plotly.graph_objects as go

def map_with_highlights(locs, highlight_locs, color="#d8000c", alpha=0.32):
    import math
    shapes = []
    for row in locs:
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        is_hi = row["locid"] in highlight_locs
        fill = f"rgba(220,53,69,{alpha})" if is_hi else "rgba(180,180,180,0.09)"
        line = dict(width=2 if is_hi else 1.2, color=color if is_hi else "#888")
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            path = "M " + " L ".join(f"{cx+u*cos-v*sin},{cy+u*sin+v*cos}" for u, v in pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        if is_hi:
            r = max(w, h) * 0.5
            shapes.append(dict(type="circle",xref="x",yref="y",
                               x0=cx-r,x1=cx+r,y0=cy-r,y1=cy+r,
                               line=dict(color=color,width=2,dash="dot")))
    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=330, margin=dict(l=12,r=12,t=10,b=5),
                      plot_bgcolor="#f8f9fa")
    fig.update_xaxes(visible=False, range=[0,1], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=1, fixedrange=True)
    for row in locs:
        if row["locid"] in highlight_locs:
            x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
            fig.add_annotation(
                x=x + w/2,
                y=1 - (y + h/2) + 0.012,
                text=row.get("label",row["locid"]),
                showarrow=False,
                font=dict(size=11, color="#c90000", family="monospace"),
                align="center",
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="#d8000c",
                borderpad=2,
                opacity=0.97,
            )
    return fig

st.set_page_config(page_title="Near Expiry Items", layout="wide")
st.title("⏰ Near Expiry Shelf Items")

try:
    shelf_handler = ShelfHandler()
    shelf_df = shelf_handler.get_shelf_items()
    st.write("DEBUG: Raw shelf_df columns", list(shelf_df.columns))
    st.write("DEBUG: Raw shelf_df sample", shelf_df.head())
    shelf_df.columns = [c.lower() for c in shelf_df.columns]
    st.write("DEBUG: shelf_df (lower-case) columns", list(shelf_df.columns))
    if shelf_df.empty:
        st.info("No items in the selling area.")
        st.stop()

    # Defensive debug: make sure locid exists
    if "locid" not in shelf_df.columns:
        st.error("❌ 'locid' is missing from your shelf query. Check your ShelfHandler SQL!")
        st.stop()
    # Map handler and locations
    map_handler = ShelfMapHandler()
    shelf_locs = map_handler.get_locations()
    st.write("DEBUG: Map shelf_locs count", len(shelf_locs))
    if len(shelf_locs) > 0:
        st.write("DEBUG: Map shelf_locs sample", pd.DataFrame(shelf_locs).head())

    today = pd.to_datetime(date.today())
    shelf_df["expirationdate"] = pd.to_datetime(shelf_df["expirationdate"])
    shelf_df["days_left"] = (shelf_df["expirationdate"] - today).dt.days

    # bring shelf-life info
    item_df = shelf_handler.fetch_data("SELECT itemid, shelflife FROM item")
    st.write("DEBUG: Raw item_df columns", list(item_df.columns))
    st.write("DEBUG: Raw item_df sample", item_df.head())
    item_df.columns = [c.lower() for c in item_df.columns]
    st.write("DEBUG: item_df (lower-case) columns", list(item_df.columns))
    shelf_df = shelf_df.merge(item_df, on="itemid", how="left")
    st.write("DEBUG: shelf_df after merge columns", list(shelf_df.columns))
    st.write("DEBUG: shelf_df after merge sample", shelf_df.head())

    subtab_days, subtab_percent = st.tabs(["📅 Days-Based", "📐 Shelf Life %"])

    # SUBTAB A: Days-Based
    with subtab_days:
        st.markdown("#### ⚙️ Customize Alert Thresholds (Days)")

        col_red, col_orange, col_green = st.columns(3)
        red_days = col_red.number_input(
            "🔴 Red (≤ days)", min_value=1, value=7, step=1
        )
        orange_days = col_orange.number_input(
            "🟠 Orange (≤ days)",
            min_value=red_days + 1,
            value=max(30, red_days + 1),
            step=1,
        )
        green_days = col_green.number_input(
            "🟢 Green (≤ days)",
            min_value=orange_days + 1,
            value=max(85, orange_days + 1),
            step=1,
        )

        near_expiry_df = shelf_df[shelf_df["days_left"] <= green_days].copy()
        st.write("DEBUG: near_expiry_df columns", list(near_expiry_df.columns))
        st.write("DEBUG: near_expiry_df sample", near_expiry_df.head())
        if near_expiry_df.empty:
            st.success(
                f"✅ No items expiring within {green_days} days."
            )
        else:
            hi_locs = sorted(set(near_expiry_df["locid"].dropna().unique()))
            st.markdown("#### 🗺️ Shelf Map: Red = shelves with near-expiry items")
            st.plotly_chart(map_with_highlights(shelf_locs, hi_locs), use_container_width=True)

            def color_days(val: int) -> str:
                if val <= red_days:
                    return "background-color: red; color: white;"
                if val <= orange_days:
                    return "background-color: orange;"
                if val <= green_days:
                    return "background-color: green; color: white;"
                return ""

            styled = near_expiry_df[
                ["itemname", "quantity", "expirationdate", "days_left"]
            ].style.map(color_days, subset=["days_left"])

            st.warning(
                f"⚠️ Items expiring within {green_days} days:"
            )
            st.write(styled)

            st.info(
                "🔎 **Color-Coding (Days)**\n"
                f"- 🔴 ≤ {red_days} days left\n"
                f"- 🟠 {red_days + 1}-{orange_days} days left\n"
                f"- 🟢 {orange_days + 1}-{green_days} days left"
            )

    # SUBTAB B: Shelf Life Fraction
    with subtab_percent:
        st.markdown(
            "#### ⚙️ Customize Alert Thresholds (Fraction of Shelf Life)"
        )

        col_r, col_o, col_g = st.columns(3)
        red_frac = col_r.number_input(
            "🔴 Red (≤ fraction)",
            min_value=0.0,
            max_value=1.0,
            value=0.20,
            step=0.05,
            format="%.2f",
        )
        orange_frac = col_o.number_input(
            "🟠 Orange (≤ fraction)",
            min_value=red_frac + 0.01,
            max_value=1.0,
            value=max(0.40, red_frac + 0.01),
            step=0.05,
