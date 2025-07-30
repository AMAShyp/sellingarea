import streamlit as st

st.set_page_config(page_title="Inventory Management System – Selling Area", layout="wide")

# ── Selling Area module only ────────────────────────────────
from selling_area.main_shelf import main_shelf_page

# Optional: keep authentication if needed
from inv_signin import authenticate

def main() -> None:
    authenticate()  # Remove this if you don't want authentication

    # Directly load the Selling Area page (no sidebar, no routing)
    main_shelf_page()

if __name__ == "__main__":
    main()
