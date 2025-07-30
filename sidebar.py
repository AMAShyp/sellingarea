# sidebar.py
import streamlit as st
from db_handler import DatabaseManager
from auth_utils import verify_pin, hash_pin

db = DatabaseManager()

# ────────────────────────────────────────────────
# CSS helper – inject once
# ────────────────────────────────────────────────
def _inject_sidebar_css() -> None:
    if st.session_state.get("_sidebar_css_done"):
        return

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] .stButton>button {
            padding:0.45rem 0.75rem;
            width:100%;
            text-align:center;
            border-radius:0.35rem;
            margin-bottom:0.4rem;
            cursor:pointer;
        }
        section[data-testid="stSidebar"] .stButton>button:hover {
            background:rgba(0,0,0,0.05);
        }
        section[data-testid="stSidebar"] .stButton>button[kind="primary"] {
            background:#e9f4ff !important;
            color:#0056b3 !important;
            font-weight:600;
            border-left:4px solid #0d6efd;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_sidebar_css_done"] = True


# ────────────────────────────────────────────────
def _change_pin_ui() -> None:
    with st.sidebar.expander("🔑 Change PIN"):
        old  = st.text_input("Current", type="password", key="old_pin")
        new1 = st.text_input("New (4–8 digits)", type="password", key="new_pin1")
        new2 = st.text_input("Confirm new", type="password", key="new_pin2")

        if st.button("Update PIN", key="btn_update_pin"):
            if not (old and new1 and new2):
                st.warning("Fill all three boxes."); return

            row = db.fetch_data("SELECT pin_hash FROM users WHERE email=%s",
                                (st.session_state["user_email"],))
            stored = row.pin_hash.iloc[0] if not row.empty else None
            if not verify_pin(old, stored):
                st.error("Current PIN is incorrect."); return

            if new1 != new2:
                st.error("New PIN entries don’t match."); return

            if not (new1.isdigit() and 4 <= len(new1) <= 8):
                st.error("PIN must be 4–8 digits."); return

            db.execute_command(
                "UPDATE users SET pin_hash=%s WHERE email=%s",
                (hash_pin(new1), st.session_state["user_email"]),
            )
            st.success("✔ PIN updated.")


# ────────────────────────────────────────────────
def sidebar() -> str:
    """Sidebar navigation; highlights active page."""
    _inject_sidebar_css()

    st.sidebar.image("assets/logo.png", use_container_width=True)

    perms     = st.session_state.get("permissions", {})
    user_role = st.session_state.get("user_role", "User")

    page_perm_map = [
        ("Home",          "CanAccessHome"),
        ("Item",          "CanAccessItems"),
        ("Receive Items", "CanAccessReceive"),
        ("Purchase Order","CanAccessPO"),
        ("Selling Area",  "CanAccessSellingArea"),
        ("Cashier",       "CanAccessCashier"),
        ("Finance",       "CanAccessFinance"),
        ("Returns",       "CanAccessReturns"),
        ("Issues",        "CanAccessIssues"),
        ("Shelf Map",     "CanAccessShelfMap"),
        ("Reports",       "CanAccessReports"),
    ]

    pages = [p for p, flag in page_perm_map if perms.get(flag, False)]
    if user_role == "Admin":
        pages.append("User Management")

    # graceful fallback: no access
    if not pages:
        st.sidebar.warning(
            "You don’t have access to any pages yet. "
            "Please contact an administrator."
        )
        st.sidebar.markdown("<hr>", unsafe_allow_html=True)
        if st.sidebar.button("🚪 Logout", use_container_width=True):
            st.logout()
        return ""

    # current page in session_state
    if "selected_page" not in st.session_state or \
       st.session_state.selected_page not in pages:
        st.session_state.selected_page = pages[0]

    # nav buttons
    for p in pages:
        btn_type = "primary" if p == st.session_state.selected_page else "secondary"
        if st.sidebar.button(
            p,
            key=f"nav_{p}",
            type=btn_type,
            use_container_width=True,
        ):
            if st.session_state.selected_page != p:
                st.session_state.selected_page = p
                st.rerun()   # refresh to repaint highlight immediately

    # bottom controls
    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.logout()

    _change_pin_ui()

    return st.session_state.selected_page
