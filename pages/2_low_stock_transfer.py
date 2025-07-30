import streamlit as st
from db_handler import DatabaseManager

# ────────── Handler ──────────
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

# ────────── UI helpers ──────────
def badge(text, color="blue"):
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:16px;font-size:0.85em;margin-right:6px;">{text}</span>'

def label(text):
    return f'<span style="font-weight:500;color:#555;">{text}</span>'

def show_success_animation(message):
    st.balloons()
    st.success(message)

# ────────── Page ──────────
handler = BarcodeShelfHandler()

st.title("📦 Refill Low Stock Items")
st.caption("Scan each item’s barcode to confirm restocking. Quantity and shelf location are automatically suggested.")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ No items are currently at or below threshold 10.")
    st.stop()

for idx, row in low_items.iterrows():
    with st.container():
        st.markdown("---")
        expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
        if not expiry_layer:
            st.error("No inventory layer found for this item.")
            continue

        shelfthreshold = int(row["shelfthreshold"])
        shelfqty = int(row["shelfqty"])
        to_transfer = shelfthreshold - shelfqty
        avail_qty = max(1, int(expiry_layer["quantity"]))
        sugg_qty = max(1, min(to_transfer, avail_qty))

        # Header card layout
        left, right = st.columns([5, 2])
        with left:
            st.markdown(f"#### {row['itemname']}")
            st.markdown(
                badge(f"Barcode: {row['barcode']}", "#2563eb") +
                badge(f"Location: {expiry_layer.get('locid','')}", "#16a34a"),
                unsafe_allow_html=True,
            )
            st.markdown(
                badge(f"Current: {shelfqty}", "#64748b") +
                badge(f"Threshold: {shelfthreshold}", "#f59e42"),
                unsafe_allow_html=True,
            )
            st.markdown(label(f"Expiration: {expiry_layer['expirationdate']}"), unsafe_allow_html=True)

        with right:
            qty = st.number_input(
                "Quantity to Refill",
                min_value=1,
                max_value=avail_qty,
                value=sugg_qty,
                key=f"qty_{row['itemid']}",
                help="Cannot exceed available inventory.",
            )

        st.markdown("")
        barcode_entry = st.text_input(
            "🔑 Enter or Scan Barcode to Confirm",
            value="",
            key=f"bc_{row['itemid']}",
            placeholder="Scan barcode here…",
            help="Barcode must match to enable the Refill button.",
        )

        btn_disabled = (barcode_entry.strip() != str(row["barcode"]))
        btn_col = st.columns([1, 5, 1])[1]

        if btn_col.button(
            "🚚 Confirm & Refill",
            key=f"refill_{row['itemid']}",
            disabled=btn_disabled,
            use_container_width=True
        ):
            user = st.session_state.get("user_email", "AutoTransfer")
            handler.move_layer(
                itemid=row["itemid"],
                expiration=expiry_layer["expirationdate"],
                qty=int(qty),
                cost=expiry_layer["cost_per_unit"],
                locid=expiry_layer.get("locid", ""),
                by=user,
            )
            show_success_animation(f"{row['itemname']} refilled with {qty} units to {expiry_layer.get('locid','')}.")
            st.rerun()

        # Feedback below the barcode field
        if barcode_entry and btn_disabled:
            st.error("❌ Barcode does not match. Please scan or enter the correct barcode.")
        elif barcode_entry and not btn_disabled:
            st.success("✅ Barcode confirmed. You can now refill this item.")

        # Extra space
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("Refill operations are logged instantly. Return to this page any time to continue.")
