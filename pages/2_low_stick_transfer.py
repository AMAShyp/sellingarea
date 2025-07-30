from datetime import date
from typing import List, Dict, Any
import pandas as pd
import streamlit as st
from db_handler import DatabaseManager

# ───────────────────────── constants ────────────────────────────────
HIDDEN = "·"  # 1-char placeholder for collapsed labels

# ────────────────────── DB helper ────────────────────────────────────
class BarcodeShelfHandler(DatabaseManager):
    # ... existing methods unchanged ...

    def get_low_stock_items(self, threshold=10, limit=10) -> pd.DataFrame:
        """Return up to `limit` items below the given shelf threshold."""
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

    def get_first_expiry_for_item(self, itemid: int) -> Dict[str, Any]:
        """Get first available layer (by earliest expiry) for given item."""
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

# ─────────────── main tab ────────────────────────────────────────────
def transfer_tab():
    st.subheader("📤 Auto Transfer: 10 Lowest Stock Items (Threshold < 10)")

    # 1. Auto-detect 10 lowest-stock items below threshold
    low_items = handler.get_low_stock_items(threshold=10, limit=10)
    st.write("DEBUG: low_items shape", low_items.shape)
    if low_items.empty:
        st.success("✅ No items are currently below threshold 10.")
        return

    # 2. Display table for user info
    st.info("🔻 The following items are below threshold and ready for transfer:")
    st.dataframe(
        low_items[["itemname", "shelfqty", "shelfthreshold", "barcode"]],
        use_container_width=True,
        hide_index=True,
    )

    # 3. Prepare transfer batch, prefill with suggested quantities (to threshold)
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
                "barcode": row["barcode"],
                "expirationdate": expiry_layer["expirationdate"],
                "available_qty": expiry_layer["quantity"],
                "cost": expiry_layer["cost_per_unit"],
                "suggested_qty": min(to_transfer, expiry_layer["quantity"]),
            }
        )

    # 4. Show and edit transfer quantities
    st.markdown("### Review and edit transfer quantities before confirming:")
    editable = pd.DataFrame(transfer_rows)
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

        # Process transfers
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

if __name__ == "__main__":
    transfer_tab()
