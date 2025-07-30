import streamlit as st
from selling_area.shelf_handler import ShelfHandler

def shelf_tab():
    st.subheader("📚 Current Shelf Items")

    shelf_handler = ShelfHandler()
    shelf_df = shelf_handler.get_shelf_items()

    if shelf_df.empty:
        st.info("ℹ️ No items currently in the selling area.")
    else:
        st.dataframe(shelf_df, use_container_width=True, hide_index=True)
