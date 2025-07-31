import streamlit as st
from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler
import plotly.graph_objects as go

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

try:
    from streamlit_plotly_events import plotly_events
    PLOTLY_EVENTS_AVAILABLE = True
except ImportError:
    PLOTLY_EVENTS_AVAILABLE = False

class DeclareHandler(DatabaseManager):
    def get_item_by_barcode(self, barcode):
        df = self.fetch_data("""
            SELECT itemid, itemnameenglish AS name, barcode,
                   familycat, sectioncat, departmentcat, classcat
            FROM item
            WHERE barcode = %s
            LIMIT 1
        """, (barcode,))
        return df.iloc[0] if not df.empty else None

    def get_shelf_entries(self, itemid):
        df = self.fetch_data("""
            SELECT locid, SUM(quantity) as qty
            FROM shelf
            WHERE itemid=%s
            GROUP BY locid
            ORDER BY locid
        """, (int(itemid),))
        return df

    def get_inventory_total(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (int(itemid),))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] is not None else 0

    def subtract_inventory(self, itemid, qty):
        batches = self.fetch_data("""
            SELECT expirationdate, cost_per_unit, quantity
            FROM inventory
            WHERE itemid=%s AND quantity > 0
            ORDER BY expirationdate ASC, cost_per_unit ASC
        """, (int(itemid),))
        left = qty
        for _, row in batches.iterrows():
            take = min(left, int(row['quantity']))
            self.execute_command(
                """
                UPDATE inventory SET quantity=quantity-%s
                WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity>=%s
                """,
                (take, int(itemid), row['expirationdate'], row['cost_per_unit'], take)
            )
            left -= take
            if left <= 0:
                break
        return qty - left

    def set_shelf_quantity(self, itemid, locid, qty):
        exists = self.fetch_data(
            "SELECT quantity FROM shelf WHERE itemid=%s AND locid=%s",
            (int(itemid), locid)
        )
        if exists.empty:
            self.execute_command("""
                INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, CURRENT_DATE, %s, 0, %s)
            """, (int(itemid), qty, locid))
        else:
            self.execute_command("""
                UPDATE shelf SET quantity=%s WHERE itemid=%s AND locid=%s
            """, (qty, int(itemid), locid))

    def get_all_locids(self):
        df = self.fetch_data("""
            SELECT locid FROM shelf_map_locations ORDER BY locid
        """)
        return df["locid"].tolist() if not df.empty else []

# --- MAP rendering function, returns a Plotly figure and a list of shelf polygons/labels
def map_with_highlights_and_hover(locs, highlight_locs, label_offset=0.018):
    import math
    shapes = []
    polygons = []
    trace_x = []
    trace_y = []
    trace_text = []
    for row in locs:
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        is_hi = row["locid"] in highlight_locs
        fill = "rgba(220,53,69,0.34)" if is_hi else "rgba(180,180,180,0.11)"
        line = dict(width=2 if is_hi else 1.2, color="#d8000c" if is_hi else "#888")
        # For clickability, we'll record the center
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
            trace_x.append(cx)
            trace_y.append(cy)
            trace_text.append(row.get("label", row["locid"]))
            polygons.append({
                "locid": row["locid"],
                "center": (cx, cy)
            })
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            abs_pts = [(cx + u * cos - v * sin, cy + u * sin + v * cos) for u, v in pts]
            # Plot invisible scatter for clickable center
            trace_x.append(cx)
            trace_y.append(cy)
            trace_text.append(row.get("label", row["locid"]))
            polygons.append({
                "locid": row["locid"],
                "center": (cx, cy)
            })
            path = "M " + " L ".join(f"{x_},{y_}" for x_, y_ in abs_pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        if is_hi:
            r = max(w, h) * 0.5
            shapes.append(dict(type="circle",xref="x",yref="y",
                               x0=cx-r,x1=cx+r,y0=cy-r,y1=cy+r,
                               line=dict(color="#d8000c",width=2,dash="dot")))
    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=340, margin=dict(l=12,r=12,t=10,b=5),
                      plot_bgcolor="#f8f9fa")
    fig.update_xaxes(visible=False, range=[0,1], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=1, fixedrange=True)
    # Add invisible scatter points at each shelf center, so clicks will register there
    fig.add_scatter(
        x=trace_x, y=trace_y, text=trace_text,
        mode="markers",
        marker=dict(size=16, opacity=0.3, color="rgba(0,0,0,0.1)"),
        hoverinfo="text",
        name="Shelves"
    )
    for row in locs:
        if row["locid"] in highlight_locs:
            x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
            fig.add_annotation(
                x=x + w/2,
                y=1 - (y + h/2) + label_offset,
                text=row.get("label",row["locid"]),
                showarrow=False,
                font=dict(size=11, color="#c90000", family="monospace"),
                align="center",
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="#d8000c",
                borderpad=2,
                opacity=0.97,
            )
    return fig, polygons, trace_text

st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode)")

handler = DeclareHandler()
map_handler = ShelfMapHandler()

