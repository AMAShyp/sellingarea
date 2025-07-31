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
        # If new_qty <= 0 and row doesn't exist, do nothing

    def get_all_locids(self):
        return sorted(FILTERED_LOCIDS)

st.set_page_config(layout="wide")
st.title("🗄️ Shelf Items Management (Direct Declaration)")

handler = ShelfManagementHandler()

all_locids = handler.get_all_locids()
all_items_df = handler.get_all_shelf_items(all_locids)

if all_items_df.empty:
    st.info("No items found in the filtered shelves.")
    st.stop()

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
            st.markdown(f"**{name}**<br><span style='color:#bbb;font-size:0.92em'>Barcode:</span> <span style='font-family:monospace;font-size:1em'>{barcode}</span>", unsafe_allow_html=True)
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
                if int(new_qty) == 0:
                    st.success(f"'{name}' removed from shelf.")
                else:
                    st.success(f"'{name}' shelf quantity set to {new_qty}.")
                st.experimental_rerun()

    st.markdown(
        "<div style='margin-top:2em;color:#bbb;font-size:1em'>"
        "Set the quantity to <b>0</b> to remove the item from the shelf.<br>"
        "Click ✅ Update to apply changes for each item."
        "</div>", unsafe_allow_html=True
    )
