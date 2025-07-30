import streamlit as st
from db_handler import DatabaseManager

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
        """, (itemid,))
        return df

    def get_inventory_total(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (itemid,))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] is not None else 0

    def subtract_inventory(self, itemid, qty):
        # Subtracts qty from inventory, from the batch with earliest expiration
        batches = self.fetch_data("""
            SELECT expirationdate, cost_per_unit, quantity
            FROM inventory
            WHERE itemid=%s AND quantity > 0
            ORDER BY expirationdate ASC, cost_per_unit ASC
        """, (itemid,))
        left = qty
        for _, row in batches.iterrows():
            take = min(left, int(row['quantity']))
            self.execute_command(
                """
                UPDATE inventory SET quantity=quantity-%s
                WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity>=%s
                """,
                (take, itemid, row['expirationdate'], row['cost_per_unit'], take)
            )
            left -= take
            if left <= 0:
                break
        return qty - left  # actual subtracted

    def set_shelf_quantity(self, itemid, locid, qty):
        # Set (overwrite) the shelf quantity at locid
        exists = self.fetch_data(
            "SELECT quantity FROM shelf WHERE itemid=%s AND locid=%s",
            (itemid, locid)
        )
        if exists.empty:
            self.execute_command("""
                INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, CURRENT_DATE, %s, 0, %s)
            """, (itemid, qty, locid))
        else:
            self.execute_command("""
                UPDATE shelf SET quantity=%s WHERE itemid=%s AND locid=%s
            """, (qty, itemid, locid))

st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode)")

handler = DeclareHandler()

barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
if not barcode:
    st.info("Please scan or enter the item barcode.")
    st.stop()

item = handler.get_item_by_barcode(barcode)
if not item is None:
    st.markdown(f"**Item:** {item['name']}  \n"
                f"🔖 Barcode: `{item['barcode']}`")
    st.markdown(
        f"<div style='font-size:1.04em;'>"
        f"<span style='color:#C61C1C;font-weight:bold;'>Class:</span> <span style='color:#222'>{item['classcat']}</span> &nbsp; "
        f"<span style='color:#004CBB;font-weight:bold;'>Department:</span> <span style='color:#222'>{item['departmentcat']}</span><br>"
        f"<span style='color:#098A23;font-weight:bold;'>Section:</span> <span style='color:#222'>{item['sectioncat']}</span> &nbsp; "
        f"<span style='color:#FF8800;font-weight:bold;'>Family:</span> <span style='color:#222'>{item['familycat']}</span>"
        f"</div>", unsafe_allow_html=True)
    itemid = item['itemid']
    shelf_entries = handler.get_shelf_entries(itemid)
    inventory_total = handler.get_inventory_total(itemid)

    if shelf_entries.empty:
        # No declared quantity yet
        st.warning("No previous quantity declared for this item in the selling area.")
        default_locid = st.text_input("Shelf Location (locid)", key="declare_locid", max_chars=32)
        if not default_locid:
            st.stop()
        prev_qty = 0
        locations = [default_locid]
    else:
        locations = shelf_entries['locid'].tolist()
        prev_qty = int(shelf_entries['qty'].iloc[0]) if len(shelf_entries)==1 else 0

    # If multiple shelf locations, pick one to declare
    if len(locations) > 1:
        locid = st.selectbox("Shelf Location (locid)", locations)
        prev_qty = int(shelf_entries[shelf_entries['locid'] == locid]['qty'].iloc[0])
    else:
        locid = locations[0]

    st.info(f"**Current (previous) quantity in selling area:** {prev_qty}  \n"
            f"**Available in inventory:** {inventory_total}")

    new_qty = st.number_input("Declare current selling area quantity", min_value=0, value=prev_qty, step=1, key="declare_qty")

    confirm = st.button("✅ Confirm Declaration", type="primary")
    if confirm:
        diff = new_qty - prev_qty
        if diff > 0:
            # Subtract from inventory
            actual_subtracted = handler.subtract_inventory(itemid, diff)
            st.success(f"Inventory reduced by {actual_subtracted}.")
        elif diff < 0:
            st.info("Declared quantity is less than previous; only updating shelf record, not adding back to inventory.")
        handler.set_shelf_quantity(itemid, locid, new_qty)
        st.success(f"Selling area quantity for '{item['name']}' at {locid} is now {new_qty}.")
        st.rerun()
elif barcode.strip():
    st.error("❌ Barcode not found in the item table.")
