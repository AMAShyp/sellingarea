# streamlit_app_pydeck_declare_fullmap_clickselect_rewrite.py
import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import urllib.parse

from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler

# Optional camera scanner
try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

# ---------- PAGE ----------
st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity — Tap shelf to rewrite location")

# ---------- GEOMETRY ----------
def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def make_rectangle(x, y, w, h, deg):
    cx = x + w / 2.0
    cy = y + h / 2.0
    rad = np.deg2rad(float(deg or 0.0))
    c, s = np.cos(rad), np.sin(rad)
    corners = np.array([[-w/2, -h/2], [w/2, -h/2], [w/2, h/2], [-w/2, h/2]])
    rot = corners @ np.array([[c, -s], [s, c]])
    abs_pts = rot + [cx, cy]
    pts = abs_pts.tolist()
    pts.append(pts[0])  # close polygon
    return pts

def build_deck(shelf_locs, highlight_locs):
    """All shelves; shelves containing this item highlighted in red.
       Tooltip shows label + a 'Select' link that writes ?picked=<locid>."""
    hi = set(map(str, highlight_locs))
    rows = []
    for row in shelf_locs:
        locid = str(row.get("locid"))
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = to_float(row.get("rotation_deg") or 0)
        coords = make_rectangle(x, y, w, h, deg)

        is_hi = locid in hi
        fill = [220, 53, 69, 190] if is_hi else [180, 180, 180, 70]
        line = [216, 0, 12, 255] if is_hi else [120, 120, 120, 255]

        label = str(row.get("label") or locid)
        select_url = "?picked=" + urllib.parse.quote_plus(locid)

        rows.append({
            "polygon": coords,
            "label": label,
            "locid": locid,
            "select_url": select_url,
            "fill_color": fill,
            "line_color": line,
        })

    df = pd.DataFrame(rows)
    layer = pdk.Layer(
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
    vs = pdk.ViewState(longitude=0.5, latitude=0.5, zoom=6, min_zoom=4, max_zoom=20)
    return pdk.Deck(
        layers=[layer],
        initial_view_state=vs,
        map_provider=None,
        tooltip={
            "html": "<b>{label}</b><br/><a href='{select_url}' style='color:#0b60ff;text-decoration:none;font-weight:600'>Select</a>",
            "style": {"backgroundColor": "white", "color": "#222", "fontSize": "15px", "font-family": "monospace"},
        },
        height=560,
    )

# ---------- DATA ACCESS ----------
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
        return self.fetch_data("""
            SELECT locid, SUM(quantity) AS qty
            FROM shelf
            WHERE itemid=%s
            GROUP BY locid
            HAVING SUM(quantity) > 0
            ORDER BY locid
        """, (int(itemid),))

    def get_inventory_total(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) AS total
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (int(itemid),))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] else 0

    def subtract_inventory(self, itemid, qty):
        batches = self.fetch_data("""
            SELECT expirationdate, cost_per_unit, quantity
            FROM inventory
            WHERE itemid=%s AND quantity > 0
            ORDER BY expirationdate ASC, cost_per_unit ASC
        """, (int(itemid),))
        left = qty
        for _, r in batches.iterrows():
            take = min(left, int(r['quantity']))
            if take > 0:
                self.execute_command("""
                    UPDATE inventory
                    SET quantity = quantity - %s
                    WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity >= %s
                """, (take, int(itemid), r['expirationdate'], r['cost_per_unit'], take))
                left -= take
            if left <= 0:
                break
        return qty - left

    def set_shelf_quantity(self, itemid, locid, qty):
        exists = self.fetch_data(
            "SELECT quantity FROM shelf WHERE itemid=%s AND locid=%s",
            (int(itemid), locid)
        )
        if exists.empty and qty > 0:
            self.execute_command("""
                INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, CURRENT_DATE, %s, 0, %s)
            """, (int(itemid), qty, locid))
        elif not exists.empty:
            if qty > 0:
                self.execute_command("""
                    UPDATE shelf SET quantity=%s WHERE itemid=%s AND locid=%s
                """, (qty, int(itemid), locid))
            else:
                self.execute_command("DELETE FROM shelf WHERE itemid=%s AND locid=%s",
                                     (int(itemid), locid))

    # NEW: rewrite all shelf rows for an item from one loc to another, merging by (exp,cost)
    def rewrite_item_location(self, itemid, from_locid, to_locid):
        if not from_locid or not to_locid or from_locid == to_locid:
            return 0
        rows = self.fetch_data("""
            SELECT itemid, expirationdate, cost_per_unit, quantity
            FROM shelf
            WHERE itemid=%s AND locid=%s AND quantity > 0
        """, (int(itemid), from_locid))
        moved = 0
        for _, r in rows.iterrows():
            qty = int(r["quantity"])
            if qty <= 0:
                continue
            # Upsert into destination locid per (itemid, expirationdate, cost_per_unit, locid)
            self.execute_command("""
                INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
                DO UPDATE SET quantity = shelf.quantity + EXCLUDED.quantity,
                              lastupdated = CURRENT_TIMESTAMP
            """, (int(itemid), r["expirationdate"], qty, r["cost_per_unit"], to_locid))
            moved += qty
        # Remove source rows after merge
        self.execute_command("""
            DELETE FROM shelf
            WHERE itemid=%s AND locid=%s
        """, (int(itemid), from_locid))
        return moved

    def get_all_locids_from_map(self, shelf_locs):
        return sorted({str(r.get("locid")) for r in shelf_locs if r.get("locid")})

    def get_items_at_location(self, locid):
        df = self.fetch_data("""
            SELECT i.itemid, i.itemnameenglish AS name, i.barcode, s.quantity
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = %s AND s.quantity > 0
            ORDER BY i.itemnameenglish
        """, (locid,))
        return df if not df.empty else pd.DataFrame(columns=["itemid", "name", "barcode", "quantity"])

