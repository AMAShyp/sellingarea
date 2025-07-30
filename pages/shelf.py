import streamlit as st
from selling_area.shelf_handler import ShelfHandler

def shelf_tab():
    st.subheader("📚 Current Shelf Items")

    try:
        shelf_handler = ShelfHandler()
        shelf_df = shelf_handler.get_shelf_items()

        st.write("DEBUG: shelf_df shape:", shelf_df.shape)
        st.write("DEBUG: shelf_df preview:", shelf_df.head())

        if shelf_df.empty:
            st.info("ℹ️ No items currently in the selling area.")
        else:
            st.dataframe(shelf_df, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"An error occurred loading shelf items: {e}")

if __name__ == "__main__":
    shelf_tab()
