from datetime import date
import pandas as pd
import streamlit as st
from db_handler import DatabaseManager

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
        df = self.fetch_data(
            """
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode, 
                   s.totalquantity AS shelfqty, i.shelfthreshold
            FROM item i
            JOIN (
                SELECT itemid, SUM(quantity) AS totalquantity
                FROM shelf
                GROUP BY itemid
            ) s ON i.itemid = s.itemid
            WHERE s.totalquantity < COALESCE(i.shelfthreshold, %s)
            ORDER BY s.totalquantity ASC
            LIMIT %s
            """,
            (threshold, limit),
        )
        return df

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

handler = BarcodeShelfHandler()

def transfer_tab():
    st.subheader("📤 Auto Transfer: 10 Lowest Stock Items (Threshold < 10)")

    # Show only 20 lowest-stock items (columns must exist!)
    all_items = handler.get_all_shelf_items(limit=20)
    st.markdown("#### 🗃️ 20 Shelf Items with Lowest Quantity (sorted by quantity)")
    show_cols = [c for c in ["itemname", "shelfqty", "shelfthreshold", "barcode"] if c in all_items.columns]
    st.dataframe(
        all_items[show_cols],
        use_container_width=True,
        hide_index=True,
    )

    # Show low stock candidates (may also lack barcode)
    low_items = handler.get_low_stock_items(threshold=10, limit=10)
    st.write("DEBUG: low_items shape", low_items.shape)
    st.markdown("#### 🛑 Low Stock Candidates (below threshold 10)")
    show_low_cols = [c for c in ["itemname", "shelfqty", "shelfthreshold", "barcode"] if c in low_items.columns]
    st.dataframe(
        low_items[show_low_cols],
        use_container_width=True,
        hide_index=True,
    )

    if low_items.empty:
        st.success("✅ No items are currently below threshold 10. (See above for lowest 20 items.)")
        return

    st.info("🔻 The following items are below threshold and ready for transfer:")
    st.dataframe(
        low_items[show_low_cols],
        use_container_width=True,
        hide_index=True,
    )

    # Prepare transfer batch, prefill with suggested quantities (to threshold)
    transfer_rows = []
    for idx, row in low_items.iterrows():
        to_transfer = row["shelfthreshold"] - row["shelfqty"]
        expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
        if not expiry_layer:
            continue
        transfer_rows.append(
            {
                "itemid": row.get("itemid"),
                "itemname": row.get("itemname"),
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
            editable.loc[i, "transfer_qty"] = col2.number_input(
                "Qty",
                min_value=1,
                max_value=int(editable.loc[i, "available_qty"]),
                value=int(editable.loc[i, "suggested_qty"]),
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
                return

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

# Do NOT run the tab in pages/! (Remove main block if using Streamlit's multipage)
# if __name__ == "__main__":
#     transfer_tab()

# In pages/ use only:
transfer_tab()
