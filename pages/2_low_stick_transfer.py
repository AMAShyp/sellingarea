import streamlit as st
from db_handler import DatabaseManager
import pandas as pd

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

handler = BarcodeShelfHandler()

def transfer_tab():
    st.subheader("📤 Auto Transfer: 10 Lowest Stock Items (At or Below Threshold 10)")

    all_items = handler.get_all_shelf_items(limit=20)
    show_cols = [c for c in ["itemname", "shelfqty", "shelfthreshold", "barcode"] if c in all_items.columns]
    st.markdown("#### 🗃️ 20 Shelf Items with Lowest Quantity (sorted by quantity)")
    st.dataframe(
        all_items[show_cols],
        use_container_width=True,
        hide_index=True,
    )

    low_items = handler.get_low_stock_items(threshold=10, limit=10)
    st.write("DEBUG: low_items shape", low_items.shape)
    st.markdown("#### 🛑 Low Stock Candidates (at or below threshold 10)")
    st.dataframe(
        low_items[show_cols],
        use_container_width=True,
        hide_index=True,
    )

    if low_items.empty:
        st.success("✅ No items are currently at or below threshold 10. (See above for lowest 20 items.)")
        return

    st.info("🔻 The following items are at or below threshold and ready for transfer:")
    st.dataframe(
        low_items[show_cols],
        use_container_width=True,
        hide_index=True,
    )

    # Transfer editing/confirmation UI here...

transfer_tab()
