# shelf_map/main_map.py
import streamlit as st
from shelf_map.map import map_tab
from shelf_map.heat_map import heat_map_tab


def main():
    """Shelf map page with map and heatmap tabs."""
    st.title("🗺 Shelf Map")
    tabs = st.tabs(["Map", "Heatmap"])

    with tabs[0]:
        map_tab()

    with tabs[1]:
        heat_map_tab()
