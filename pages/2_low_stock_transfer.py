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
        # decrement inventory
        self.execute_command(
            """
            UPDATE inventory
            SET    quantity = quantity - %s
            WHERE  itemid=%s AND expirationdate=%s AND cost_per_unit=%s
              AND  quantity >= %s
            """,
            (qty, itemid, expiration, cost, qty),
        )
        # add to shelf
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
        # log entry
        self.execute_command(
            """
            INSERT INTO shelfentries (itemid, expirationdate, quantity, createdby, locid)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (itemid, expiration, qty, by, locid),
        )

# ───── CSS Styling ─────
st.markdown("""
<style>
.card-container {
    background: #fefefe;
    border: 1px solid #e0ecec;
    border-radius: 1rem;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}
.refill-btn button {
    width: 100%;
    padding: 0.6em 0;
    font-size: 1.05rem;
    font-weight: 600;
    border-radius: 0.5rem;
    background: linear-gradient(90deg, #1ABC9C, #3EE2B4);
    color: white;
    border: none;
}
.barcode-box input, .quantity-box input {
    width: 100%;
    padding: 0.4em 0.8em;
    font-size: 1rem;
    border: 1px solid #d5dbe2;
    border-radius: 0.5rem;
    background: #fafafa;
}
.confirmed { color: #008c4a; font-weight: 600; }
.not-matched { color: #e74c3c; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ───── Page ─────
handler = BarcodeShelfHandler()
st.subheader("📤 Auto Transfer: Low Stock Items (Barcode Confirmation)")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ No items at or below threshold 10.")
    st.stop()

for _, row in low_items.iterrows():
    expiry = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry:
        st.error(f"No shelf layer for {row['itemname']}.")
        continue

    # prepare values
    shelfqty = int(row["shelfqty"])
    threshold = int(row["shelfthreshold"])
    needed = max(1, threshold - shelfqty)
    avail = max(1, int(expiry["quantity"]))
    default_qty = min(needed, avail)

    # card container
    with st.container():
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)

        # Info row
        info_cols = st.columns([3,2,2])
        info_cols[0].markdown(f"**🛒 {row['itemname']}**  \nBarcode: `{row['barcode']}`")
        info_cols[1].markdown(f"📦 Shelf: **{shelfqty}** / 🚦 Threshold: **{threshold}**")
        info_cols[2].markdown(f"📍 Location: `{expiry.get('locid','')}`")

        st.markdown("<br>", unsafe_allow_html=True)

        # Controls row: qty, barcode, refill
        ctrl_cols = st.columns([2,3,2])
        with st.container():
            with st.column(0):
                st.markdown("<div class='quantity-box'><b>Qty to refill:</b></div>", unsafe_allow_html=True)
                qty = ctrl_cols[0].number_input(
                    "",
                    min_value=1,
                    max_value=avail,
                    value=default_qty,
                    key=f"qty_{row['itemid']}",
                    label_visibility="collapsed",
                )
            with st.column(1):
                st.markdown("<div class='barcode-box'><b>Confirm Barcode:</b></div>", unsafe_allow_html=True)
                bc = ctrl_cols[1].text_input(
                    "",
                    placeholder="Scan here...",
                    key=f"bc_{row['itemid']}",
                    label_visibility="collapsed",
                )
            with st.column(2):
                disabled = bc.strip() != str(row["barcode"])
                refill_clicked = ctrl_cols[2].button(
                    "🚚 Refill",
                    key=f"refill_{row['itemid']}",
                    disabled=disabled,
                )
        # feedback
        if bc:
            msg = "<div class='confirmed'>✅ Barcode OK</div>" if not disabled else "<div class='not-matched'>❌ Barcode mismatch</div>"
            st.markdown(msg, unsafe_allow_html=True)

        # action
        if refill_clicked:
            user = st.session_state.get("user_email", "AutoTransfer")
            handler.move_layer(
                itemid=row["itemid"],
                expiration=expiry["expirationdate"],
                qty=int(qty),
                cost=expiry["cost_per_unit"],
                locid=expiry.get("locid",""),
                by=user,
            )
            st.success(f"✅ {row['itemname']} refilled {qty} units to {expiry.get('locid','')}!")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
