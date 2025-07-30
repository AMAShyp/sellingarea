# ── selling_area/main_shelf.py ───────────────────────────────────────
import streamlit as st

from selling_area.shelf          import shelf_tab
from selling_area.transfer       import transfer_tab          # single-item
from selling_area.bulk_transfer  import bulk_transfer_tab     # NEW multi-item
from selling_area.alerts         import alerts_tab
from selling_area.shelf_manage   import shelf_manage_tab


def main_shelf_page() -> None:
    """
    Top-level page for Selling-Area tasks.
    Tabs: Shelf view · Single Transfer · Bulk Transfer · Alerts · Manage Settings
    """
    tabs = st.tabs(
        ["Shelf", "Single Transfer", "Bulk Transfer", "Alerts", "Manage Settings"]
    )

    with tabs[0]:
        shelf_tab()

    with tabs[1]:
        transfer_tab()          # existing one-by-one transfer

    with tabs[2]:
        bulk_transfer_tab()     # NEW multi-item / CSV transfer

    with tabs[3]:
        alerts_tab()

    with tabs[4]:
        shelf_manage_tab()      # thresholds & averages


if __name__ == "__main__":
    main_shelf_page()