# ---------- STYLE ----------
st.markdown("""
<style>
.catline {margin:0.08em 0 0.09em 0;font-size:1.1em;}
.cat-class {color:#C61C1C;font-weight:bold;}
.cat-dept  {color:#004CBB;font-weight:bold;}
.cat-sect  {color:#098A23;font-weight:bold;}
.cat-family{color:#FF8800;font-weight:bold;}
.cat-val {color:#111;}
.scan-hint {
    font-size: 1.1em; color: #087911; font-weight: 600; background: #eafdff;
    padding: .2em .7em; border-radius: .45em; margin: .4em 0 .6em 0; text-align:center;
}
.small-dim {color:#666;font-size:.92em;margin-top:.25rem;}
</style>
""", unsafe_allow_html=True)

# ---------- STATE ----------
st.session_state.setdefault("latest_declaration", {})
st.session_state.setdefault("latest_itemid", None)
st.session_state.setdefault("last_rewrite_key", "")  # to avoid double execution on rerun

# Read ?picked=<locid> from URL
try:
    params = st.query_params  # Streamlit ≥1.31
except Exception:
    params = st.experimental_get_query_params()
picked_locid = ""
if params and "picked" in params:
    v = params["picked"]
    picked_locid = v[0] if isinstance(v, list) else v

handler = DeclareHandler()
map_handler = ShelfMapHandler()

tab1, tab2 = st.tabs(["📷 Scan via camera", "⌨️ Type/paste barcode"])

