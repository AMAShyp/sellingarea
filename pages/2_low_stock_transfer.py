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

st.subheader("📤 Auto Transfer: Low Stock Items (Barcode Confirmation Required)")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ No items are currently at or below threshold 10.")
    st.stop()

for idx, row in low_items.iterrows():
    st.markdown("---")
    col0, col1, col2, col3, col4, col5 = st.columns([2,2,2,2,2,2])
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        col0.error("No inventory layer found!")
        continue

    shelfthreshold = int(row["shelfthreshold"])
    shelfqty = int(row["shelfqty"])
    to_transfer = shelfthreshold - shelfqty
    avail_qty = max(1, int(expiry_layer["quantity"]))
    sugg_qty = max(1, min(to_transfer, avail_qty))

    col0.markdown(f"**{row['itemname']}**")
    col0.markdown(f"Barcode: `{row['barcode']}`")
    col1.markdown(f"Shelf Qty: `{shelfqty}` / Threshold: `{shelfthreshold}`")
    col2.markdown(f"Location: `{expiry_layer.get('locid','')}`")

    qty = col3.number_input(
        "Qty",
        min_value=1,
        max_value=avail_qty,
        value=sugg_qty,
        key=f"qty_{row['itemid']}",
    )

    barcode_entry = col4.text_input(
        "Enter/Scan Barcode to Confirm",
        value="",
        key=f"bc_{row['itemid']}",
        placeholder="Scan barcode here...",
    )

    btn_disabled = (barcode_entry.strip() != str(row["barcode"]))

    if col5.button(
        "🚚 Refill",
        key=f"refill_{row['itemid']}",
        disabled=btn_disabled,
        help="Enter the correct barcode to enable this button.",
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
        st.success(f"✅ {row['itemname']} refilled with {qty} units to {expiry_layer.get('locid','')}!")
        st.rerun()

    # Visual feedback
    if barcode_entry and btn_disabled:
        col4.error("❌ Barcode does not match.")
    elif barcode_entry and not btn_disabled:
        col4.success("✅ Barcode confirmed.")
