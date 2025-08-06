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
        # --- Only keep items with positive quantity ---
        if not df.empty:
            df = df[df["quantity"] > 0]
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
all_items_df = handler.get_all_shelf_items(all_locids)   # Items with 0 already filtered out

if all_items_df.empty:
    st.info("No items with positive quantity found in the filtered shelves.")
    st.stop()

# MULTI-SELECT dropdown for shelves
selected_locids = st.multiselect(
    "Select shelf location(s) for bulk update:",
    options=all_locids,
    default=all_locids[:1] if all_locids else []
)

if not selected_locids:
    st.warning("Select at least one shelf to bulk update.")
    st.stop()

# Filter items for selected shelves
items_in_locs = all_items_df[all_items_df["locid"].isin(selected_locids)].copy()

if items_in_locs.empty:
    st.info(f"No items with positive quantity currently on the selected shelves.")
else:
    st.markdown("<b>Set a general quantity for ALL items below (overrides individual boxes):</b>", unsafe_allow_html=True)
    general_qty = st.number_input(
        "General quantity for all",
        min_value=0,
        max_value=99999,
        value=None,
        step=1,
        key=f"bulk_generalqty_{'_'.join(selected_locids)}"
    )

    st.markdown("#### Adjust if needed, then click <b>Apply Bulk Update</b>", unsafe_allow_html=True)
    bulk_changes = {}
    # Loop by shelf (locid), then items
    for locid in selected_locids:
        st.markdown(f"<div style='background:#f7f7f7;padding:0.5em 1em 0.4em 1em;border-radius:0.3em;margin-top:1.3em;margin-bottom:0.4em'><b>Shelf: <span style='color:#1575ad'>{locid}</span></b></div>", unsafe_allow_html=True)
        shelf_items = items_in_locs[items_in_locs["locid"] == locid]
        for idx, row in shelf_items.iterrows():
            itemid = row["itemid"]
            name = row["name"]
            barcode = row["barcode"]
            shelf_qty = int(row["quantity"])
            init_value = general_qty if general_qty is not None else shelf_qty

            new_qty = st.number_input(
                f"{name} ({barcode}) [on {locid}]",
                min_value=0,
                max_value=99999,
                value=init_value,
                step=1,
                key=f"bulkqty_{locid}_{itemid}"
            )
            bulk_changes[(itemid, locid)] = (shelf_qty, int(new_qty), name, barcode, locid)

    if st.button("💾 Apply Bulk Update", key="apply_bulk_update"):
        changed = False
        for (itemid, locid), (old_qty, new_qty, name, barcode, locid_) in bulk_changes.items():
            if new_qty != old_qty:
                handler.update_shelf_quantity(itemid, locid, new_qty)
                changed = True
                if new_qty == 0 and old_qty > 0:
                    handler.return_to_inventory(itemid, old_qty)
        if changed:
            st.success("Bulk update applied successfully!")
        else:
            st.info("No changes detected.")
        st.rerun()

    # Table preview: only items that would remain with positive qty or whose qty is being changed
    preview_data = [
        {
            "Shelf": locid,
            "Item Name": name,
            "Barcode": barcode,
            "Old Shelf Qty": old_qty,
            "New Shelf Qty": new_qty
        }
        for (itemid, locid), (old_qty, new_qty, name, barcode, locid_) in bulk_changes.items()
        if old_qty > 0 or new_qty > 0
    ]
    if preview_data:
        st.markdown("#### Bulk change preview")
        st.dataframe(pd.DataFrame(preview_data), hide_index=True, use_container_width=True)
    else:
        st.info("All items would be removed from the shelves.")

st.markdown(
    "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
    "Items with 0 shelf quantity are hidden.<br>"
    "Set general quantity for all, or adjust individuals below.<br>"
    "Set quantity to <b>0</b> to drop out an item from the shelf and return it to inventory.<br>"
    "Click <b>Apply Bulk Update</b> to apply all changes at once."
    "</div>", unsafe_allow_html=True
)
