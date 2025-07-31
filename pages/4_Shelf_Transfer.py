import streamlit as st
import pandas as pd
from db_handler import DatabaseManager

# --- LOAD filtered locid list from CSV ---
LOCID_CSV_PATH = "assets/locid_list.csv"
locid_df = pd.read_csv(LOCID_CSV_PATH)
FILTERED_LOCIDS = set(str(l).strip() for l in locid_df["locid"].dropna().unique())

class ShelfTransferHandler(DatabaseManager):
    def get_shelf_items(self, locid):
        q = """
            SELECT s.locid, i.itemid, i.itemnameenglish AS name, i.barcode, s.quantity
            FROM shelf s
            JOIN item i ON s.itemid = i.itemid
            WHERE s.locid = %s AND s.quantity > 0
            ORDER BY i.itemnameenglish
        """
        df = self.fetch_data(q, (locid,))
        return df if not df.empty else pd.DataFrame(columns=["locid", "itemid", "name", "barcode", "quantity"])

    def get_all_locids(self):
        return sorted(FILTERED_LOCIDS)

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
                "SELECT quantity FROM inventory WHERE itemid=%s AND expirationdate=CURRENT_DATE AND cost_per_unit=0 AND storagelocation='ShelfReturn'",
                (int(itemid),)
            )
            if not check.empty:
                self.execute_command(
                    "UPDATE inventory SET quantity=quantity+%s WHERE itemid=%s AND expirationdate=CURRENT_DATE AND cost_per_unit=0 AND storagelocation='ShelfReturn'",
                    (qty, int(itemid))
                )
            else:
                self.execute_command(
                    "INSERT INTO inventory (itemid, expirationdate, quantity, cost_per_unit, storagelocation) VALUES (%s, CURRENT_DATE, %s, 0, 'ShelfReturn')",
                    (int(itemid), qty)
                )

st.set_page_config(layout="wide")
st.title("🔄 Shelf Transfers")

handler = ShelfTransferHandler()
all_locids = handler.get_all_locids()

if len(all_locids) < 1:
    st.warning("At least one shelf required.")
    st.stop()

tab1, tab2 = st.tabs(["Shelf ➔ Shelf", "Shelf ➔ Inventory"])

# ==================== TAB 1: SHELF TO SHELF ====================
with tab1:
    colA, colB = st.columns(2)
    with colA:
        source_locid = st.selectbox(
            "Select Source Shelf Location (locid):",
            options=all_locids,
            index=0,
            key="s2s_source"
        )
    with colB:
        target_locid_options = [l for l in all_locids if l != source_locid]
        target_locid = st.selectbox(
            "Select Target Shelf Location (locid):",
            options=target_locid_options,
            index=0,
            key="s2s_target"
        )

    source_items = handler.get_shelf_items(source_locid)
    if source_items.empty:
        st.info(f"No items with positive quantity currently on shelf `{source_locid}`.")
    else:
        st.markdown(
            f"### Transfer from `{source_locid}` to `{target_locid}`"
        )

        transfer_dict = {}
        transfer_table = []
        for idx, row in source_items.iterrows():
            itemid = row["itemid"]
            name = row["name"]
            barcode = row["barcode"]
            shelf_qty = int(row["quantity"])
            col1, col2, col3, col4 = st.columns([2, 2, 1.4, 1.4])
            with col1:
                st.markdown(
                    f"**{name}**<br><span style='color:#bbb;font-size:0.92em'>Barcode:</span> "
                    f"<span style='font-family:monospace;font-size:1em'>{barcode}</span>",
                    unsafe_allow_html=True
                )
            with col2:
                st.markdown(f"<b>Available at source:</b> {shelf_qty}", unsafe_allow_html=True)
            with col3:
                qty_to_transfer = st.number_input(
                    "Transfer Qty",
                    min_value=0,
                    max_value=shelf_qty,
                    value=0,
                    step=1,
                    key=f"s2s_{source_locid}_{target_locid}_{itemid}"
                )
            transfer_dict[itemid] = (name, barcode, shelf_qty, int(qty_to_transfer))
            transfer_table.append({
                "Item Name": name,
                "Barcode": barcode,
                "Available at Source": shelf_qty,
                "Transfer Qty": int(qty_to_transfer)
            })

        preview_df = pd.DataFrame([
            t for t in transfer_table if t["Transfer Qty"] > 0
        ])
        st.markdown("#### Transfer preview")
        if not preview_df.empty:
            st.dataframe(preview_df, hide_index=True, use_container_width=True)
        else:
            st.info("No items selected for transfer yet.")

        if st.button("🚚 Execute Transfer", type="primary", key="s2s_exec"):
            any_transferred = False
            for itemid, (name, barcode, shelf_qty, qty_to_transfer) in transfer_dict.items():
                if qty_to_transfer > 0 and qty_to_transfer <= shelf_qty:
                    # Decrement from source shelf
                    new_source_qty = shelf_qty - qty_to_transfer
                    handler.update_shelf_quantity(itemid, source_locid, new_source_qty)
                    # Increment on target shelf (get current, add)
                    target_item_df = handler.get_shelf_items(target_locid)
                    current_target_qty = 0
                    if not target_item_df.empty:
                        matching = target_item_df[target_item_df["itemid"] == itemid]
                        if not matching.empty:
                            current_target_qty = int(matching["quantity"].iloc[0])
                    new_target_qty = current_target_qty + qty_to_transfer
                    handler.update_shelf_quantity(itemid, target_locid, new_target_qty)
                    any_transferred = True
            if any_transferred:
                st.success("Transfer completed successfully.")
            else:
                st.info("No items selected for transfer or invalid quantities.")
            st.rerun()

    st.markdown(
        "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
        "Only items with a positive shelf quantity are shown.<br>"
        "Set transfer quantity for any items to move them from the source to the target shelf.<br>"
        "If source quantity reaches zero, item will be removed from the source shelf."
        "</div>", unsafe_allow_html=True
    )

