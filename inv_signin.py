import streamlit as st
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components        # ← iframe for JS timer
from db_handler import DatabaseManager
from auth_utils import hash_pin, verify_pin
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

db = DatabaseManager()
BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")

# ───────────────────────── helpers ────────────────────────────────
def _row_to_permissions(row):
    return {
        "CanAccessHome":        row["canaccesshome"],
        "CanAccessItems":       row["canaccessitems"],
        "CanAccessReceive":     row["canaccessreceive"],
        "CanAccessPO":          row["canaccesspo"],
        "CanAccessReports":     row["canaccessreports"],
        "CanAccessSellingArea": row["canaccesssellingarea"],
        "CanAccessCashier":     row["canaccesscashier"],
        "CanAccessFinance":     row["canaccessfinance"],
        "CanAccessReturns":     row["canaccessreturns"],
        "CanAccessIssues":      row["canaccessissues"],
        "CanAccessShelfMap":    row["canaccessshelfmap"],
    }

# ───────────────────────── auth flow ──────────────────────────────
def authenticate():
    """Google SSO ➜ mandatory PIN ➜ permissions (Baghdad)."""
    # 1) Google sign-in ------------------------------------------------
    if not st.user.is_logged_in:
        logo = "https://img.icons8.com/color/48/000000/google-logo.png"
        st.markdown("<h2 style='text-align:center'>Inventory Management System</h2>",
                    unsafe_allow_html=True)
        _, c, _ = st.columns([1, 3, 1])
        with c:
            st.image(logo, width=32)
            st.button("Sign in with Google", on_click=st.login, use_container_width=True)
        st.stop()

    # identity ---------------------------------------------------------
    user_email = st.user.email
    st.session_state["user_email"] = user_email
    st.session_state["user_name"]  = st.user.name

    # 2) ensure user row exists ---------------------------------------
    user_df = db.fetch_data("SELECT * FROM users WHERE email=%s", (user_email,))
    if user_df.empty:
        st.error("🚫 Your account has not been registered by an administrator.")
        st.stop()

    info      = user_df.iloc[0]
    pin_hash  = info.get("pin_hash")
    fail_cnt  = int(info.get("pin_fail_count", 0) or 0)
    lock_ts   = info.get("pin_locked_until")

    now = datetime.now(BAGHDAD_TZ)

    # parse lock_ts → aware(Baghdad)
    if lock_ts:
        try:
            lock_dt = lock_ts if isinstance(lock_ts, datetime) else datetime.fromisoformat(str(lock_ts))
            if lock_dt.tzinfo is None:
                lock_dt = lock_dt.replace(tzinfo=timezone.utc)
            lock_dt = lock_dt.astimezone(BAGHDAD_TZ)
        except Exception:
            lock_dt = None
    else:
        lock_dt = None

    # ------------- LOCKED branch with iframe countdown ---------------
    if lock_dt and lock_dt > now:
        remaining_ms = int((lock_dt - now).total_seconds() * 1000)
        st_autorefresh(interval=remaining_ms + 500, key="unlock_refresh")   # one rerun

        lock_iso = lock_dt.isoformat()
        components.html(
            f"""
            <div style="font-family:Arial, sans-serif;">
              <h4 style="color:red;">Account locked due to repeated incorrect PIN entries.</h4>
              <p>Please try again in <span id="timer" style="font-weight:bold;font-size:1.2em;"></span>.</p>
            </div>
            <script>
              const end = Date.parse("{lock_iso}");
              function update() {{
                const diff = Math.max(0, end - Date.now());
                const hrs  = String(Math.floor(diff / 3600000)).padStart(2,'0');
                const mins = String(Math.floor((diff % 3600000) / 60000)).padStart(2,'0');
                const secs = String(Math.floor((diff % 60000)  / 1000)).padStart(2,'0');
                document.getElementById("timer").textContent = `${{hrs}}:${{mins}}:${{secs}}`;
              }}
              update(); setInterval(update, 1000);
            </script>
            """,
            height=140,
        )
        st.stop()
    elif lock_dt and lock_dt <= now:
        db.execute_command(
            "UPDATE users SET pin_fail_count = 0, pin_locked_until = NULL WHERE email = %s",
            (user_email,),
        )
        fail_cnt = 0

    # ───────────────── PIN SET-UP (first time) ──────────────────────
    if not pin_hash:
        st.info("🔒 First-time login – please set a 4- to 8-digit PIN.")
        pin1 = st.text_input("Choose a PIN",     type="password", key="set_pin1")
        pin2 = st.text_input("Confirm your PIN", type="password", key="set_pin2")
        if st.button("Save PIN"):
            if not (pin1 and pin2):
                st.warning("Enter the PIN twice."); st.stop()
            if pin1 != pin2:
                st.error("PINs don’t match."); st.stop()
            if not (pin1.isdigit() and 4 <= len(pin1) <= 8):
                st.error("PIN must be 4–8 digits."); st.stop()
            db.execute_command("UPDATE users SET pin_hash = %s WHERE email = %s",
                               (hash_pin(pin1), user_email))
            st.success("✔ PIN saved. Sign in again.")
            st.session_state.clear(); st.rerun()
        st.stop()

    # 3) mandatory PIN every session ---------------------------------
    MAX_FAILS   = 5
    LOCK_MINUTE = 15

    if not st.session_state.get("pin_ok"):
        pin_try = st.text_input("Enter your PIN", type="password")
        if pin_try:
            if verify_pin(pin_try, pin_hash):
                st.session_state["pin_ok"] = True
                db.execute_command("UPDATE users SET pin_fail_count = 0, pin_locked_until = NULL WHERE email=%s",
                                   (user_email,))
                st.rerun()
            else:
                fail_cnt += 1
                if fail_cnt >= MAX_FAILS:
                    lock_until = now + timedelta(minutes=LOCK_MINUTE)
                    db.execute_command("UPDATE users SET pin_fail_count=%s, pin_locked_until=%s WHERE email=%s",
                                       (fail_cnt, lock_until, user_email))
                    st.error("Too many incorrect PIN attempts – account locked.")
                else:
                    db.execute_command("UPDATE users SET pin_fail_count=%s WHERE email=%s",
                                       (fail_cnt, user_email))
                    st.error("❌ Incorrect PIN")
        st.stop()

    # 4) load permissions & role ------------------------------------
    st.session_state["permissions"] = _row_to_permissions(info)
    st.session_state["user_role"]   = info["role"]

# ───────────────────────── misc helper ────────────────────────────
def logout():
    st.logout()
