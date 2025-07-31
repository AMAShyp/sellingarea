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
        # FIFO: Try to update, else insert.
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
st.title("🗄️ Shelf Items Management")

handler = ShelfManagementHandler()

all_locids = handler.get_all_locids()
all_items_df = handler.get_all_shelf_items(all_locids)

if all_items_df.empty:
    st.info("No items found in the filtered shelves.")
    st.stop()

tab1, tab2 = st.tabs(["Single Item Edit", "Bulk Shelf Change"])

with tab1:
    selected_locid = st.selectbox(
        "Select shelf location (locid) to manage:",
        options=all_locids,
        index=0,
        help="Only locations from the filtered list."
    )

    items_in_loc = all_items_df[all_items_df["locid"] == selected_locid].copy()
    if items_in_loc.empty:
        st.info(f"No items currently on shelf `{selected_locid}`.")
    else:
        st.markdown(f"### Items at shelf: `{selected_locid}`")
        for idx, row in items_in_loc.iterrows():
            itemid = row["itemid"]
            name = row["name"]
            barcode = row["barcode"]
            shelf_qty = int(row["quantity"])

            col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1.2])

            with col1:
                st.markdown(
                    f"**{name}**<br>"
                    f"<span style='color:#bbb;font-size:0.92em'>Barcode:</span> "
                    f"<span style='font-family:monospace;font-size:1em'>{barcode}</span>",
                    unsafe_allow_html=True
                )
            with col2:
                st.markdown(f"<b>Current Shelf Qty:</b> {shelf_qty}", unsafe_allow_html=True)
            with col3:
                new_qty = st.number_input(
                    "Set shelf quantity",
                    min_value=0,
                    max_value=99999,
                    value=shelf_qty,
                    step=1,
                    key=f"declare_{selected_locid}_{itemid}"
                )
            with col4:
                if st.button("✅ Update", key=f"update_{selected_locid}_{itemid}"):
                    handler.update_shelf_quantity(itemid, selected_locid, int(new_qty))
                    if int(new_qty) == 0 and shelf_qty > 0:
                        handler.return_to_inventory(itemid, shelf_qty)
                        st.success(f"'{name}' removed from shelf and {shelf_qty} returned to inventory.")
                    elif int(new_qty) != shelf_qty:
                        st.success(f"'{name}' shelf quantity set to {new_qty}.")
                    st.rerun()

        st.markdown(
            "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
            "Set the quantity to <b>0</b> to remove the item from the shelf and return it to inventory.<br>"
            "Click ✅ Update to apply changes for each item."
            "</div>", unsafe_allow_html=True
        )

with tab2:
    st.markdown("### Bulk Change: Set shelf quantity for all items at a location")
    selected_locid_bulk = st.selectbox(
        "Select shelf location for bulk update:",
        options=all_locids,
        index=0,
        key="bulk_locid_select"
    )
    items_in_loc_bulk = all_items_df[all_items_df["locid"] == selected_locid_bulk].copy()
    if items_in_loc_bulk.empty:
        st.info(f"No items currently on shelf `{selected_locid_bulk}`.")
    else:
        st.markdown(f"#### Set quantities below. Any item set to <b>0</b> will be dropped from shelf and moved to inventory.", unsafe_allow_html=True)
        bulk_changes = {}
        for idx, row in items_in_loc_bulk.iterrows():
            itemid = row["itemid"]
            name = row["name"]
            barcode = row["barcode"]
            shelf_qty = int(row["quantity"])
            new_qty = st.number_input(
                f"{name} ({barcode})",
                min_value=0,
                max_value=99999,
                value=shelf_qty,
                step=1,
                key=f"bulkqty_{selected_locid_bulk}_{itemid}"
            )
            bulk_changes[itemid] = (shelf_qty, int(new_qty), name, barcode)

        if st.button("💾 Apply Bulk Update", key="apply_bulk_update"):
            changed = False
            for itemid, (old_qty, new_qty, name, barcode) in bulk_changes.items():
                if new_qty != old_qty:
                    handler.update_shelf_quantity(itemid, selected_locid_bulk, new_qty)
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
        "Set quantity to <b>0</b> to drop out an item from the shelf and return it to inventory.<br>"
        "Click <b>Apply Bulk Update</b> to apply all changes at once."
        "</div>", unsafe_allow_html=True
    )
