import streamlit as st
from db_handler import DatabaseManager

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

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
        return qty - left  # actual subtracted

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

st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode)")

handler = DeclareHandler()

st.markdown("""
<style>
.catline {margin:0.08em 0 0.09em 0;font-size:1.1em;}
.cat-class {color:#C61C1C;font-weight:bold;}
.cat-dept {color:#004CBB;font-weight:bold;}
.cat-sect {color:#098A23;font-weight:bold;}
.cat-family {color:#FF8800;font-weight:bold;}
.cat-val {color:#111;}
</style>
""", unsafe_allow_html=True)

barcode = ""
barcode_mode = st.radio("Choose barcode input method:", ["Type / Scan in input box", "Scan via phone camera"])

if barcode_mode == "Type / Scan in input box":
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
elif QR_AVAILABLE:
    scanned = qrcode_scanner(key="barcode_cam", label="Scan barcode using phone camera")
    barcode = scanned or ""
    if barcode:
        st.success(f"Scanned: {barcode}")
    else:
        st.info("Open camera, show barcode in view.")

else:
    st.warning("Camera scanning component not installed. Please use the input box, or `pip install streamlit-qrcode-scanner`.")

if not barcode:
    st.info("Please scan or enter the item barcode.")
    st.stop()

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

    if shelf_entries.empty:
        st.warning("No previous quantity declared for this item in the selling area.")
        default_locid = st.text_input("Shelf Location (locid)", key="declare_locid", max_chars=32)
        if not default_locid:
            st.stop()
        prev_qty = 0
        locations = [default_locid]
    else:
        locations = shelf_entries['locid'].tolist()
        prev_qty = int(shelf_entries['qty'].iloc[0]) if len(shelf_entries)==1 else 0

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
            actual_subtracted = handler.subtract_inventory(itemid, diff)
            st.success(f"Inventory reduced by {actual_subtracted}.")
        elif diff < 0:
            st.info("Declared quantity is less than previous; only updating shelf record, not adding back to inventory.")
        handler.set_shelf_quantity(itemid, locid, new_qty)
        st.success(f"Selling area quantity for '{item['name']}' at {locid} is now {new_qty}.")
        st.rerun()
elif barcode.strip():
    st.error("❌ Barcode not found in the item table.")
