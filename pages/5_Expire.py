import streamlit as st
import pandas as pd
import datetime
from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler
import plotly.graph_objects as go

# --- Config ---
LOCID_CSV_PATH = "assets/locid_list.csv"
locid_df = pd.read_csv(LOCID_CSV_PATH)
FILTERED_LOCIDS = set(str(l).strip() for l in locid_df["locid"].dropna().unique())

TODAY = datetime.date.today()

class ExpiryHandler(DatabaseManager):
    def get_expiry_shelf_items(self, locids):
        # Join shelf to item for shelflife, expirationdate, etc.
        q = """
            SELECT s.locid, s.itemid, i.itemnameenglish AS name, i.barcode,
                   s.quantity, s.expirationdate, i.shelflife
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = ANY(%s)
            AND s.quantity > 0
            AND s.expirationdate IS NOT NULL
            ORDER BY s.locid, s.expirationdate
        """
        df = self.fetch_data(q, (list(locids),))
        return df if not df.empty else pd.DataFrame(columns=["locid", "itemid", "name", "barcode", "quantity", "expirationdate", "shelflife"])

    def get_all_locids(self):
        return sorted(FILTERED_LOCIDS)

st.set_page_config(layout="wide")
st.title("⏳ Shelf Expiry Dashboard")

handler = ExpiryHandler()
map_handler = ShelfMapHandler()

st.markdown("## Near-Expiry and Expired Items (shelf batches)")
tab1, tab2 = st.tabs(["Days-Based Expiry", "Shelf-Life Fraction"])

# --- MAP RENDERING (with colored shelves) ---
def map_with_expiry(locs, shelf_colormap, label_map):
    import math
    shapes = []
    polygons = []
    label_x = []
    label_y = []
    label_text = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    any_loc = False

    color_map = {
        "red": "rgba(220,53,69,0.34)",
        "orange": "rgba(255,128,0,0.23)",
        "green": "rgba(40,160,20,0.20)",
        "gray": "rgba(180,180,180,0.11)"
    }
    line_map = {
        "red": "#d8000c",
        "orange": "#ff8000",
        "green": "#098A23",
        "gray": "#888"
    }

    for row in locs:
        locid = str(row["locid"])
        if locid not in FILTERED_LOCIDS:
            continue
        color = shelf_colormap.get(locid, "gray")
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        min_x = min(min_x, x)
        min_y = min(min_y, y_draw)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y_draw + h)
        any_loc = True
        fill = color_map.get(color, color_map["gray"])
        line = dict(width=2 if color != "gray" else 1.2, color=line_map.get(color, "#888"))
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
        label = label_map.get(locid, locid)
        label_x.append(cx)
        label_y.append(cy)
        label_text.append(label)
    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=430, margin=dict(l=12,r=12,t=10,b=5),
                      plot_bgcolor="#f8f9fa")
    if any_loc:
        expand_x = (max_x - min_x) * 0.07
        expand_y = (max_y - min_y) * 0.07
        fig.update_xaxes(visible=False, range=[min_x - expand_x, max_x + expand_x], constrain="domain", fixedrange=True)
        fig.update_yaxes(visible=False, range=[min_y - expand_y, max_y + expand_y], scaleanchor="x", scaleratio=1, fixedrange=True)
    else:
        fig.update_xaxes(visible=False, range=[0,1], constrain="domain", fixedrange=True)
        fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=1, fixedrange=True)
    fig.add_scatter(
        x=label_x, y=label_y, text=label_text,
        mode="text",
        textposition="middle center",
        textfont=dict(size=13, color="#003366", family="monospace"),
        showlegend=False,
        hoverinfo="none",
        name="LocID Labels"
    )
    return fig

# --- Tab 1: Days-Based Expiry ---
with tab1:
    st.subheader("⚡ Days-Based Expiry (classic expiry warning)")
    col1, col2, col3 = st.columns(3)
    with col1:
        red_days = st.number_input("Red (urgent, ≤ days)", min_value=1, max_value=180, value=7, step=1)
    with col2:
        orange_days = st.number_input("Orange (warning, ≤ days)", min_value=red_days+1, max_value=365, value=30, step=1)
    with col3:
        green_days = st.number_input("Green (informational, ≤ days)", min_value=orange_days+1, max_value=999, value=85, step=1)

    shelf_items = handler.get_expiry_shelf_items(FILTERED_LOCIDS)
    if shelf_items.empty:
        st.info("No shelf items with expiry dates found.")
    else:
        shelf_items["days_left"] = (pd.to_datetime(shelf_items["expirationdate"]).dt.date - TODAY).dt.days

        # Color coding and filtering
        def days_color(days):
            if days <= red_days:
                return "red"
            elif days <= orange_days:
                return "orange"
            elif days <= green_days:
                return "green"
            else:
                return None

        shelf_items["color"] = shelf_items["days_left"].apply(days_color)
        display_items = shelf_items[shelf_items["color"].notnull()].copy()

        st.markdown("#### 🟦 Map: Shelf with expiring items (red=most urgent, orange=soon, green=informational)")
        # For map coloring: use max urgency per locid
        shelf_colormap = {}
        label_map = {}
        for locid, group in display_items.groupby("locid"):
            if "red" in group["color"].values:
                shelf_colormap[locid] = "red"
            elif "orange" in group["color"].values:
                shelf_colormap[locid] = "orange"
            elif "green" in group["color"].values:
                shelf_colormap[locid] = "green"
            else:
                shelf_colormap[locid] = "gray"
            # Show most urgent item expiring soonest on label
            label_map[locid] = group.sort_values("days_left").iloc[0]["name"]

        shelf_locs = [row for row in map_handler.get_locations() if str(row["locid"]) in FILTERED_LOCIDS]
        st.plotly_chart(map_with_expiry(shelf_locs, shelf_colormap, label_map), use_container_width=True)

        st.markdown("#### Items near expiry (within alert window):")
        st.dataframe(
            display_items[["locid", "name", "barcode", "quantity", "expirationdate", "days_left", "color"]]
            .rename(columns={
                "locid": "Shelf",
                "name": "Item Name",
                "barcode": "Barcode",
                "quantity": "Qty",
                "expirationdate": "Expiry Date",
                "days_left": "Days Left",
                "color": "Band"
            }),
            use_container_width=True,
            hide_index=True
        )

