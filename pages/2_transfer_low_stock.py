import streamlit as st
import pandas as pd
from selling_area.shelf_handler import ShelfHandler
from pages.transfer import BarcodeShelfHandler, layers_for_barcode, all_locids

st.set_page_config(page_title="Low Stock Transfer", layout="wide")

st.title("⚠️ Low Stock Items & Bulk Transfer")

# --- Instantiate handlers ---
shelf_handler = ShelfHandler()
barcode_handler = BarcodeShelfHandler()

# --- 1. Show Low Stock Items ---
st.subheader("🚨 Low Stock in Selling Area")

global_threshold = st.number_input(
    "🔢 Global Low Stock Threshold",
    min_value=1,
    value=10,
    step=1,
    key="xfer_global_thresh"
)

low_stock_df = shelf_handler.get_low_shelf_stock(global_threshold)
if low_stock_df.empty:
    st.success("✅ No items are below the global threshold.")
    st.stop()

st.warning("⚠️ Items below global threshold in selling area:")
st.dataframe(low_stock_df, use_container_width=True, hide_index=True)

# Select items to transfer
st.markdown("### Select items to transfer to shelf")
low_stock_df['Transfer'] = False  # add a column for selection

selected = st.multiselect(
    "Select items by name or barcode",
    low_stock_df["itemname"],
    default=low_stock_df["itemname"].tolist(),
    key="xfer_items_select"
)

transfer_items = low_stock_df[low_stock_df["itemname"].isin(selected)]

if transfer_items.empty:
    st.info("No items selected for transfer.")
    st.stop()

st.markdown("### 📦 Prepare Transfer for Selected Low-Stock Items")

# --- 2. Transfer UI for Each Selected Item ---
loc_opts = all_locids()

# Loop through selected low stock items
transfer_jobs = []
for idx, row in transfer_items.iterrows():
    with st.expander(f"Transfer to shelf: {row['itemname']} (Barcode: {row['barcode']})", expanded=True):
        itemid = row["itemid"]
        barcode = row.get("barcode", "")
        needed_qty = int(row.get("needed_for_average", row["shelfthreshold"]))
        to_transfer = st.number_input(
            f"Quantity to transfer for {row['itemname']} (Below threshold by {needed_qty})",
            min_value=1, max_value=needed_qty*3, value=needed_qty, step=1, key=f"qty_{itemid}"
        )

        # Choose destination shelf
        locid = st.selectbox(f"Shelf location for {row['itemname']}", loc_opts, key=f"loc_{itemid}")

        # List available batches/layers for this item
        if barcode:
            layers = layers_for_barcode(barcode)
            if not layers:
                st.error(f"No inventory batches found for {row['itemname']} (barcode {barcode}).")
            else:
                layer_df = pd.DataFrame(layers)
                st.dataframe(layer_df, use_container_width=True, hide_index=True)
        else:
            st.info("No barcode found for this item.")
            layers = []

        transfer_jobs.append({
            "itemid": itemid,
            "itemname": row['itemname'],
            "barcode": barcode,
            "to_transfer": to_transfer,
            "locid": locid,
            "layers": layers,
        })

# --- 3. Execute Transfers (Batch) ---
if st.button("🚚 Transfer Selected Items"):
    user = st.session_state.get("user_email", "Unknown")
    for job in transfer_jobs:
        if not job["layers"] or job["to_transfer"] < 1 or not job["locid"]:
            st.error(f"Invalid transfer info for {job['itemname']}.")
            continue

        remaining = job["to_transfer"]
        # (Optional) resolve shortages as in your original logic:
        remaining = barcode_handler.resolve_shortages(
            itemid=job["itemid"], qty_need=remaining, user=user
        )

        for layer in sorted(job["layers"], key=lambda l: l["cost"]):
            if remaining == 0:
                break
            take = min(remaining, layer["qty"])
            barcode_handler.move_layer(
                itemid=layer["itemid"],
                expiration=layer["expirationdate"],
                qty=take,
                cost=layer["cost"],
                locid=job["locid"],
                by=user,
            )
            remaining -= take
        st.success(f"Transferred {job['to_transfer']} of {job['itemname']} to {job['locid']}.")

    st.rerun()

st.info("This process lets you identify and restock low-selling-area items directly from inventory batches, using the same layered/expiry-based logic as barcode transfers.")
