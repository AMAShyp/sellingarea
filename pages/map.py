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
st.title("📤 Auto Refill: Low Stock Items")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ All items are sufficiently stocked.")
    st.stop()

# Compact card-row CSS for clarity and spacing
st.markdown("""
<style>
.compact-row {
    display: flex;
    align-items: center;
    background: #f9f9fc;
    border-radius: 0.9em;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    border: 1.5px solid #E0ECEC;
    margin-bottom: 1.1em;
    padding: 0.7em 1.1em 0.7em 1.1em;
}
.compact-row .col {
    margin-right: 2em;
}
.compact-row .barcode-box input {
    font-size: 1.1em !important;
    padding: 0.4em 0.8em !important;
    border-radius: 0.7em !important;
    border: 1.5px solid #d5dbe2 !important;
    background: #fbfbfb !important;
}
.compact-row .qty-box input {
    font-size: 1.09em !important;
    font-weight: 600 !important;
    border-radius: 0.7em !important;
    padding: 0.33em 1em !important;
}
.confirmed-barcode { color: #008c4a; font-weight: bold;}
.not-matched-barcode { color: #e74c3c; font-weight: bold;}
.refill-btn button {
    font-size: 1.09em !important;
    font-weight: bold !important;
    border-radius: 0.7em !important;
    padding: 0.37em 1.8em !important;
    background: linear-gradient(92deg, #1ABC9C 70%, #52ffe2 100%) !important;
    color: white !important;
    border: none !important;
    margin-top: 0.2em;
}
</style>
""", unsafe_allow_html=True)

for idx, row in low_items.iterrows():
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        st.error(f"❌ No shelf/loc found for {row['itemname']}.")
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
        st.markdown("<div class='compact-row'>", unsafe_allow_html=True)

        # Info block
        st.markdown(
            f"""<div class='col' style="min-width:280px;">
            <b>{row['itemname']}</b>
            <br><span style='font-size:0.97em;'>Barcode: <span style="font-family:monospace">{row['barcode']}</span></span>
            <br>Qty: <b>{shelfqty}</b> / {shelfthreshold}
            <br>Loc: <span style="font-family:monospace">{expiry_layer.get('locid','')}</span>
            </div>""", unsafe_allow_html=True
        )

        # Quantity box
        qty = st.number_input(
            "Qty", min_value=1, max_value=avail_qty,
            value=suggested_qty, key=qty_key, label_visibility="collapsed"
        )

        # Barcode input
        st.markdown("<div class='barcode-box col' style='min-width:150px;'>", unsafe_allow_html=True)
        barcode_input = st.text_input(
            "Barcode", value="", key=barcode_key, placeholder="Scan barcode...", label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # Status message
        barcode_correct = barcode_input.strip() == row["barcode"]
        msg = ""
        if barcode_input:
            if barcode_correct:
                msg = "<span class='confirmed-barcode'>✅ Barcode matched</span>"
            else:
                msg = "<span class='not-matched-barcode'>❌ Barcode incorrect</span>"
        st.markdown(f"<div class='col' style='min-width:140px;'>{msg}</div>", unsafe_allow_html=True)

        # Button
        btn_col = st.columns([0.5,1,0.5])[1]
        with btn_col:
            refill_clicked = st.button(
                "🚚 Refill",
                key=button_key,
                disabled=not barcode_correct,
                help="Scan or enter the correct barcode to enable.",
                type="primary",
                use_container_width=True
            )
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
        st.markdown("</div>", unsafe_allow_html=True)
