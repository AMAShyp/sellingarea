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

# --- Compact Card Style ---
st.markdown("""
<style>
.compact-card {
    border-radius: 1.1em;
    background: linear-gradient(90deg, #e7fdf8 80%, #e3e8fa 100%);
    border: 1.3px solid #E0ECEC;
    box-shadow: 0 2px 6px rgba(44,62,80,.10);
    margin-bottom: 0.6em;
    padding: 1.1em 1.1em 0.9em 1.1em;
    transition: box-shadow 0.2s;
}
.compact-card:hover {
    box-shadow: 0 6px 22px 0 rgba(44,62,80,.16);
    border-color: #17c7a6;
}
.refill-btn button {
    font-size: 1.13rem !important;
    font-weight: 600 !important;
    border-radius: 0.9em !important;
    background: linear-gradient(92deg, #1ABC9C 60%, #3ee2b4 100%) !important;
    color: white !important;
    padding: 0.47em 1.7em !important;
    margin-top: 0.1em;
}
.barcode-box input {
    font-size: 1.09em !important;
    padding: 0.4em 1em !important;
    border-radius: 0.7em !important;
    border: 1.4px solid #d5dbe2 !important;
    background: #fbfbfb !important;
}
.quantity-box input {
    font-size: 1.12em !important;
    font-weight: 600 !important;
    border-radius: 0.7em !important;
    padding: 0.26em 0.8em !important;
}
.confirmed-barcode {
    color: #008c4a;
    font-weight: bold;
    font-size: 1.08em;
}
.not-matched-barcode {
    color: #e74c3c;
    font-weight: bold;
    font-size: 1.08em;
}
@media (max-width: 1100px) {
    .compact-card { padding: 0.5em 0.4em 0.6em 0.5em;}
}
</style>
""", unsafe_allow_html=True)

st.subheader("📤 Auto Transfer: Low Stock Items (Barcode Confirmation Required)")

handler = BarcodeShelfHandler()
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

    qkey = f"qty_{row['itemid']}"
    bckey = f"bc_{row['itemid']}"
    btnkey = f"refill_{row['itemid']}"

    with st.container():
        st.markdown('<div class="compact-card">', unsafe_allow_html=True)
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        # Item Info
        with col1:
            st.markdown(
                f"""<div style="font-size:1.17em;font-weight:700;color:#236879;line-height:1.3;">
                🛒 {row['itemname']}
                </div>
                <div style="font-size:0.99em;color:#888;margin-top:0.18em;">
                    Barcode: <span style="font-family:monospace;">{row['barcode']}</span>
                </div>
                <div style="font-size:1em; margin-top:0.35em;">
                    📦 <b>Shelf Qty:</b> {shelfqty} <br>
                    🚦 <b>Threshold:</b> {shelfthreshold} <br>
                    🗺️ <b>Location:</b> <span style="font-family:monospace;">{expiry_layer.get('locid','')}</span>
                </div>""",
                unsafe_allow_html=True
            )
        # Quantity input
        with col2:
            st.markdown('<div class="quantity-box"><b>Qty to refill:</b></div>', unsafe_allow_html=True)
            qty = st.number_input(
                "",
                min_value=1,
                max_value=avail_qty,
                value=sugg_qty,
                key=qkey,
                label_visibility="collapsed",
            )
        # Barcode entry
        with col3:
            st.markdown('<div class="barcode-box"><b>Scan/Enter Barcode:</b></div>', unsafe_allow_html=True)
            barcode_entry = st.text_input(
                "",
                value="",
                key=bckey,
                placeholder="Scan barcode here...",
                label_visibility="collapsed",
            )
            barcode_correct = (barcode_entry.strip() == str(row["barcode"]))
            if barcode_entry:
                if barcode_correct:
                    st.markdown('<span class="confirmed-barcode">✅ Barcode confirmed</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="not-matched-barcode">❌ Barcode does not match</span>', unsafe_allow_html=True)
        # Button
        with col4:
            refill_clicked = st.button(
                "🚚 Refill",
                key=btnkey,
                disabled=not barcode_correct,
                help="Scan or enter the correct barcode to enable.",
                type="primary",
                use_container_width=True,
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
                st.success(
                    f"✅ <b>{row['itemname']}</b> refilled with <b>{qty}</b> units to <b>{expiry_layer.get('locid','')}</b>!",
                    icon="🎉",
                )
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
