import streamlit as st
import pandas as pd
from datetime import date
from selling_area.shelf_handler import ShelfHandler

st.set_page_config(page_title="Near Expiry Items", layout="wide")
st.title("⏰ Near Expiry Shelf Items")

try:
    shelf_handler = ShelfHandler()
    shelf_df = shelf_handler.get_shelf_items()
    st.write("DEBUG: shelf_df shape", shelf_df.shape)
    if shelf_df.empty:
        st.info("No items in the selling area.")
        st.stop()

    today = pd.to_datetime(date.today())
    shelf_df["expirationdate"] = pd.to_datetime(shelf_df["expirationdate"])
    shelf_df["days_left"] = (shelf_df["expirationdate"] - today).dt.days

    # bring shelf-life info
    item_df = shelf_handler.fetch_data("SELECT itemid, shelflife FROM item")
    shelf_df = shelf_df.merge(item_df, on="itemid", how="left")

    subtab_days, subtab_percent = st.tabs(["📅 Days-Based", "📐 Shelf Life %"])

    # SUBTAB A: Days-Based
    with subtab_days:
        st.markdown("#### ⚙️ Customize Alert Thresholds (Days)")

        col_red, col_orange, col_green = st.columns(3)
        red_days = col_red.number_input(
            "🔴 Red (≤ days)", min_value=1, value=7, step=1
        )
        orange_days = col_orange.number_input(
            "🟠 Orange (≤ days)",
            min_value=red_days + 1,
            value=max(30, red_days + 1),
            step=1,
        )
        green_days = col_green.number_input(
            "🟢 Green (≤ days)",
            min_value=orange_days + 1,
            value=max(85, orange_days + 1),
            step=1,
        )

        near_expiry_df = shelf_df[shelf_df["days_left"] <= green_days].copy()
        st.write("DEBUG: near_expiry_df shape", near_expiry_df.shape)
        if near_expiry_df.empty:
            st.success(
                f"✅ No items expiring within {green_days} days."
            )
        else:
            def color_days(val: int) -> str:
                if val <= red_days:
                    return "background-color: red; color: white;"
                if val <= orange_days:
                    return "background-color: orange;"
                if val <= green_days:
                    return "background-color: green; color: white;"
                return ""

            styled = near_expiry_df[
                ["itemname", "quantity", "expirationdate", "days_left"]
            ].style.map(color_days, subset=["days_left"])

            st.warning(
                f"⚠️ Items expiring within {green_days} days:"
            )
            st.write(styled)

            st.info(
                "🔎 **Color-Coding (Days)**\n"
                f"- 🔴 ≤ {red_days} days left\n"
                f"- 🟠 {red_days + 1}-{orange_days} days left\n"
                f"- 🟢 {orange_days + 1}-{green_days} days left"
            )

    # SUBTAB B: Shelf Life Fraction
    with subtab_percent:
        st.markdown(
            "#### ⚙️ Customize Alert Thresholds (Fraction of Shelf Life)"
        )

        col_r, col_o, col_g = st.columns(3)
        red_frac = col_r.number_input(
            "🔴 Red (≤ fraction)",
            min_value=0.0,
            max_value=1.0,
            value=0.20,
            step=0.05,
            format="%.2f",
        )
        orange_frac = col_o.number_input(
            "🟠 Orange (≤ fraction)",
            min_value=red_frac + 0.01,
            max_value=1.0,
            value=max(0.40, red_frac + 0.01),
            step=0.05,
            format="%.2f",
        )
        green_frac = col_g.number_input(
            "🟢 Green (≤ fraction)",
            min_value=orange_frac + 0.01,
            max_value=1.0,
            value=max(0.80, orange_frac + 0.01),
            step=0.05,
            format="%.2f",
        )

        fraction_df = shelf_df[
            (shelf_df["shelflife"].notna()) & (shelf_df["shelflife"] > 0)
        ].copy()
        st.write("DEBUG: fraction_df shape", fraction_df.shape)

        if fraction_df.empty:
            st.info("No items have a positive shelf life defined.")
        else:
            fraction_df["fraction_left"] = (
                fraction_df["days_left"] / fraction_df["shelflife"]
            )
            alerts_frac_df = fraction_df[
                fraction_df["fraction_left"] <= green_frac
            ].copy()
            st.write("DEBUG: alerts_frac_df shape", alerts_frac_df.shape)
            if alerts_frac_df.empty:
                st.success(
                    "✅ No items are below the selected fraction of shelf life."
                )
            else:
                def color_frac(val: float) -> str:
                    if val <= red_frac:
                        return "background-color: red; color: white;"
                    if val <= orange_frac:
                        return "background-color: orange;"
                    if val <= green_frac:
                        return "background-color: green; color: white;"
                    return ""

                styled_f = alerts_frac_df[
                    [
                        "itemname",
                        "quantity",
                        "expirationdate",
                        "days_left",
                        "shelflife",
                        "fraction_left",
                    ]
                ].style.map(color_frac, subset=["fraction_left"])

                st.warning(
                    f"⚠️ Items with fraction of shelf life ≤ {green_frac:.2f}:"
                )
                st.write(styled_f)

                st.info(
                    "🔎 **Color-Coding (Shelf-Life Fraction)**\n"
                    f"- 🔴 ≤ {red_frac:.2f}\n"
                    f"- 🟠 ({red_frac:.2f}, {orange_frac:.2f}]\n"
                    f"- 🟢 ({orange_frac:.2f}, {green_frac:.2f}]"
                )

        # show items missing shelf-life for completeness
        missing = shelf_df[
            (shelf_df["shelflife"].isna()) | (shelf_df["shelflife"] <= 0)
        ]
        if not missing.empty:
            st.markdown("---")
            st.error(
                "The following items have no valid shelf life, "
                "so fraction-based alerts aren't possible:"
            )
            st.dataframe(
                missing[
                    [
                        "itemname",
                        "quantity",
                        "expirationdate",
                        "days_left",
                        "shelflife",
                    ]
                ]
            )
except Exception as e:
    st.error(f"An error occurred: {e}")
