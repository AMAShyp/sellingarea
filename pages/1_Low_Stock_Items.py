import streamlit as st
import pandas as pd
from selling_area.shelf_handler import ShelfHandler
import matplotlib.pyplot as plt

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

    # Get per-item shelf quantities and thresholds
    shelf_qty_df = shelf_handler.get_shelf_quantity_by_item()

    st.write("DEBUG: shelf_qty_df shape", shelf_qty_df.shape)

    if shelf_qty_df.empty:
        st.info("No items found in the selling area.")
        st.stop()

    # For chart: Only show items with a defined threshold (>0)
    df_chart = shelf_qty_df[shelf_qty_df["shelfthreshold"].notna() & (shelf_qty_df["shelfthreshold"] > 0)].copy()
    df_chart = df_chart.sort_values("totalquantity")

    # Add an "under_threshold" flag
    df_chart["under_threshold"] = df_chart["totalquantity"] < df_chart["shelfthreshold"]

    st.markdown("### 📊 Shelf Quantity vs. Threshold (All Items)")
    if df_chart.empty:
        st.info("No items have thresholds defined.")
    else:
        fig, ax = plt.subplots(figsize=(min(16, 2 + 0.5*len(df_chart)), 6))
        x = df_chart["itemname"]

        # Bar for current quantity
        bars = ax.bar(x, df_chart["totalquantity"], label="Current Quantity", alpha=0.8)

        # Bar for threshold (drawn as a line)
        ax.plot(x, df_chart["shelfthreshold"], color='red', marker='o', linestyle='-', label='Threshold', linewidth=2)

        # Color bars based on under/over threshold
        for idx, bar in enumerate(bars):
            if df_chart.iloc[idx]["under_threshold"]:
                bar.set_color('crimson')
            else:
                bar.set_color('mediumseagreen')

        # Annotate bars that are under threshold
        for idx, row in df_chart.iterrows():
            if row["under_threshold"]:
                ax.text(idx, row["totalquantity"] + 0.5, "Low!", color='crimson', ha='center', va='bottom', fontweight='bold')

        ax.set_ylabel("Quantity")
        ax.set_xticks(range(len(x)))
        ax.set_xticklabels(x, rotation=45, ha='right')
        ax.set_title("Shelf Items: Quantity vs. Threshold")
        ax.legend()
        plt.tight_layout()

        st.pyplot(fig)

        st.info(
            "Bar color: **Red** = Below threshold, **Green** = Above threshold.\n"
            "Red line = Threshold for each item."
        )

    # Table for all under-threshold items
    low_stock_df = df_chart[df_chart["under_threshold"]].copy()
    st.markdown("---")
    st.markdown("### 🔻 Items Below Threshold")
    if low_stock_df.empty:
        st.success("✅ All items meet or exceed their shelf threshold.")
    else:
        st.dataframe(
            low_stock_df[["itemname", "totalquantity", "shelfthreshold"]],
            use_container_width=True,
            hide_index=True,
        )
        st.warning(f"{len(low_stock_df)} item(s) below their threshold.")

except Exception as e:
    st.error(f"An error occurred: {e}")
