import streamlit as st

st.set_page_config(page_title="Inventory Management System – Selling Area", layout="wide")

from selling_area.main_shelf import main_shelf_page

def main():
    # Directly load the Selling Area page
    main_shelf_page()

if __name__ == "__main__":
    main()