# ==================== TAB 2: SHELF TO INVENTORY ====================
with tab2:
    shelf_locid = st.selectbox(
        "Select Shelf Location to move to Inventory:",
        options=all_locids,
        index=0,
        key="s2inv_source"
    )

    shelf_items = handler.get_shelf_items(shelf_locid)
    if shelf_items.empty:
        st.info(f"No items with positive quantity currently on shelf `{shelf_locid}`.")
    else:
        st.markdown(
            f"### Move from Shelf `{shelf_locid}` to Inventory"
        )

        inv_transfer_dict = {}
        inv_transfer_table = []
        for idx, row in shelf_items.iterrows():
            itemid = row["itemid"]
            name = row["name"]
            barcode = row["barcode"]
            shelf_qty = int(row["quantity"])
            col1, col2, col3 = st.columns([2, 2, 2])
            with col1:
                st.markdown(
                    f"**{name}**<br><span style='color:#bbb;font-size:0.92em'>Barcode:</span> "
                    f"<span style='font-family:monospace;font-size:1em'>{barcode}</span>",
                    unsafe_allow_html=True
                )
            with col2:
                st.markdown(f"<b>Available at shelf:</b> {shelf_qty}", unsafe_allow_html=True)
            with col3:
                qty_to_inventory = st.number_input(
                    "Move Qty",
                    min_value=0,
                    max_value=shelf_qty,
                    value=0,
                    step=1,
                    key=f"s2inv_{shelf_locid}_{itemid}"
                )
            inv_transfer_dict[itemid] = (name, barcode, shelf_qty, int(qty_to_inventory))
            inv_transfer_table.append({
                "Item Name": name,
                "Barcode": barcode,
                "Available at Shelf": shelf_qty,
                "Move Qty": int(qty_to_inventory)
            })

        preview_inv_df = pd.DataFrame([
            t for t in inv_transfer_table if t["Move Qty"] > 0
        ])
        st.markdown("#### Transfer preview")
        if not preview_inv_df.empty:
            st.dataframe(preview_inv_df, hide_index=True, use_container_width=True)
        else:
            st.info("No items selected for transfer yet.")

        if st.button("🚚 Move to Inventory", type="primary", key="s2inv_exec"):
            any_moved = False
            for itemid, (name, barcode, shelf_qty, qty_to_inventory) in inv_transfer_dict.items():
                if qty_to_inventory > 0 and qty_to_inventory <= shelf_qty:
                    # Remove from shelf
                    new_shelf_qty = shelf_qty - qty_to_inventory
                    handler.update_shelf_quantity(itemid, shelf_locid, new_shelf_qty)
                    # Add to inventory with FIFO logic
                    handler.return_to_inventory(itemid, qty_to_inventory)
                    any_moved = True
            if any_moved:
                st.success("Shelf items moved to inventory successfully.")
            else:
                st.info("No items selected for transfer or invalid quantities.")
            st.rerun()

    st.markdown(
        "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
        "Only items with a positive shelf quantity are shown.<br>"
        "Set quantity for any items to move them from the shelf to inventory.<br>"
        "If shelf quantity reaches zero, item will be removed from the shelf."
        "</div>", unsafe_allow_html=True
    )
