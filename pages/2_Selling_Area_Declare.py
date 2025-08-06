import streamlit as st
import pandas as pd
from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

# --- DATABASE HANDLER ---
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

    def get_all_locids(self):
        map_handler = ShelfMapHandler()
        locs = map_handler.get_locations()
        all_locids = sorted(str(row["locid"]) for row in locs)
        return all_locids

    def get_items_at_location(self, locid):
        df = self.fetch_data("""
            SELECT i.itemid, i.itemnameenglish AS name, i.barcode, s.quantity
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = %s AND s.quantity > 0
            ORDER BY i.itemnameenglish
        """, (locid,))
        return df if not df.empty else pd.DataFrame(columns=["itemid", "name", "barcode", "quantity"])

# --- SIMPLE GRID SHELF MAP ---
def draw_shelf_map(locs, highlight_locs, on_click=None):
    # locs: list of dict with keys 'locid','x_pct','y_pct',...
    # Arrange shelves by their y,x positions for a 2D grid.
    # We'll build a 2D matrix indexed by (row, col)
    import numpy as np

    # Normalize the shelf coordinates to integers
    xs = [float(l['x_pct']) for l in locs]
    ys = [float(l['y_pct']) for l in locs]
    x_sorted = sorted(set(xs))
    y_sorted = sorted(set(ys))
    col_map = {x:i for i,x in enumerate(x_sorted)}
    row_map = {y:i for i,y in enumerate(y_sorted)}
    grid = [[None for _ in x_sorted] for _ in y_sorted]

    locid_lookup = {}
    for l in locs:
        row = row_map[float(l['y_pct'])]
        col = col_map[float(l['x_pct'])]
        grid[row][col] = l['locid']
        locid_lookup[l['locid']] = l

    st.markdown("##### Shelf Map (click a location below):")
    selected = None
    for r, row in enumerate(grid):
        cols = st.columns(len(row))
        for c, locid in enumerate(row):
            if locid is None:
                cols[c].empty()
                continue
            btn_label = f"**{locid}**" if locid in highlight_locs else str(locid)
            style = f"background-color:#FFDFDF" if locid in highlight_locs else ""
            # Custom colored button
            if style:
                cols[c].markdown(
                    f"<div style='border:1px solid #ccc;border-radius:0.4em;background:#ffeaea;padding:.25em;text-align:center;font-weight:600;color:#b31c1c'>{btn_label}</div>",
                    unsafe_allow_html=True,
                )
            if cols[c].button(btn_label, key=f"shelfbtn_{locid}"):
                selected = locid
                if on_click:
                    on_click(locid)
    return selected

st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode)")

handler = DeclareHandler()
map_handler = ShelfMapHandler()

if "latest_declaration" not in st.session_state:
    st.session_state["latest_declaration"] = {}
if "latest_itemid" not in st.session_state:
    st.session_state["latest_itemid"] = None
if "selected_locid" not in st.session_state:
    st.session_state["selected_locid"] = None

tab1, tab2 = st.tabs(["📷 Scan via camera", "⌨️ Type/paste barcode"])

def declare_logic(barcode, reset_callback):
    item = None
    itemid = None

    if barcode:
        item = handler.get_item_by_barcode(barcode)
        if item is not None:
            itemid = int(item['itemid'])

    if itemid is not None and st.session_state.get("latest_itemid") != itemid:
        st.session_state["latest_declaration"] = {}
        st.session_state["latest_itemid"] = itemid
        st.session_state["selected_locid"] = None

    if not barcode:
        st.info("Please scan or enter the item barcode.")
        return

    if item is not None:
        st.markdown(f"**Item:** {item['name']}<br>🔖 Barcode: `{item['barcode']}`", unsafe_allow_html=True)
        shelf_entries = handler.get_shelf_entries(itemid)
        inventory_total = handler.get_inventory_total(itemid)
        all_locids = handler.get_all_locids()
        shelf_locs = [row for row in map_handler.get_locations()]
        highlight_locs = shelf_entries["locid"].tolist() if not shelf_entries.empty else []

        # Draw the grid, set st.session_state['selected_locid'] on click
        def on_grid_click(locid):
            st.session_state["selected_locid"] = locid
        draw_shelf_map(shelf_locs, highlight_locs, on_click=on_grid_click)

        prev_qty = 0
        prev_locid = ""
        if shelf_entries.empty:
            st.warning("No previous quantity declared for this item in the selling area.")
        else:
            prev_locid = shelf_entries['locid'].iloc[0] if len(shelf_entries)==1 else ""
            prev_qty = int(shelf_entries['qty'].iloc[0]) if len(shelf_entries)==1 else 0

        locid = st.session_state.get("selected_locid") or prev_locid or (all_locids[0] if all_locids else "")
        if locid:
            st.info(f"Selected location: `{locid}`")
        else:
            st.info("Please click a shelf location in the map above.")

        st.info(f"**Current (previous) quantity in selling area:** {prev_qty}  \n"
                f"**Available in inventory:** {inventory_total}")

        new_qty = st.number_input("Declare current selling area quantity", min_value=0, value=prev_qty, step=1, key="declare_qty")

        col1, col2 = st.columns([2,1])
        confirm_clicked = False
        with col1:
            confirm = st.button("✅ Confirm Declaration", type="primary")
            if confirm:
                confirm_clicked = True
        with col2:
            if st.button("🔄 New Scan", type="secondary"):
                reset_callback()
                st.rerun()

        if confirm_clicked and locid:
            diff = new_qty - prev_qty
            if diff > 0:
                actual_subtracted = handler.subtract_inventory(itemid, diff)
                st.success(f"Inventory reduced by {actual_subtracted}.")
            elif diff < 0:
                st.info("Declared quantity is less than previous; only updating shelf record, not adding back to inventory.")
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
            </div>
            """,
            unsafe_allow_html=True
        )
        handler = DeclareHandler()
        items_at_location = handler.get_items_at_location(latest["locid"])
        items_at_location = items_at_location[items_at_location["quantity"] > 0]
        if not items_at_location.empty:
            st.markdown(f"<br/><b>All items at location <span style='color:#098A23'>{latest['locid']}</span>:</b>", unsafe_allow_html=True)
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
    for k in ["barcode_cam", "barcode_input", "declare_qty", "declare_locid", "selected_locid"]:
        if k in st.session_state:
            st.session_state.pop(k)

with tab1:
    barcode = ""
    if QR_AVAILABLE:
        st.markdown("<div style='font-size:1.28em;color:#087911;font-weight:600;background:#eafdff;padding:.14em .7em .13em .7em;border-radius:.45em;margin:.2em 0 .5em 0;text-align:center;'>Aim the barcode at your phone or webcam for instant detection.<br>Hold steady and close to the lens.</div>", unsafe_allow_html=True)
        barcode = qrcode_scanner(key="barcode_cam") or ""
        if barcode:
            st.success(f"Scanned: {barcode}")
        declare_logic(barcode, reset_camera_scan)
    else:
        st.warning("Camera scanning not available. Please use tab 2 or `pip install streamlit-qrcode-scanner`.")

with tab2:
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
    declare_logic(barcode, lambda: reset_camera_scan())

show_latest_declaration_and_items()
