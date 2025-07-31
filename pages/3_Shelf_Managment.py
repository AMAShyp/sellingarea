import streamlit as st
import pandas as pd
from db_handler import DatabaseManager

# --- LOAD filtered locid list from CSV ---
LOCID_CSV_PATH = "assets/locid_list.csv"
locid_df = pd.read_csv(LOCID_CSV_PATH)
FILTERED_LOCIDS = set(str(l).strip() for l in locid_df["locid"].dropna().unique())

class ShelfManagementHandler(DatabaseManager):
    def get_all_shelf_items(self, locids):
        q = """
            SELECT s.locid, i.itemid, i.itemnameenglish AS name, i.barcode, s.quantity
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = ANY(%s)
            ORDER BY s.locid, i.itemnameenglish
        """
        df = self.fetch_data(q, (list(locids),))
        return df if not df.empty else pd.DataFrame(columns=["locid", "itemid", "name", "barcode", "quantity"])

    def update_shelf_quantity(self, itemid, locid, new_qty):
        exists = self.fetch_data(
            "SELECT quantity FROM shelf WHERE itemid=%s AND locid=%s",
            (int(itemid), locid)
        )
        if exists.empty and new_qty > 0:
            self.execute_command("""
                INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, CURRENT_DATE, %s, 0, %s)
            """, (int(itemid), new_qty, locid))
        elif not exists.empty:
            if new_qty > 0:
                self.execute_command("""
                    UPDATE shelf SET quantity=%s WHERE itemid=%s AND locid=%s
                """, (new_qty, int(itemid), locid))
            else:
                self.execute_command("""
                    DELETE FROM shelf WHERE itemid=%s AND locid=%s
                """, (int(itemid), locid))

    def return_to_inventory(self, itemid, qty):
        if qty > 0:
            check = self.fetch_data(
                "SELECT quantity FROM inventory WHERE itemid=%s AND expirationdate=CURRENT_DATE AND cost_per_unit=0 AND storagelocation='BulkReturn'",
                (int(itemid),)
            )
            if not check.empty:
                self.execute_command(
                    "UPDATE inventory SET quantity=quantity+%s WHERE itemid=%s AND expirationdate=CURRENT_DATE AND cost_per_unit=0 AND storagelocation='BulkReturn'",
                    (qty, int(itemid))
                )
            else:
                self.execute_command(
                    "INSERT INTO inventory (itemid, expirationdate, quantity, cost_per_unit, storagelocation) VALUES (%s, CURRENT_DATE, %s, 0, 'BulkReturn')",
                    (int(itemid), qty)
                )

    def get_all_locids(self):
        return sorted(FILTERED_LOCIDS)

st.set_page_config(layout="wide")
st.title("🗄️ Bulk Shelf Items Management")

handler = ShelfManagementHandler()

all_locids = handler.get_all_locids()
all_items_df = handler.get_all_shelf_items(all_locids)

if all_items_df.empty:
    st.info("No items found in the filtered shelves.")
    st.stop()

selected_locid = st.selectbox(
    "Select shelf location for bulk update:",
    options=all_locids,
    index=0
)

items_in_loc = all_items_df[all_items_df["locid"] == selected_locid].copy()
if items_in_loc.empty:
    st.info(f"No items currently on shelf `{selected_locid}`.")
else:
    st.markdown("<b>Set a general quantity for ALL items below (overrides individual boxes):</b>", unsafe_allow_html=True)
    general_qty = st.number_input(
        "General quantity for all",
        min_value=0,
        max_value=99999,
        value=None,
        step=1,
        key=f"bulk_generalqty_{selected_locid}"
    )

    st.markdown("#### Adjust if needed, then click <b>Apply Bulk Update</b>", unsafe_allow_html=True)
    bulk_changes = {}
    for idx, row in items_in_loc.iterrows():
        itemid = row["itemid"]
        name = row["name"]
        barcode = row["barcode"]
        shelf_qty = int(row["quantity"])

        # If general_qty is not None, override default value
        init_value = general_qty if general_qty is not None else shelf_qty

        new_qty = st.number_input(
            f"{name} ({barcode})",
            min_value=0,
            max_value=99999,
            value=init_value,
            step=1,
            key=f"bulkqty_{selected_locid}_{itemid}"
        )
        bulk_changes[itemid] = (shelf_qty, int(new_qty), name, barcode)

    if st.button("💾 Apply Bulk Update", key="apply_bulk_update"):
        changed = False
        for itemid, (old_qty, new_qty, name, barcode) in bulk_changes.items():
            if new_qty != old_qty:
                handler.update_shelf_quantity(itemid, selected_locid, new_qty)
                changed = True
                if new_qty == 0 and old_qty > 0:
                    handler.return_to_inventory(itemid, old_qty)
        if changed:
            st.success("Bulk update applied successfully!")
        else:
            st.info("No changes detected.")
        st.rerun()

    # Table preview
    preview_data = [
        {
            "Item Name": name,
            "Barcode": barcode,
            "Old Shelf Qty": old_qty,
            "New Shelf Qty": new_qty
        }
        for itemid, (old_qty, new_qty, name, barcode) in bulk_changes.items()
    ]
    st.markdown("#### Bulk change preview")
    st.dataframe(pd.DataFrame(preview_data), hide_index=True, use_container_width=True)

st.markdown(
    "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
    "Set general quantity for all, or adjust individuals below.<br>"
    "Set quantity to <b>0</b> to drop out an item from the shelf and return it to inventory.<br>"
    "Click <b>Apply Bulk Update</b> to apply all changes at once."
    "</div>", unsafe_allow_html=True
)
