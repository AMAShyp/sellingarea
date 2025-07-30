import streamlit as st
from db_handler import DatabaseManager

# ───── Database Handler ─────
class BarcodeShelfHandler(DatabaseManager):
    def get_low_stock_items(self, threshold=10, limit=10):
        return self.fetch_data(
            """
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode, 
                   s.totalquantity AS shelfqty, i.shelfthreshold
            FROM item i
            JOIN (
                SELECT itemid, SUM(quantity) AS totalquantity
                FROM shelf
                GROUP BY itemid
            ) s ON i.itemid = s.itemid
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold, %s)
            ORDER BY s.totalquantity ASC
            LIMIT %s
            """,
            (threshold, limit),
        )

    def get_first_expiry_for_item(self, itemid):
        df = self.fetch_data(
            """
            SELECT expirationdate, quantity, cost_per_unit, locid
            FROM shelf
            WHERE itemid = %s AND quantity > 0
            ORDER BY expirationdate ASC, cost_per_unit ASC
            LIMIT 1
            """,
            (itemid,),
        )
        return df.iloc[0].to_dict() if not df.empty else {}

    def move_layer(self, *, itemid, expiration, qty, cost, locid, by):
        self.execute_command(
            """
            UPDATE inventory
            SET quantity = quantity - %s
            WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity >= %s
            """,
            (qty, itemid, expiration, cost, qty),
        )
        self.execute_command(
            """
            INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
            DO UPDATE SET quantity = shelf.quantity + EXCLUDED.quantity, lastupdated = CURRENT_TIMESTAMP
            """,
            (itemid, expiration, qty, cost, locid),
        )
        self.execute_command(
            """
            INSERT INTO shelfentries (itemid, expirationdate, quantity, createdby, locid)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (itemid, expiration, qty, by, locid),
        )

# ───── Streamlit Page ─────
handler = BarcodeShelfHandler()

st.set_page_config(layout="wide")
st.title("📤 Auto Refill: Low-Stock Items")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ All items are sufficiently stocked.")
    st.stop()

# Inject some clean CSS for cards and layout
st.markdown("""
<style>
.item-card {
    padding: 0.7rem 1rem;
    border-radius: 0.8rem;
    box-shadow: 0 3px 6px rgba(0,0,0,0.05);
    background-color: #ffffff;
    margin-bottom: 0.8rem;
    border: 1px solid #dde3e9;
}
.success-text { color: green; font-weight: bold; }
.error-text { color: red; font-weight: bold; }
.refill-btn button {
    background-color: #16a085 !important;
    color: white !important;
    font-weight: bold;
    border-radius: 0.5rem !important;
    padding: 0.4rem 1.2rem !important;
}
</style>
""", unsafe_allow_html=True)

for idx, row in low_items.iterrows():
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        st.error(f"❌ Inventory data missing for {row['itemname']}.")
        continue

    shelfqty = int(row["shelfqty"])
    shelfthreshold = int(row["shelfthreshold"])
    to_transfer = max(1, shelfthreshold - shelfqty)
    avail_qty = int(expiry_layer["quantity"])
    suggested_qty = min(to_transfer, avail_qty)

    qty_key = f"qty_{row['itemid']}"
    barcode_key = f"barcode_{row['itemid']}"
    button_key = f"refill_{row['itemid']}"

    with st.container():
        cols = st.columns([4, 1.2, 2, 1], gap="medium")

        # Item card details
        cols[0].markdown(f"""
        <div class='item-card'>
            <b>{row['itemname']}</b><br>
            📦 Shelf: {shelfqty}/{shelfthreshold} &nbsp; | &nbsp; 🗺️ Loc: {expiry_layer.get('locid','')}<br>
            🔖 Barcode: <span style='font-family:monospace;'>{row['barcode']}</span>
        </div>
        """, unsafe_allow_html=True)

        # Quantity selection
        qty = cols[1].number_input("Qty", 1, avail_qty, suggested_qty, key=qty_key)

        # Barcode input
        barcode_input = cols[2].text_input("🔍 Barcode", key=barcode_key, placeholder="Scan barcode...")

        barcode_correct = barcode_input.strip() == row["barcode"]
        if barcode_input:
            if barcode_correct:
                cols[2].markdown("<div class='success-text'>✅ Barcode matched!</div>", unsafe_allow_html=True)
            else:
                cols[2].markdown("<div class='error-text'>❌ Barcode incorrect!</div>", unsafe_allow_html=True)

        # Refill button
        refill_clicked = cols[3].button("🚚 Refill", key=button_key, disabled=not barcode_correct)

        if refill_clicked:
            user = st.session_state.get("user_email", "AutoTransfer")
            handler.move_layer(
                itemid=row["itemid"],
                expiration=expiry_layer["expirationdate"],
                qty=int(qty),
                cost=expiry_layer["cost_per_unit"],
                locid=expiry_layer.get("locid", ""),
                by=user,
            )
            st.success(f"✅ {row['itemname']} refilled ({qty} units to {expiry_layer.get('locid','')})!")
            st.rerun()