# --- Tab 2: Shelf-Life Fraction Expiry ---
with tab2:
    st.subheader("⚡ Shelf-Life Fraction (shelf-life used up)")

    col1, col2, col3 = st.columns(3)
    with col1:
        red_frac = st.number_input("Red (urgent, ≤ fraction left)", min_value=0.00, max_value=1.00, value=0.20, step=0.01, format="%.2f")
    with col2:
        orange_frac = st.number_input("Orange (warning, ≤ fraction left)", min_value=red_frac+0.01, max_value=1.00, value=0.40, step=0.01, format="%.2f")
    with col3:
        green_frac = st.number_input("Green (informational, ≤ fraction left)", min_value=orange_frac+0.01, max_value=1.00, value=0.80, step=0.01, format="%.2f")

    shelf_items = handler.get_expiry_shelf_items(FILTERED_LOCIDS)
    if shelf_items.empty:
        st.info("No shelf items with expiry dates found.")
    else:
        # Calculate fraction left
        shelf_items["days_left"] = (pd.to_datetime(shelf_items["expirationdate"]).dt.date - TODAY).dt.days
        # shelflife can be None or zero (invalid)
        shelf_items["shelflife"] = pd.to_numeric(shelf_items["shelflife"], errors="coerce")
        shelf_items["fraction_left"] = shelf_items["days_left"] / shelf_items["shelflife"]
        shelf_items["fraction_left"] = shelf_items["fraction_left"].where(shelf_items["shelflife"] > 0, None)

        # Color coding and filtering
        def frac_color(frac):
            if frac is None or pd.isna(frac):
                return None
            elif frac <= red_frac:
                return "red"
            elif frac <= orange_frac:
                return "orange"
            elif frac <= green_frac:
                return "green"
            else:
                return None

        shelf_items["color"] = shelf_items["fraction_left"].apply(frac_color)
        display_items = shelf_items[shelf_items["color"].notnull()].copy()

        st.markdown("#### 🟦 Map: Shelf with used-up shelf life (red=most urgent, orange=soon, green=informational)")
        # For map coloring: use max urgency per locid
        shelf_colormap = {}
        label_map = {}
        for locid, group in display_items.groupby("locid"):
            if "red" in group["color"].values:
                shelf_colormap[locid] = "red"
            elif "orange" in group["color"].values:
                shelf_colormap[locid] = "orange"
            elif "green" in group["color"].values:
                shelf_colormap[locid] = "green"
            else:
                shelf_colormap[locid] = "gray"
            label_map[locid] = group.sort_values("fraction_left").iloc[0]["name"]

        shelf_locs = [row for row in map_handler.get_locations() if str(row["locid"]) in FILTERED_LOCIDS]
        st.plotly_chart(map_with_expiry(shelf_locs, shelf_colormap, label_map), use_container_width=True)

        st.markdown("#### Items with low shelf-life left:")
        st.dataframe(
            display_items[["locid", "name", "barcode", "quantity", "expirationdate", "days_left", "shelflife", "fraction_left", "color"]]
            .rename(columns={
                "locid": "Shelf",
                "name": "Item Name",
                "barcode": "Barcode",
                "quantity": "Qty",
                "expirationdate": "Expiry Date",
                "days_left": "Days Left",
                "shelflife": "Shelf Life",
                "fraction_left": "Fraction Left",
                "color": "Band"
            }),
            use_container_width=True,
            hide_index=True
        )

        # Items missing shelf-life value
        missing_shelf_life = shelf_items[shelf_items["shelflife"].isna() | (shelf_items["shelflife"] <= 0)]
        if not missing_shelf_life.empty:
            st.markdown("#### ⚠️ Items missing shelf-life definition (not color-coded):")
            st.dataframe(
                missing_shelf_life[["locid", "name", "barcode", "quantity", "expirationdate", "days_left"]]
                .rename(columns={
                    "locid": "Shelf",
                    "name": "Item Name",
                    "barcode": "Barcode",
                    "quantity": "Qty",
                    "expirationdate": "Expiry Date",
                    "days_left": "Days Left"
                }),
                use_container_width=True,
                hide_index=True
            )