st.markdown("""
<style>
.catline {margin:0.08em 0 0.09em 0;font-size:1.1em;}
.cat-class {color:#C61C1C;font-weight:bold;}
.cat-dept {color:#004CBB;font-weight:bold;}
.cat-sect {color:#098A23;font-weight:bold;}
.cat-family {color:#FF8800;font-weight:bold;}
.cat-val {color:#111;}
.scan-hint {
    font-size: 1.28em;
    color: #087911;
    font-weight: 600;
    background: #eafdff;
    padding: .14em .7em .13em .7em;
    border-radius: .45em;
    margin: .2em 0 .5em 0;
    text-align:center;
}
</style>
""", unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📷 Scan via camera", "⌨️ Type/paste barcode"])

def declare_logic(barcode, reset_callback):
    if not barcode:
        st.info("Please scan or enter the item barcode.")
        return

    item = handler.get_item_by_barcode(barcode)
    if item is not None:
        st.markdown(f"**Item:** {item['name']}<br>🔖 Barcode: `{item['barcode']}`", unsafe_allow_html=True)
        st.markdown(
            f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{item['classcat']}</span></div>"
            f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{item['departmentcat']}</span></div>"
            f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{item['sectioncat']}</span></div>"
            f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{item['familycat']}</span></div>",
            unsafe_allow_html=True)
        itemid = int(item['itemid'])
        shelf_entries = handler.get_shelf_entries(itemid)
        inventory_total = handler.get_inventory_total(itemid)
        all_locids = handler.get_all_locids()

        # Show shelf map for this item after any valid scan or entry, with interactivity
        shelf_locs = map_handler.get_locations()
        highlight_locs = shelf_entries["locid"].tolist() if not shelf_entries.empty else []
        st.markdown("#### 🗺️ Shelf Map — click anywhere to see shelf name/ID")
        fig, polygons, trace_text = map_with_highlights_and_hover(shelf_locs, highlight_locs)
        clicked_locid = None

        if PLOTLY_EVENTS_AVAILABLE:
            events = plotly_events(fig, click_event=True, hover_event=False, select_event=False, key="main_shelf_map", override_height=350)
            if events:
                point = events[0]
                idx = point["pointIndex"]
                if 0 <= idx < len(polygons):
                    clicked_locid = polygons[idx]["locid"]
                    st.success(f"You clicked: **{clicked_locid}**")
        else:
            st.plotly_chart(fig, use_container_width=True)
            st.info("Install `streamlit-plotly-events` for click support: `pip install streamlit-plotly-events`")

        prev_qty = 0
        prev_locid = ""
        if shelf_entries.empty:
            st.warning("No previous quantity declared for this item in the selling area.")
        else:
            prev_locid = shelf_entries['locid'].iloc[0] if len(shelf_entries)==1 else ""
            prev_qty = int(shelf_entries['qty'].iloc[0]) if len(shelf_entries)==1 else 0

        locid = st.selectbox(
            "Shelf Location (locid)",
            options=all_locids,
            index=all_locids.index(prev_locid) if prev_locid in all_locids else 0 if all_locids else 0,
            key="declare_locid",
            help="Start typing to search and select the shelf location."
        ) if all_locids else st.text_input("Shelf Location (locid)", key="declare_locid", max_chars=32)

        st.info(f"**Current (previous) quantity in selling area:** {prev_qty}  \n"
                f"**Available in inventory:** {inventory_total}")

        new_qty = st.number_input("Declare current selling area quantity", min_value=0, value=prev_qty, step=1, key="declare_qty")

        col1, col2 = st.columns([2,1])
        with col1:
            confirm = st.button("✅ Confirm Declaration", type="primary")
        with col2:
            if st.button("🔄 New Scan", type="secondary"):
                reset_callback()
                st.rerun()

        if confirm:
            diff = new_qty - prev_qty
            if diff > 0:
                actual_subtracted = handler.subtract_inventory(itemid, diff)
                st.success(f"Inventory reduced by {actual_subtracted}.")
            elif diff < 0:
                st.info("Declared quantity is less than previous; only updating shelf record, not adding back to inventory.")
            handler.set_shelf_quantity(itemid, locid, new_qty)
            st.success(f"Selling area quantity for '{item['name']}' at {locid} is now {new_qty}.")
            st.rerun()
    elif barcode.strip():
        st.error("❌ Barcode not found in the item table.")

def reset_camera_scan():
    for k in ["barcode_cam", "barcode_input", "declare_qty", "declare_locid"]:
        if k in st.session_state:
            st.session_state.pop(k)

with tab1:
    barcode = ""
    if QR_AVAILABLE:
        st.markdown("<div class='scan-hint'>Aim the barcode at your phone or webcam for instant detection.<br>Hold steady and close to the lens.</div>", unsafe_allow_html=True)
        barcode = qrcode_scanner(key="barcode_cam") or ""
        if barcode:
            st.success(f"Scanned: {barcode}")
        declare_logic(barcode, reset_camera_scan)
    else:
        st.warning("Camera scanning not available. Please use tab 2 or `pip install streamlit-qrcode-scanner`.")

with tab2:
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
    declare_logic(barcode, lambda: reset_camera_scan())
