import streamlit as st
import pandas as pd
from selling_area.shelf_handler import ShelfHandler

def shelf_manage_tab():
    """
    Handles the management (viewing/editing) of ShelfThreshold and ShelfAverage for items.
    This is a separate tab from the Alerts tab.
    """

    st.subheader("⚙️ Shelf Management Settings")

    shelf_handler = ShelfHandler()
    all_items = shelf_handler.get_all_items()

    # Identify items with missing threshold/average (<NA>)
    missing_items = all_items[
        all_items["shelfthreshold"].isna() | all_items["shelfaverage"].isna()
    ]
    editable_items = all_items[
        all_items["shelfthreshold"].notna() & all_items["shelfaverage"].notna()
    ]

    # ────────────────────────────────────────────
    # 1) BATCH EDIT FOR MISSING ITEMS
    # ────────────────────────────────────────────
    st.markdown("### ❗ Items Missing Shelf Threshold/Average")
    if missing_items.empty:
        st.success("✅ No items are missing shelf settings.")
    else:
        st.warning("These items do not have threshold or average set:")
        
        # Make a copy so we can fill missing numeric values with 0 to avoid errors
        missing_editable = missing_items.copy()
        missing_editable["shelfthreshold"] = (
            missing_editable["shelfthreshold"].fillna(0).astype(int)
        )
        missing_editable["shelfaverage"] = (
            missing_editable["shelfaverage"].fillna(0).astype(int)
        )

        st.markdown("*Edit the values below and click **Update All Missing Items** to save.*")

        edited_df = st.data_editor(
            missing_editable[["itemid", "itemname", "shelfthreshold", "shelfaverage"]],
            num_rows="dynamic", 
            key="missing_thresholds_editor"
        )

        if st.button("💾 Update All Missing Items"):
            for _, row in edited_df.iterrows():
                itemid = row["itemid"]
                new_threshold = row["shelfthreshold"]
                new_average   = row["shelfaverage"]
                shelf_handler.update_shelf_settings(itemid, new_threshold, new_average)

            st.success(f"✅ Updated shelf settings for {len(edited_df)} items.")
            st.rerun()

    st.markdown("---")

    # ────────────────────────────────────────────
    # 2) SINGLE-ITEM EDIT FOR ALREADY DEFINED THRESHOLDS
    # ────────────────────────────────────────────
    st.markdown("### ✏️ Set or Update Shelf Threshold & Average (Individual Items)")

    if editable_items.empty:
        st.info("No items have threshold/average defined yet. See above to add them.")
        return

    # Let the user pick from those that already have threshold & average
    item_names = editable_items["itemname"].tolist()
    selected_item = st.selectbox("🔎 Search and select an item to edit", item_names)

    selected_row = editable_items[editable_items["itemname"] == selected_item].iloc[0]

    default_threshold = int(selected_row["shelfthreshold"])
    default_average   = int(selected_row["shelfaverage"])

    new_threshold = st.number_input("Shelf Threshold", min_value=0, value=default_threshold)
    new_average   = st.number_input("Shelf Average",   min_value=0, value=default_average)

    if st.button("💾 Update Selected Item"):
        shelf_handler.update_shelf_settings(selected_row["itemid"], new_threshold, new_average)
        st.success(f"✅ Updated shelf settings for **{selected_row['itemname']}**.")
        st.rerun()
