import streamlit as st
st.set_page_config(page_title="Inventory Management System", layout="wide")

# ── Page modules ─────────────────────────────────────────────
import home
from item                       import mainitem
import PO.mainpo                as mainpo
from receive_items.main_receive import main_receive_page
import reports.main_reports      as main_reports
from selling_area.main_shelf     import main_shelf_page
from cashier.main_cashier        import main_cashier_page
from finance.main_finance        import main_finance_page
from returns.main_return         import main_return_page
from issues.main_issue           import issues_page
from shelf_map.main_map import main as shelf_map_page

# helpers
from sidebar    import sidebar
from inv_signin import authenticate

# NEW: unified user management tabs
from admin.user_admin_tabs import show_user_admin


def main() -> None:
    authenticate()

    page        = sidebar()
    perms       = st.session_state.get("permissions", {})

    # routing -------------------------------------------------
    if   page == "Home"           and perms.get("CanAccessHome"):
        home.home()

    elif page == "Item"           and perms.get("CanAccessItems"):
        mainitem.item_page()

    elif page == "Receive Items"  and perms.get("CanAccessReceive"):
        main_receive_page()

    elif page == "Purchase Order" and perms.get("CanAccessPO"):
        mainpo.po_page()

    elif page == "Selling Area"   and perms.get("CanAccessSellingArea"):
        main_shelf_page()

    elif page == "Cashier"        and perms.get("CanAccessCashier"):
        main_cashier_page()

    elif page == "Finance"        and perms.get("CanAccessFinance"):
        main_finance_page()

    elif page == "Returns"        and perms.get("CanAccessReturns"):
        main_return_page()

    elif page == "Issues"         and perms.get("CanAccessIssues"):
        issues_page()

    elif page == "Shelf Map"      and perms.get("CanAccessShelfMap"):
        shelf_map_page()

    elif page == "Reports"        and perms.get("CanAccessReports"):
        main_reports.reports_page()

    elif page == "User Management" and st.session_state.get("user_role") == "Admin":
        show_user_admin()  # ← unified tab with both add + manage

    else:
        st.error("❌ You do not have permission to access this page.")


if __name__ == "__main__":
    main()
