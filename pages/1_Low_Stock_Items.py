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
        # Show relevant columns, renaming locid to Location
        columns_to_show = [
            "itemname", "locid", "shelfid", "itemid", "expirationdate",
            "quantity", "lastupdated", "notes", "cost_per_unit"
        ]
        display_df = low_stock_df.copy()
        display_df = display_df[columns_to_show]
        display_df = display_df.rename(columns={"locid": "Location"})
        st.dataframe(
            display_df,
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

            # Optional: show location if it’s part of shelf_qty_df
            columns_alerts = [
                "itemname", "Location" if "locid" in alerts_df.columns else None,
                "totalquantity", "shelfthreshold", "shelfaverage", "needed_for_average"
            ]
            # Remove None if locid not present
            columns_alerts = [c for c in columns_alerts if c]
            if "locid" in alerts_df.columns:
                alerts_df = alerts_df.rename(columns={"locid": "Location"})

            st.warning("⚠️ Items below individual shelf thresholds:")
            st.dataframe(
                alerts_df[columns_alerts],
                use_container_width=True,
                hide_index=True,
            )

            st.info(
                "🔎 **Explanation**:\n"
                "- **Location**: shelf/location ID\n"
                "- **totalquantity**: current shelf quantity\n"
                "- **shelfthreshold**: minimum required\n"
                "- **shelfaverage**: desired shelf quantity\n"
                "- **needed_for_average**: quantity needed to reach average"
            )

except Exception as e:
    st.error(f"An error occurred: {e}")
