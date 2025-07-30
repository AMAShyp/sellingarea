import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from selling_area.shelf_handler import ShelfHandler

st.set_page_config(page_title="Low Stock Items", layout="wide")
st.title("⚠️ Low Stock Items")

try:
    shelf_handler = ShelfHandler()
    tab1, tab2 = st.tabs(["Table View", "Bar Chart Visualization"])

    with tab1:
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
            st.dataframe(
                low_stock_df,
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

                st.warning("⚠️ Items below individual shelf thresholds:")
                st.dataframe(
                    alerts_df[
                        [
                            "itemname",
                            "totalquantity",
                            "shelfthreshold",
                            "shelfaverage",
                            "needed_for_average",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

                st.info(
                    "🔎 **Explanation**:\n"
                    "- **totalquantity**: current shelf quantity\n"
                    "- **shelfthreshold**: minimum required\n"
                    "- **shelfaverage**: desired shelf quantity\n"
                    "- **needed_for_average**: quantity needed to reach average"
                )

    with tab2:
        st.subheader("📊 Shelf Quantity vs Threshold")

        # Use the same shelf quantity DataFrame as above
        shelf_qty_df = shelf_handler.get_shelf_quantity_by_item()

        if shelf_qty_df.empty:
            st.info("No items found in the selling area for visualization.")
        else:
            # Clean and prepare
            viz_df = shelf_qty_df[
                shelf_qty_df["shelfthreshold"].notna() & shelf_qty_df["shelfaverage"].notna()
            ].copy()
            if viz_df.empty:
                st.info("No items with defined thresholds for visualization.")
            else:
                # Sort by totalquantity vs threshold, highlight below/above
                viz_df["below_threshold"] = viz_df["totalquantity"] < viz_df["shelfthreshold"]
                viz_df = viz_df.sort_values(by="below_threshold", ascending=False)

                # Set up the bar chart
                fig, ax = plt.subplots(figsize=(min(0.35*len(viz_df), 16), 6))

                bars = ax.bar(
                    viz_df["itemname"], 
                    viz_df["totalquantity"],
                    label="On Shelf",
                    alpha=0.7,
                )

                # Plot shelf thresholds as a horizontal line/bar
                ax.plot(
                    viz_df["itemname"],
                    viz_df["shelfthreshold"],
                    color="red",
                    marker="o",
                    linestyle="--",
                    linewidth=2,
                    label="Threshold"
                )

                # Color bars: below threshold = red, above = green
                for idx, bar in enumerate(bars):
                    if viz_df.iloc[idx]["below_threshold"]:
                        bar.set_color("red")
                    else:
                        bar.set_color("green")

                ax.set_ylabel("Quantity")
                ax.set_xlabel("Item")
                ax.set_title("Shelf Quantity vs. Threshold (Red = Below Threshold)")
                ax.legend()
                plt.xticks(rotation=60, ha="right")
                plt.tight_layout()
                st.pyplot(fig)

                st.info(
                    "🔎 **Bar Chart**\n"
                    "- **Red bars**: below threshold\n"
                    "- **Green bars**: at/above threshold\n"
                    "- **Red dashed line**: threshold per item"
                )

except Exception as e:
    st.error(f"An error occurred: {e}")
