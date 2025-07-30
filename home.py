# home.py – single-page dashboard with KPI cards & gauge (logo removed)

import base64
from typing import Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db_handler import DatabaseManager


# ───────────────────────────────  UI helpers  ────────────────────────────────
def _inject_css() -> None:
    if st.session_state.get("_home_css_done"):
        return

    st.markdown(
        """
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
              rel="stylesheet">
        <style>
        html,body,[class*="css"],.stApp{
            font-family:'Roboto',sans-serif;
            background:linear-gradient(to bottom right,#f8f9fb,#e3e6f0);
        }
        .kpi-card{
            background:#fff;border-radius:10px;
            box-shadow:0 3px 8px rgba(0,0,0,0.06);
            padding:1rem;display:flex;align-items:center;gap:0.75rem;
        }
        .kpi-icon{font-size:1.8rem;line-height:1}
        .kpi-text{display:flex;flex-direction:column}
        .kpi-value{font-size:1.4rem;font-weight:700;margin:0}
        .kpi-label{font-size:0.85rem;color:#666;margin:0}
        .hero{
            background:linear-gradient(90deg,#5c8df6,#a66ef6);
            color:#fff;border-radius:8px;text-align:center;
            padding:2rem 1rem;margin-bottom:2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_home_css_done"] = True


def _image_uri(data: bytes | None) -> str | None:
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}" if data else None


def _kpi_cards(kpis: list[tuple[str, int | float, str]]) -> None:
    cols = st.columns(len(kpis))
    for col, (label, val, icon) in zip(cols, kpis):
        col.markdown(
            f"""
            <div class="kpi-card">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-text">
                <p class="kpi-value">{val:,}</p>
                <p class="kpi-label">{label}</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ──────────────────────────  Data retrieval + filters  ───────────────────────
@st.cache_data(show_spinner="Loading inventory …")
def _load_inventory() -> pd.DataFrame:
    query = """
        SELECT i.ItemID, i.ItemNameEnglish, i.ClassCat, i.DepartmentCat,
               i.SectionCat, i.FamilyCat, i.SubFamilyCat, i.ItemPicture,
               inv.Quantity, inv.ExpirationDate, inv.StorageLocation,
               i.Threshold, i.AverageRequired
        FROM Inventory inv
        JOIN Item i ON inv.ItemID = i.ItemID
    """
    db = DatabaseManager()
    df = db.fetch_data(query)

    if df.empty:
        return df

    df.columns = df.columns.str.lower()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    df["itempicture"] = df["itempicture"].apply(_image_uri)

    return (
        df.groupby(["itemid", "expirationdate", "storagelocation"], as_index=False)
          .agg({
              "itemnameenglish": "first",
              "classcat": "first",
              "departmentcat": "first",
              "sectioncat": "first",
              "familycat": "first",
              "subfamilycat": "first",
              "threshold": "first",
              "averagerequired": "first",
              "itempicture": "first",
              "quantity": "sum",
          })
    )


def _filter_multiselect(label: str, options: Iterable[str], key: str) -> list[str]:
    opts = sorted({o for o in options if pd.notna(o)})
    return st.sidebar.multiselect(label, opts, key=key) if opts else []


def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("🔎 Filters")
    search   = st.sidebar.text_input("Search Item Name")
    classes  = _filter_multiselect("Class", df["classcat"].unique(), "f_class")
    depts    = _filter_multiselect("Department", df["departmentcat"].unique(), "f_dept")
    sections = _filter_multiselect("Section", df["sectioncat"].unique(), "f_sec")

    f = df.copy()
    if search:
        f = f[f["itemnameenglish"].str.contains(search, case=False, na=False)]
    if classes:
        f = f[f["classcat"].isin(classes)]
    if depts:
        f = f[f["departmentcat"].isin(depts)]
    if sections:
        f = f[f["sectioncat"].isin(sections)]

    return f


# ─────────────────────────────────  Main page  ───────────────────────────────
def home() -> None:
    _inject_css()
    st.title("🏠 Home")

    df = _load_inventory()
    if df.empty:
        st.info("No inventory data available.")
        return

    # ── hero ──────────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='hero'>"
        "<h2>Inventory Portal</h2>"
        "<p>Stay on top of stock levels across your business.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── KPI calculations ──────────────────────────────────────────────────────
    total_items   = len(df)
    total_qty     = int(df["quantity"].sum())
    low_stock_cnt = (df["quantity"] < df["threshold"]).sum()
    classes_num   = df["classcat"].nunique()
    dept_num      = df["departmentcat"].nunique()
    expired_cnt   = (
        pd.to_datetime(df["expirationdate"], errors="coerce") <
        pd.Timestamp.today().normalize()
    ).sum()

    # ── KPI card row ──────────────────────────────────────────────────────────
    _kpi_cards(
        [
            ("Items",       total_items,   "🗃️"),
            ("Total Stock", total_qty,     "📦"),
            ("Low Stock",   low_stock_cnt, "⚠️"),
            ("Classes",     classes_num,   "🏷️"),
            ("Departments", dept_num,      "🏢"),
            ("Expired",     expired_cnt,   "⌛"),
        ]
    )

    # ── Low-stock % gauge ─────────────────────────────────────────────────────
    low_pct = round((low_stock_cnt / total_items) * 100, 1) if total_items else 0
    gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=low_pct,
            number={"suffix": "%"},
            title={"text": "Low Stock Ratio"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#e74c3c"},
                "steps": [
                    {"range": [0, 50],  "color": "#2ecc71"},
                    {"range": [50, 80], "color": "#f1c40f"},
                    {"range": [80, 100],"color": "#e74c3c"},
                ],
            },
        )
    )
    st.plotly_chart(gauge, use_container_width=True)

    # ── Quick-insight charts ─────────────────────────────────────────────────
    tab_bar, tab_pie = st.tabs(["Top Classes", "Departments Share"])

    with tab_bar:
        top_classes = (
            df.groupby("classcat", as_index=False)["quantity"]
              .sum().sort_values("quantity", ascending=False).head(10)
        )
        if not top_classes.empty:
            st.plotly_chart(
                px.bar(top_classes, x="classcat", y="quantity", color="classcat"),
                use_container_width=True,
            )

    with tab_pie:
        dept_pie = (
            df.groupby("departmentcat", as_index=False)["quantity"]
              .sum().sort_values("quantity", ascending=False)
        )
        if not dept_pie.empty:
            st.plotly_chart(
                px.pie(dept_pie, names="departmentcat", values="quantity"),
                use_container_width=True,
            )

    # ── Details & tables ─────────────────────────────────────────────────────
    with st.expander("🔧 Details & Tables", expanded=False):
        show_images = st.sidebar.checkbox("Show Images", value=True, key="show_img")
        filtered = _apply_filters(df)

        # Low-stock table
        low_df = (
            filtered.groupby("itemid", as_index=False)
                    .agg({
                        "itemnameenglish": "first",
                        "quantity": "sum",
                        "threshold": "first",
                        "averagerequired": "first",
                        "itempicture": "first",
                    })
                    .query("quantity < threshold")
        )
        if not low_df.empty:
            low_df["reorderamount"] = low_df["averagerequired"] - low_df["quantity"]
            cols = [
                "itempicture",
                "itemnameenglish",
                "quantity",
                "threshold",
                "reorderamount",
            ]
            if not show_images:
                cols.remove("itempicture")

            st.subheader("⚠️ Low Stock Items")
            st.data_editor(
                low_df[cols],
                column_config=(
                    {"itempicture": st.column_config.ImageColumn("Item Picture")}
                    if show_images
                    else None
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("All stock levels are sufficient.")

        # Full inventory table
        st.subheader("📋 Full Inventory")
        full_cols = [
            "itempicture",
            "itemnameenglish",
            "classcat",
            "departmentcat",
            "sectioncat",
            "familycat",
            "subfamilycat",
            "quantity",
            "threshold",
            "averagerequired",
            "expirationdate",
            "storagelocation",
        ]
        if not show_images:
            full_cols.remove("itempicture")

        st.data_editor(
            filtered[full_cols],
            column_config=(
                {"itempicture": st.column_config.ImageColumn("Item Picture")}
                if show_images
                else None
            ),
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
        )

        if st.download_button(
            "Download CSV",
            data=filtered.to_csv(index=False),
            file_name="inventory_data.csv",
            mime="text/csv",
        ):
            st.toast("✅ Inventory CSV downloaded")


# End of file
