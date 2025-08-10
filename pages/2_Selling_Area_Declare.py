# streamlit_app_pydeck_declare_fullmap.py
import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk

from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler

# Optional: barcode scanning (QR)
try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

# ---------------- CONFIG ----------------
st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode) — Pydeck (Full Map)")

# ---------------- GEOMETRY HELPERS ----------------
def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def make_rectangle(x, y, w, h, deg):
    """Return a closed polygon ([lon, lat] list) in normalized 0..1 space with rotation."""
    cx = x + w / 2
    cy = y + h / 2
    rad = np.deg2rad(deg)
    cos, sin = np.cos(rad), np.sin(rad)
    corners = np.array([
        [-w/2, -h/2],
        [ w/2, -h/2],
        [ w/2,  h/2],
        [-w/2,  h/2]
    ])
    rotated = np.dot(corners, np.array([[cos, -sin],[sin, cos]]))
    abs_pts = rotated + [cx, cy]
    return abs_pts.tolist() + [abs_pts[0].tolist()]  # close polygon

def build_deck(shelf_locs, highlight_locs):
    """Create a pydeck.Deck showing all shelves; highlight those in highlight_locs."""
    highlight_set = set(map(str, highlight_locs))
    rows = []
    for row in shelf_locs:
        locid = str(row.get("locid"))
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        coords = make_rectangle(x, y, w, h, deg)

        is_hi = locid in highlight_set
        fill_rgb = (220, 53, 69) if is_hi else (180, 180, 180)     # red-ish vs grey
        line_rgb = (216, 0, 12) if is_hi else (120, 120, 120)
        fill_a = 190 if is_hi else 70
        line_a = 255

        label = str(row.get("label") or locid)
        rows.append({
            "polygon": coords,
            "label": label,
            "locid": locid,
            "fill_color": list(fill_rgb) + [fill_a],
            "line_color": list(line_rgb) + [line_a],
        })

    df = pd.DataFrame(rows)
    polygon_layer = pdk.Layer(
        "PolygonLayer",
        data=df,
        get_polygon="polygon",
        get_fill_color="fill_color",
        get_line_color="line_color",
        pickable=True,
        auto_highlight=True,
        filled=True,
        stroked=True,
        get_line_width=2,
    )
    view_state = pdk.ViewState(
        longitude=0.5, latitude=0.5, zoom=6, min_zoom=4, max_zoom=20, pitch=0, bearing=0
    )
    return pdk.Deck(
        layers=[polygon_layer],
        initial_view_state=view_state,
        map_provider=None,   # coordinates are normalized (0..1)
        tooltip={
            "html": "<b>{label}</b><br/><span style='font-family:monospace'>{locid}</span>",
            "style": {"backgroundColor": "white", "color": "#222", "fontSize": "16px", "font-family": "monospace"},
        },
        height=550,
    )

