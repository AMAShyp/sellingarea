import streamlit as st
from selling_area.shelf_handler import ShelfHandler

st.set_page_config(page_title="Low Stock Items", layout="wide")
st.title("⚠️ Low Stock Items")

try:
    shelf_handler = ShelfHandler()

    st.subheader("🚨 Global Low Stock Alerts")
    global_threshold = st.number_input(
        "🔢 Global Low Stock Threshold",
        min_value=1,
        value=10,
        step=1,
    )

    low_stock_df = shelf_handler.get_low_shelf_stock(global_threshold)
    st.write("DEBUG: low_stock_df shape", low_stock_df.shape)

    if low_stock_df.empty:
        st.success("✅ No items are below the global threshold.")
    else:
        st.warning("⚠️ Items below global threshold in selling area:")
        # Show location column
        show_cols = [col for col in low_stock_df.columns if col in [
            "itemname", "locid", "totalquantity", "shelfthreshold", "shelfaverage"
        ]]
        if not show_cols:
            show_cols = low_stock_df.columns  # fallback to all
        st.dataframe(
            low_stock_df[show_cols],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    st.subheader("🚨 Shelf Threshold-Based Alerts")
    shelf_qty_df = shelf_handler.get_shelf_quantity_by_item()
    st.write("DEBUG: shelf_qty_df shape", shelf_qty_df.shape)
    if shelf_qty_df.empty:
        st.info("No items found in the selling area.")
    else:
        alerts_df = shelf_qty_df[
            (shelf_qty_df["shelfthreshold"].notna())
            & (shelf_qty_df["shelfthreshold"] > 0)
            & (shelf_qty_df["totalquantity"] < shelf_qty_df["shelfthreshold"])
        ].copy()

        if alerts_df.empty:
            st.success("✅ All items meet or exceed their shelf threshold.")
        else:
            alerts_df["needed_for_average"] = alerts_df.apply(
                lambda r: max(
                    0, (r["shelfaverage"] or 0) - r["totalquantity"]
                ),
                axis=1,
            )
            # Show location column
            show_cols = [col for col in alerts_df.columns if col in [
                "itemname", "locid", "totalquantity", "shelfthreshold", "shelfaverage", "needed_for_average"
            ]]
            if not show_cols:
                show_cols = alerts_df.columns  # fallback to all
            st.warning("⚠️ Items below individual shelf thresholds:")
            st.dataframe(
                alerts_df[show_cols],
                use_container_width=True,
                hide_index=True,
            )

            st.info(
                "🔎 **Explanation**:\n"
                "- **totalquantity**: current shelf quantity\n"
                "- **shelfthreshold**: minimum required\n"
                "- **shelfaverage**: desired shelf quantity\n"
                "- **needed_for_average**: quantity needed to reach average\n"
                "- **locid**: shelf/location identifier"
            )

except Exception as e:
    st.error(f"An error occurred: {e}")