# ---------- CORE ----------
def declare_logic(barcode, reset_callback):
    item = None
    itemid = None
    if barcode:
        item = handler.get_item_by_barcode(barcode)
        if item is not None:
            itemid = int(item['itemid'])

    if itemid and st.session_state["latest_itemid"] != itemid:
        st.session_state["latest_declaration"] = {}
        st.session_state["latest_itemid"] = itemid

    if not barcode:
        st.info("Please scan or enter the item barcode.")
        return

    if item is not None:
        st.markdown(f"**Item:** {item['name']}<br>🔖 Barcode: {item['barcode']}", unsafe_allow_html=True)
        st.markdown(
            f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{item['classcat']}</span></div>"
            f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{item['departmentcat']}</span></div>"
            f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{item['sectioncat']}</span></div>"
            f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{item['familycat']}</span></div>",
            unsafe_allow_html=True
        )

        # Pull current shelves for this item
        shelf_entries = handler.get_shelf_entries(itemid)  # locid, qty
        inventory_total = handler.get_inventory_total(itemid)

        # Determine the "current" locid (only if there is exactly one)
        prev_locid = shelf_entries['locid'].iloc[0] if (not shelf_entries.empty and len(shelf_entries) == 1) else ""

        # If user tapped a shelf on the map: rewrite location immediately (merge quantities)
        if picked_locid:
            rewrite_key = f"{itemid}->{prev_locid}->{picked_locid}"
            if prev_locid and picked_locid != prev_locid and st.session_state["last_rewrite_key"] != rewrite_key:
                moved = handler.rewrite_item_location(itemid, prev_locid, picked_locid)
                st.success(f"📍 Rewrote location: {prev_locid} ➜ {picked_locid} (moved {moved} units).")
                st.session_state["last_rewrite_key"] = rewrite_key
                # Refresh shelf_entries after rewrite
                shelf_entries = handler.get_shelf_entries(itemid)

        # Map + highlights
        shelf_locs = map_handler.get_locations()  # full map
        highlight_locs = shelf_entries["locid"].tolist() if not shelf_entries.empty else []
        st.markdown("#### 🗺️ Shelf Map — tap a shelf, then press “Select” in tooltip to rewrite location")
        st.caption("Tip: On mobile, tap once to show the tooltip, then tap **Select**.")
        st.pydeck_chart(build_deck(shelf_locs, highlight_locs), use_container_width=True)

        # Show chosen/current shelf
        chosen_locid = picked_locid or prev_locid
        if chosen_locid:
            st.success(f"Current shelf for this item: **{chosen_locid}**")
            st.markdown(
                "<div class='small-dim'>Choose another shelf from the map to rewrite again, "
                "or <a href='?picked='>clear selection</a>.</div>",
                unsafe_allow_html=True
            )
        else:
            st.info("No shelf chosen yet. Tap a shelf on the map and hit **Select** in the tooltip.")

        # Quantity panel
        prev_qty_display = 0
        if not shelf_entries.empty and chosen_locid:
            row = shelf_entries[shelf_entries["locid"] == chosen_locid]
            if not row.empty:
                prev_qty_display = int(row["qty"].iloc[0])

        st.info(
            f"**Current (previous) quantity at this shelf:** {prev_qty_display}  \n"
            f"**Available in inventory:** {inventory_total}"
        )

        new_qty = st.number_input(
            "Declare current selling area quantity",
            min_value=0,
            value=prev_qty_display,
            step=1,
            key="declare_qty"
        )

        c1, c2 = st.columns([2, 1])
        confirm_clicked = c1.button("✅ Confirm Declaration", key="btn_confirm_declaration")
        if c2.button("🔄 New Scan", key="btn_new_scan"):
            reset_callback()
            try:
                st.query_params.clear()
            except Exception:
                st.experimental_set_query_params(picked="")
            st.session_state["last_rewrite_key"] = ""
            st.rerun()

        if confirm_clicked:
            # Update shelf quantity at the current (possibly rewritten) location
            handler.set_shelf_quantity(itemid, chosen_locid, new_qty)
            st.success(f"Selling area quantity for '{item['name']}' at {chosen_locid} is now {new_qty}.")
            st.session_state["latest_declaration"] = {
                "itemid": itemid, "itemname": item['name'], "barcode": item['barcode'],
                "locid": chosen_locid, "qty": new_qty
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
    for k in ["barcode_cam", "barcode_input", "declare_qty"]:
        st.session_state.pop(k, None)

# ---------- TABS ----------
with tab1:
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
    declare_logic(barcode, reset_camera_scan)

show_latest_declaration_and_items()