# ---------------- DATA ACCESS ----------------
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
            HAVING SUM(quantity) > 0
            ORDER BY locid
        """, (int(itemid),))
        return df if not df.empty else df

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
            if take > 0:
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
            if qty > 0:
                self.execute_command("""
                    INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                    VALUES (%s, CURRENT_DATE, %s, 0, %s)
                """, (int(itemid), qty, locid))
        else:
            if qty > 0:
                self.execute_command("""
                    UPDATE shelf SET quantity=%s WHERE itemid=%s AND locid=%s
                """, (qty, int(itemid), locid))
            else:
                self.execute_command("""
                    DELETE FROM shelf WHERE itemid=%s AND locid=%s
                """, (int(itemid), locid))

    def get_all_locids_from_map(self, shelf_locs):
        """Prefer the map’s source of truth."""
        return sorted({str(r.get("locid")) for r in shelf_locs if r.get("locid") is not None})

    def get_items_at_location(self, locid):
        df = self.fetch_data("""
            SELECT i.itemid, i.itemnameenglish AS name, i.barcode, s.quantity
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = %s AND s.quantity > 0
            ORDER BY i.itemnameenglish
        """, (locid,))
        return df if not df.empty else pd.DataFrame(columns=["itemid", "name", "barcode", "quantity"])

# ---------------- STYLE ----------------
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

# ---------------- STATE ----------------
if "latest_declaration" not in st.session_state:
    st.session_state["latest_declaration"] = {}
if "latest_itemid" not in st.session_state:
    st.session_state["latest_itemid"] = None

handler = DeclareHandler()
map_handler = ShelfMapHandler()

tab1, tab2 = st.tabs(["📷 Scan via camera", "⌨️ Type/paste barcode"])

# ---------------- CORE FLOW ----------------
def declare_logic(barcode, reset_callback):
    item = None
    itemid = None

    if barcode:
        item = handler.get_item_by_barcode(barcode)
        if item is not None:
            itemid = int(item['itemid'])

    # Item changed → reset last message
    if itemid is not None and st.session_state.get("latest_itemid") != itemid:
        st.session_state["latest_declaration"] = {}
        st.session_state["latest_itemid"] = itemid

    if not barcode:
        st.info("Please scan or enter the item barcode.")
        return

    if item is not None:
        # Item header
        st.markdown(f"**Item:** {item['name']}<br>🔖 Barcode: {item['barcode']}", unsafe_allow_html=True)
        st.markdown(
            f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{item['classcat']}</span></div>"
            f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{item['departmentcat']}</span></div>"
            f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{item['sectioncat']}</span></div>"
            f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{item['familycat']}</span></div>",
            unsafe_allow_html=True
        )

        # Data pulls
        shelf_entries = handler.get_shelf_entries(itemid)
        inventory_total = handler.get_inventory_total(itemid)
        shelf_locs = map_handler.get_locations()  # FULL MAP
        all_locids = handler.get_all_locids_from_map(shelf_locs)

        # Build map (highlight shelves that have this item)
        highlight_locs = shelf_entries["locid"].tolist() if not shelf_entries.empty else []
        st.markdown("#### 🗺️ Shelf Map (pydeck) — hover any cell to see label/ID")
        st.pydeck_chart(build_deck(shelf_locs, highlight_locs), use_container_width=True)

        # Previous qty + default locid suggestion
        prev_qty = 0
        prev_locid = ""
        if shelf_entries.empty:
            st.warning("No previous quantity declared for this item in the selling area.")
        else:
            prev_locid = shelf_entries['locid'].iloc[0] if len(shelf_entries) == 1 else ""
            prev_qty = int(shelf_entries['qty'].iloc[0]) if len(shelf_entries) == 1 else 0

        # Location selector (pydeck click isn’t captured by Streamlit)
        if all_locids:
            locid = st.selectbox(
                "Shelf Location (locid)",
                options=all_locids,
                index=all_locids.index(prev_locid) if prev_locid in all_locids else 0,
                key="declare_locid",
                help="Pick location. Hover the map to verify."
            )
        else:
            locid = st.text_input("Shelf Location (locid)", key="declare_locid", max_chars=32)

        st.info(
            f"**Current (previous) quantity in selling area:** {prev_qty}  \n"
            f"**Available in inventory:** {inventory_total}"
        )

        new_qty = st.number_input(
            "Declare current selling area quantity",
            min_value=0, value=prev_qty, step=1, key="declare_qty"
        )

        c1, c2 = st.columns([2, 1])
        confirm_clicked = False
        with c1:
            if st.button("✅ Confirm Declaration", type="primary"):
                confirm_clicked = True
        with c2:
            if st.button("🔄 New Scan", type="secondary"):
                reset_callback()
                st.rerun()

        if confirm_clicked:
            diff = new_qty - prev_qty
            if diff > 0:
                actual_subtracted = handler.subtract_inventory(itemid, diff)
                st.success(f"Inventory reduced by {actual_subtracted}.")
            elif diff < 0:
                st.info("Declared quantity is less than previous; updating shelf record only (no add-back).")

            handler.set_shelf_quantity(itemid, locid, new_qty)
            st.success(f"Selling area quantity for '{item['name']}' at {locid} is now {new_qty}.")

            st.session_state["latest_declaration"] = {
                "itemid": itemid,
                "itemname": item['name'],
                "barcode": item['barcode'],
                "locid": locid,
                "qty": new_qty
            }
            st.rerun()

    elif barcode.strip():
        st.error("❌ Barcode not found in the item table.")

def show_latest_declaration_and_items():
    latest = st.session_state.get("latest_declaration")
    if latest and "itemid" in latest:
        st.markdown(
            f"""<div style='background:#e7f8e9;border:1.5px solid #47bd72;
                  border-radius:0.5em;padding:0.65em 1em 0.6em 1em;
                  margin-top:1em;font-size:1.09em;'>
                <b>Latest Declaration:</b><br>
                <b>Item:</b> <span style='color:#1c4680'>{latest["itemname"]}</span><br>
                <b>Barcode:</b> <span style='color:#222;font-family:monospace'>{latest["barcode"]}</span><br>
                <b>Location:</b> <span style='color:#098A23'>{latest["locid"]}</span><br>
                <b>Quantity:</b> <span style='color:#C61C1C'>{latest["qty"]}</span>
            </div>""",
            unsafe_allow_html=True
        )

        items_at_location = DeclareHandler().get_items_at_location(latest["locid"])
        items_at_location = items_at_location[items_at_location["quantity"] > 0]
        if not items_at_location.empty:
            st.markdown(
                f"<br/><b>All items at location <span style='color:#098A23'>{latest['locid']}</span>:</b>",
                unsafe_allow_html=True
            )
            st.dataframe(
                items_at_location.rename(columns={
                    "itemid": "Item ID",
                    "name": "Item Name",
                    "barcode": "Barcode",
                    "quantity": "Shelf Quantity"
                }),
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("No items currently in this shelf location.")

def reset_camera_scan():
    for k in ["barcode_cam", "barcode_input", "declare_qty", "declare_locid"]:
        if k in st.session_state:
            st.session_state.pop(k)

# ---------------- TABS ----------------
with tab1:
    barcode = ""
    if QR_AVAILABLE:
        st.markdown(
            "<div class='scan-hint'>Aim the barcode at your phone or webcam for instant detection.<br>Hold steady and close to the lens.</div>",
            unsafe_allow_html=True
        )
        barcode = qrcode_scanner(key="barcode_cam") or ""
        if barcode:
            st.success(f"Scanned: {barcode}")
        declare_logic(barcode, reset_camera_scan)
    else:
        st.warning("Camera scanning not available. Please use tab 2 or pip install streamlit-qrcode-scanner.")

with tab2:
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
    declare_logic(barcode, lambda: reset_camera_scan())

show_latest_declaration_and_items()
