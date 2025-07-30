import streamlit as st
import pandas as pd
from db_handler import DatabaseManager

# ───── Handler ─────
class BarcodeShelfHandler(DatabaseManager):
    def get_all_shelf_items(self, limit=20):
        return self.fetch_data(
            f"""
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode,
                   COALESCE(s.totalquantity, 0) AS shelfqty, i.shelfthreshold
            FROM item i
            LEFT JOIN (
                SELECT itemid, SUM(quantity) AS totalquantity
                FROM shelf
                GROUP BY itemid
            ) s ON i.itemid = s.itemid
            ORDER BY shelfqty ASC
            LIMIT {limit}
            """
        )

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
            SELECT expirationdate, quantity, cost_per_unit
            FROM inventory
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

st.subheader("📤 Auto Transfer: 10 Lowest Stock Items (At or Below Threshold 10)")

# Show the 20 lowest-stock items for reference
all_items = handler.get_all_shelf_items(limit=20)
show_cols = [c for c in ["itemname", "shelfqty", "shelfthreshold", "barcode"] if c in all_items.columns]
st.markdown("#### 🗃️ 20 Shelf Items with Lowest Quantity (sorted by quantity)")
st.dataframe(
    all_items[show_cols],
    use_container_width=True,
    hide_index=True,
)

# Get low stock candidates (at or below threshold)
low_items = handler.get_low_stock_items(threshold=10, limit=10)
st.markdown("#### 🛑 Low Stock Candidates (at or below threshold 10)")
st.dataframe(
    low_items[show_cols],
    use_container_width=True,
    hide_index=True,
)

if low_items.empty:
    st.success("✅ No items are currently at or below threshold 10. (See above for lowest 20 items.)")
    st.stop()

st.info("🔻 The following items are at or below threshold and ready for transfer:")
st.dataframe(
    low_items[show_cols],
    use_container_width=True,
    hide_index=True,
)

# Build editable table for transfer
transfer_rows = []
for idx, row in low_items.iterrows():
    to_transfer = row["shelfthreshold"] - row["shelfqty"]
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        continue  # skip if no inventory layer
    transfer_rows.append(
        {
            "itemid": row["itemid"],
            "itemname": row["itemname"],
            "barcode": row.get("barcode", ""),
            "expirationdate": expiry_layer["expirationdate"],
            "available_qty": expiry_layer["quantity"],
            "cost": expiry_layer["cost_per_unit"],
            "suggested_qty": min(to_transfer, expiry_layer["quantity"]),
        }
    )

st.markdown("### Review and edit transfer quantities before confirming:")
editable = pd.DataFrame(transfer_rows)
if not editable.empty:
    editable["transfer_qty"] = editable["suggested_qty"]
    editable["locid"] = ""  # Let user pick location

    for i in range(len(editable)):
        col1, col2, col3 = st.columns([2, 2, 2])
        col1.markdown(f"**{editable.loc[i, 'itemname']}** (Barcode: {editable.loc[i, 'barcode']})")
        avail_qty = max(1, int(editable.loc[i, "available_qty"]))  # never below 1
        sugg_qty = max(1, int(editable.loc[i, "suggested_qty"]))   # never below 1
        editable.loc[i, "transfer_qty"] = col2.number_input(
            "Qty",
            min_value=1,
            max_value=avail_qty,
            value=min(sugg_qty, avail_qty),
            key=f"qty_{i}",
        )
        editable.loc[i, "locid"] = col3.text_input(
            "To Location",
            value="",
            key=f"loc_{i}",
        )

    if st.button("🚚 Confirm & Transfer All"):
        errors = []
        for idx, row in editable.iterrows():
            if not row["locid"]:
                errors.append(f"{row['itemname']}: Location required.")
            elif row["transfer_qty"] > row["available_qty"]:
                errors.append(f"{row['itemname']}: Not enough in inventory for transfer.")

        if errors:
            for e in errors:
                st.error(e)
            st.stop()

        user = st.session_state.get("user_email", "AutoTransfer")
        for idx, row in editable.iterrows():
            handler.move_layer(
                itemid=row["itemid"],
                expiration=row["expirationdate"],
                qty=int(row["transfer_qty"]),
                cost=row["cost"],
                locid=row["locid"],
                by=user,
            )
        st.success("✅ Transfer completed for all selected items!")
        st.experimental_rerun()
else:
    st.info("No transfer candidates available at this time.")
