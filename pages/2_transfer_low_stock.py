import streamlit as st
import pandas as pd
from selling_area.shelf_handler import ShelfHandler
from selling_area.transfer import BarcodeShelfHandler, layers_for_barcode, all_locids

st.set_page_config(page_title="Low Stock Quick Transfer", layout="wide")
st.title("⚠️ Low Stock Items – Quick Transfer")

# 1. Show Low Stock Items
shelf_handler = ShelfHandler()
barcode_handler = BarcodeShelfHandler()
global_threshold = st.number_input(
    "🔢 Global Low Stock Threshold",
    min_value=1,
    value=10,
    step=1,
    key="quick_xfer_global_thresh"
)
low_stock_df = shelf_handler.get_low_shelf_stock(global_threshold)

if low_stock_df.empty:
    st.success("✅ No items are below the global threshold.")
    st.stop()

loc_opts = all_locids()
user = st.session_state.get("user_email", "Unknown")

st.markdown("### 🛒 Low Stock Items – Quick Action")

for idx, row in low_stock_df.iterrows():
    with st.expander(f"{row['itemname']} (Current: {row['totalquantity']}, Threshold: {row['shelfthreshold']})", expanded=False):
        st.write(f"**Needed for Average:** {row.get('needed_for_average', row['shelfthreshold'])}")
        barcode = row.get("barcode", "")
        itemid = row["itemid"]
        # Get available inventory layers
        layers = layers_for_barcode(barcode) if barcode else []
        inv_qty = sum(l.get("qty", 0) for l in layers)
        st.write(f"**Available in Inventory:** {inv_qty}")
        if not layers:
            st.error("No available inventory for this item.")
            continue

        transfer_qty = st.number_input(
            "Quantity to transfer", min_value=1, max_value=inv_qty, value=min(inv_qty, int(row.get("needed_for_average", row['shelfthreshold']))), key=f"qty_{itemid}"
        )
        dest_loc = st.selectbox("Destination shelf location", loc_opts, key=f"loc_{itemid}")

        # (Optional) show inventory details
        with st.expander("Show Inventory Batches (Layers)", expanded=False):
            st.dataframe(pd.DataFrame(layers), use_container_width=True, hide_index=True)

        if st.button("Transfer Now", key=f"transfer_{itemid}"):
            remaining = transfer_qty
            # (optional) resolve shortages
            remaining = barcode_handler.resolve_shortages(itemid=itemid, qty_need=remaining, user=user)
            for layer in sorted(layers, key=lambda l: l["cost"]):
                if remaining == 0:
                    break
                take = min(remaining, layer["qty"])
                barcode_handler.move_layer(
                    itemid=layer["itemid"],
                    expiration=layer["expirationdate"],
                    qty=take,
                    cost=layer["cost"],
                    locid=dest_loc,
                    by=user,
                )
                remaining -= take
            st.success(f"Transferred {transfer_qty} units of {row['itemname']} to {dest_loc}.")
            st.rerun()

st.info("Transfer inventory to selling area shelf for low-stock items directly from this page. Each item is handled individually for clarity.")
