import streamlit as st
from db_handler import DatabaseManager

# ───── Handler ─────
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
            SET    quantity = quantity - %s
            WHERE  itemid=%s AND expirationdate=%s AND cost_per_unit=%s
              AND  quantity >= %s
            """,
            (qty, itemid, expiration, cost, qty),
        )
        self.execute_command(
            """
            INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
            DO UPDATE SET quantity    = shelf.quantity + EXCLUDED.quantity,
                          lastupdated = CURRENT_TIMESTAMP
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

# ───── Page ─────
handler = BarcodeShelfHandler()

st.markdown("""
<style>
.card-container {
    background: linear-gradient(92deg, #f9fafb 80%, #e8fffa 100%);
    border-radius: 1.2rem;
    border: 1.5px solid #E0ECEC;
    box-shadow: 0 2px 8px rgba(44, 62, 80, 0.10);
    padding: 1.5rem 2rem 1.3rem 2rem;
    margin-bottom: 2.1rem;
}
.refill-btn button {
    font-size: 1.18rem !important;
    font-weight: 600 !important;
    padding: 0.5em 2.2em !important;
    border-radius: 0.8em !important;
    background: linear-gradient(92deg, #1ABC9C 60%, #3ee2b4 100%) !important;
    color: white !important;
    border: none !important;
    margin-top: 0.5em;
}
.barcode-box input {
    font-size: 1.14em !important;
    padding: 0.4em 1em !important;
    border-radius: 0.7em !important;
    border: 1.5px solid #d5dbe2 !important;
    background: #fbfbfb !important;
}
.quantity-box input {
    font-size: 1.1em !important;
    font-weight: 600 !important;
    border-radius: 0.6em !important;
    padding: 0.3em 0.8em !important;
}
.confirmed-barcode {
    color: #008c4a;
    font-weight: bold;
}
.not-matched-barcode {
    color: #e74c3c;
    font-weight: bold;
}
@media (max-width: 1000px) {
    .card-container { padding: 1em 0.5em 1em 0.5em;}
}
</style>
""", unsafe_allow_html=True)

st.subheader("📤 Auto Transfer: Low Stock Items (Barcode Confirmation Required)")
st.markdown("<br>", unsafe_allow_html=True)

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ No items are currently at or below threshold 10.")
    st.stop()

for idx, row in low_items.iterrows():
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        st.error(f"No shelf location found for {row['itemname']}.")
        continue

    shelfthreshold = int(row["shelfthreshold"])
    shelfqty = int(row["shelfqty"])
    to_transfer = shelfthreshold - shelfqty
    avail_qty = max(1, int(expiry_layer["quantity"]))
    sugg_qty = max(1, min(to_transfer, avail_qty))

    # Unique keys for widgets in card
    qkey = f"qty_{row['itemid']}"
    bckey = f"bc_{row['itemid']}"
    btnkey = f"refill_{row['itemid']}"

    with st.container():
        st.markdown(f"""
        <div class="card-container">
        <div style="display: flex; flex-wrap: wrap; gap: 1.7rem; align-items: flex-start;">
            <div style="min-width:220px;max-width:350px;">
                <div style="font-size:1.27em;font-weight:700; color:#256179;line-height:1.3;">🛒 {row['itemname']}</div>
                <div style="font-size:1em; color:#888;margin-top:0.2em;">Barcode: <span style="font-family:monospace;font-size:1em;">{row['barcode']}</span></div>
            </div>
            <div style="font-size:1.07em; min-width:160px;">
                <span>📦 <b>Shelf Qty:</b> {shelfqty}</span>
                <br><span>🚦 <b>Threshold:</b> {shelfthreshold}</span>
            </div>
            <div style="font-size:1.09em; min-width:140px;">
                <span>🗺️ <b>Location:</b></span><br>
                <span style="font-family:monospace; font-size:1.06em;">{expiry_layer.get('locid','')}</span>
            </div>
            <div style="min-width:120px;">
                <div class="quantity-box">
                <b>Qty to refill:</b><br>
                </div>
        """, unsafe_allow_html=True)
        qty = st.number_input(
            "",
            min_value=1,
            max_value=avail_qty,
            value=sugg_qty,
            key=qkey,
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("""
            <div style="min-width:180px;">
            <div class="barcode-box">
                <b>Scan/Enter Barcode:</b><br>
        """, unsafe_allow_html=True)
        barcode_entry = st.text_input(
            "",
            value="",
            key=bckey,
            placeholder="Scan barcode here...",
            label_visibility="collapsed",
        )
        st.markdown("</div></div>", unsafe_allow_html=True)

        barcode_correct = (barcode_entry.strip() == str(row["barcode"]))
        status_msg = ""
        if barcode_entry:
            if barcode_correct:
                status_msg = '<span class="confirmed-barcode">✅ Barcode confirmed</span>'
            else:
                status_msg = '<span class="not-matched-barcode">❌ Barcode does not match</span>'
        st.markdown(f'<div style="min-width:140px; margin-top:8px;">{status_msg}</div>', unsafe_allow_html=True)

        # Button
        col_btn = st.columns([1, 2, 1])[1]
        with col_btn:
            refill_clicked = st.button(
                "🚚 Refill & Log",
                key=btnkey,
                disabled=not barcode_correct,
                help="Scan or enter the correct barcode to enable.",
                type="primary",
                use_container_width=True,
                # Classes for style above (for some Streamlit themes)
                # Disabled color handled by Streamlit.
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
                st.success(f"✅ <b>{row['itemname']}</b> refilled with <b>{qty}</b> units to <b>{expiry_layer.get('locid','')}</b>!", icon="🎉")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
