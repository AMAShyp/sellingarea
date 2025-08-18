# streamlit_app_pydeck_declare_fullmap_click_to_select.py
# Debuggable rewrite — surfaces DB user, schema, and table privileges when errors occur.

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk

from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler

# Optional: barcode scanning (QR)
try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

SCHEMA = "sellingarea"  # <-- adjust if your schema name differs

# ---------------- CONFIG ----------------
st.set_page_config(layout="centered")
st.title("🟢 Declare Selling Area Quantity (by Barcode) — Click shelf on map to select")

# ---------------- DEBUG CONTROLS ----------------
DEBUG = st.toggle("Show Debug Info", value=False, help="Toggle on to see detailed DB diagnostics and SQL traces.")

def debug_box(title: str, content: str | None = None):
    if DEBUG:
        with st.expander(f"🔎 {title}", expanded=True):
            if content:
                st.code(content, language="text")

def debug_kv(title: str, **kv):
    if DEBUG:
        with st.expander(f"🔎 {title}", expanded=True):
            for k, v in kv.items():
                st.write(f"**{k}:** `{v}`")

# ---------------- GEOMETRY HELPERS ----------------
def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def make_rectangle(x, y, w, h, deg):
    """Closed polygon ([lon, lat]) in normalized 0..1 space with rotation."""
    cx = x + w / 2.0
    cy = y + h / 2.0
    rad = np.deg2rad(float(deg or 0.0))
    c, s = np.cos(rad), np.sin(rad)
    corners = np.array([[-w/2, -h/2], [w/2, -h/2], [w/2, h/2], [-w/2, h/2]])
    rot = corners @ np.array([[c, -s], [s, c]])
    abs_pts = rot + [cx, cy]
    pts = abs_pts.tolist()
    pts.append(pts[0])  # close
    return pts

def build_deck(shelf_locs, highlight_locs, selected_locid=""):
    """
    - Base PolygonLayer 'shelves' (grey or red for highlight)
    - Optional selected overlay (blue outline) for the clicked shelf
    - Tooltip shows a single-line label
    """
    hi = set(map(str, highlight_locs))
    rows = []
    for row in shelf_locs:
        locid = str(row.get("locid"))
        x, y, w, h = map(to_float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = to_float(row.get("rotation_deg") or 0)
        coords = make_rectangle(x, y, w, h, deg)
        is_hi = locid in hi
        rows.append({
            "polygon": coords,
            "locid": locid,
            "label_text": str(row.get("label") or locid),
            "fill_color": [220, 53, 69, 190] if is_hi else [180, 180, 180, 70],
            "line_color": [216, 0, 12, 255] if is_hi else [120, 120, 120, 255],
        })
    df = pd.DataFrame(rows)

    base_layer = pdk.Layer(
        "PolygonLayer",
        id="shelves",
        data=df,
        get_polygon="polygon",
        get_fill_color="fill_color",
        get_line_color="line_color",
        pickable=True,
        auto_highlight=True,
        filled=True,
        stroked=True,
        get_line_width=2,
    )

    layers = [base_layer]

    # Optional selected overlay (blue outline + semi-transparent fill)
    if selected_locid:
        sel_df = df[df["locid"] == str(selected_locid)]
        if not sel_df.empty:
            sel_layer = pdk.Layer(
                "PolygonLayer",
                id="selected-outline",
                data=sel_df,
                get_polygon="polygon",
                get_fill_color=[30, 144, 255, 40],   # light blue tint
                get_line_color=[16, 98, 234, 255],   # vivid blue outline
                pickable=False,
                filled=True,
                stroked=True,
                get_line_width=3,
            )
            layers.append(sel_layer)

    view_state = pdk.ViewState(longitude=0.5, latitude=0.5, zoom=6, min_zoom=4, max_zoom=20, pitch=0, bearing=0)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_provider=None,  # normalized canvas 0..1
        tooltip={"html": "<b>{label_text}</b>", "style": {"fontSize": "14px", "font-family": "monospace"}},
        height=550,
    )
    return deck

# ---------------- DATA ACCESS + DIAGNOSTICS ----------------
class DeclareHandler(DatabaseManager):
    # Quick DB introspection to power debug panel
    def whoami(self):
        try:
            df = self.fetch_data("SELECT current_user, session_user;")
            cu = df.iloc[0]["current_user"] if not df.empty else None
            su = df.iloc[0]["session_user"] if not df.empty else None
        except Exception:
            cu = su = None

        try:
            sp = self.fetch_data("SHOW search_path;")
            search_path = sp.iloc[0][0] if not sp.empty else None
        except Exception:
            search_path = None

        # Check privileges specifically for sellingarea.shelfentries
        checks = {}
        try:
            q = """
                SELECT
                  has_table_privilege(%s, %s, 'SELECT')  AS can_select,
                  has_table_privilege(%s, %s, 'INSERT')  AS can_insert,
                  has_table_privilege(%s, %s, 'UPDATE')  AS can_update,
                  has_table_privilege(%s, %s, 'DELETE')  AS can_delete
            """
            t = f"{SCHEMA}.shelfentries"
            dfp = self.fetch_data(q, (cu, t, cu, t, cu, t, cu, t))
            if not dfp.empty:
                for col in dfp.columns:
                    checks[col] = bool(dfp.iloc[0][col])
        except Exception:
            pass

        return {"current_user": cu, "session_user": su, "search_path": search_path, "shelfentries_priv": checks}

    def _debug_wrap_fetch(self, label: str, sql: str, params: tuple | None = None):
        try:
            if DEBUG:
                debug_kv(f"SQL (fetch) — {label}", sql=sql, params=params)
            return self.fetch_data(sql, params)
        except Exception as e:
            self._emit_db_error(label, sql, params, e)
            raise

    def _debug_wrap_exec(self, label: str, sql: str, params: tuple | None = None):
        try:
            if DEBUG:
                debug_kv(f"SQL (exec) — {label}", sql=sql, params=params)
            return self.execute_command(sql, params)
        except Exception as e:
            self._emit_db_error(label, sql, params, e)
            raise

    def _emit_db_error(self, label: str, sql: str, params, err: Exception):
        info = self.whoami()
        st.error(f"🚫 **Database error in `{label}`**")
        if DEBUG:
            debug_kv("DB Identity", **info)
            debug_box("Failing SQL", sql)
            debug_kv("Params", params=params)
            debug_box("Exception", repr(err))

        # Friendly suggestion when it's a permission error
        msg = str(err).lower()
        if "permission denied" in msg or "42501" in msg:
            grant = f"""\
-- Run as a superuser/owner. Replace app_user with your DB user:
GRANT USAGE ON SCHEMA {SCHEMA} TO app_user;
GRANT SELECT, INSERT ON TABLE {SCHEMA}.shelfentries TO app_user;"""
            st.warning(
                "Looks like a **permission** problem on "
                f"`{SCHEMA}.shelfentries`. You’ll need to grant privileges to the app user."
            )
            debug_box("Suggested GRANTs", grant)

    # -------------------- business queries --------------------
    def get_item_by_barcode(self, barcode):
        sql = f"""
            SELECT itemid, itemnameenglish AS name, barcode,
                   familycat, sectioncat, departmentcat, classcat
            FROM {SCHEMA}.item
            WHERE barcode = %s
            LIMIT 1
        """
        df = self._debug_wrap_fetch("get_item_by_barcode", sql, (barcode,))
        return df.iloc[0] if not df.empty else None

    def get_inventory_total(self, itemid):
        sql = f"""
            SELECT SUM(quantity) as total
            FROM {SCHEMA}.inventory
            WHERE itemid=%s AND quantity > 0
        """
        df = self._debug_wrap_fetch("get_inventory_total", sql, (int(itemid),))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] is not None else 0

    def get_item_locations(self, itemid):
        # NOTE: this was the failing query in your trace
        sql = f"""
            SELECT DISTINCT locid
            FROM {SCHEMA}.shelfentries
            WHERE itemid=%s AND locid IS NOT NULL AND locid <> ''
            ORDER BY locid
        """
        df = self._debug_wrap_fetch("get_item_locations", sql, (int(itemid),))
        return df["locid"].tolist() if not df.empty else []

    def insert_declaration(self, itemid, locid, qty, who="Unknown"):
        # Append-only: NO expirationdate
        sql = f"""
            INSERT INTO {SCHEMA}.shelfentries
                (itemid, quantity, locid, trx_type, note, reference_id, reference_type, createdby)
            VALUES
                (%s, %s, %s, 'STOCKTAKE', 'declare', NULL, NULL, %s)
        """
        self._debug_wrap_exec("insert_declaration", sql, (int(itemid), int(qty), str(locid), str(who)))

    def get_recent_declarations_at_location(self, locid, limit=200):
        sql = f"""
            SELECT
                se.entryid,
                se.itemid,
                i.itemnameenglish AS name,
                i.barcode,
                se.quantity,
                se.entrydate
            FROM {SCHEMA}.shelfentries se
            JOIN {SCHEMA}.item i ON i.itemid = se.itemid
            WHERE se.locid = %s AND se.note = 'declare'
            ORDER BY se.entrydate DESC, se.entryid DESC
            LIMIT %s
        """
        df = self._debug_wrap_fetch("get_recent_declarations_at_location", sql, (str(locid), int(limit)))
        return df if not df.empty else pd.DataFrame(columns=["entryid", "itemid", "name", "barcode", "quantity", "entrydate"])

# ---------------- STYLE ----------------
st.markdown("""
<style>
.catline {margin:0.08em 0 0.09em 0;font-size:1.1em;}
.cat-class {color:#C61C1C;font-weight:bold;}
.cat-dept {color:#004CBB;font-weight:bold;}
.cat-sect {color:#098A23;font-weight:bold;}
.cat-family {color:#FF8800;font-weight:bold;}
.cat-val {color:#111;}
.scan-hint {font-size:1.1em;color:#087911;font-weight:600;background:#eafdff;padding:.2em .7em;border-radius:.45em;margin:.4em 0 .6em 0;text-align:center;}
.small-dim {color:#666;font-size:.92em;margin-top:.25rem;}
</style>
""", unsafe_allow_html=True)

# ---------------- STATE ----------------
st.session_state.setdefault("latest_declaration", {})
st.session_state.setdefault("latest_itemid", None)
st.session_state.setdefault("picked_locid", "")  # updated by map clicks

handler = DeclareHandler()
map_handler = ShelfMapHandler()

# Show identity & privilege snapshot in debug
if DEBUG:
    info = handler.whoami()
    debug_kv("Session & Privileges Snapshot",
             current_user=info.get("current_user"),
             session_user=info.get("session_user"),
             search_path=info.get("search_path"),
             shelfentries_priv=info.get("shelfentries_priv"))

tab1, tab2 = st.tabs(["📷 Scan via camera", "⌨️ Type/paste barcode"])

# ---------------- CORE FLOW ----------------
def declare_logic(barcode, reset_callback):
    # Trace the entry state
    debug_kv("declare_logic entry", barcode=barcode)

    item = None
    itemid = None
    if barcode:
        item = handler.get_item_by_barcode(barcode)
        if item is not None:
            itemid = int(item['itemid'])

    # Reset message when switching items
    if itemid and st.session_state["latest_itemid"] != itemid:
        st.session_state["latest_declaration"] = {}
        st.session_state["latest_itemid"] = itemid
        st.session_state["picked_locid"] = ""  # clear previous selection

    if not barcode:
        st.info("Please scan or enter the item barcode.")
        return

    if item is None and barcode.strip():
        st.error("❌ Barcode not found in the item table.")
        return

    # ---------- Item details ----------
    st.markdown(f"**Item:** {item['name']}<br>🔖 Barcode: {item['barcode']}", unsafe_allow_html=True)
    st.markdown(
        f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{item['classcat']}</span></div>"
        f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{item['departmentcat']}</span></div>"
        f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{item['sectioncat']}</span></div>"
        f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{item['familycat']}</span></div>",
        unsafe_allow_html=True
    )

    # ---------- Data pulls ----------
    try:
        item_locs_history = handler.get_item_locations(itemid)
    except Exception as e:
        st.error("Failed to fetch historical shelf locations for this item.")
        if DEBUG:
            debug_box("get_item_locations Exception", repr(e))
        return

    try:
        inventory_total = handler.get_inventory_total(itemid)  # read-only info
    except Exception as e:
        inventory_total = 0
        if DEBUG:
            debug_box("get_inventory_total Exception (non-fatal)", repr(e))

    try:
        shelf_locs = map_handler.get_locations()  # FULL MAP from your ShelfMapHandler
    except Exception as e:
        st.error("Failed to load shelf map locations.")
        if DEBUG:
            debug_box("map_handler.get_locations Exception", repr(e))
        return

    # ---------- MAP (click to select) ----------
    st.markdown("#### 🗺️ Click a shelf to select it")
    deck = build_deck(shelf_locs, item_locs_history, st.session_state["picked_locid"])
    event = st.pydeck_chart(
        deck,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-object",
        key="main_shelf_map",
    )

    # Extract clicked object → update picked_locid
    try:
        sel = getattr(event, "selection", None) or event.get("selection") if isinstance(event, dict) else None
        if sel:
            objs = sel.get("objects", {}) if isinstance(sel, dict) else {}
            picked_list = objs.get("shelves") or []
            if picked_list:
                first = picked_list[0]
                data = first.get("object") if isinstance(first, dict) and "object" in first else first
                locid_clicked = str(data.get("locid") or "")
                if locid_clicked:
                    st.session_state["picked_locid"] = locid_clicked
    except Exception as e:
        if DEBUG:
            debug_box("Selection parse Exception (non-fatal)", repr(e))

    # ---------- Chosen shelf ----------
    chosen_locid = st.session_state["picked_locid"]
    if chosen_locid:
        st.success(f"Selected shelf: **{chosen_locid}**")
        st.caption("Click a different shelf to change.")
    else:
        st.info("Click a shelf on the map to select it. (You can still proceed without selection if you type a locid.)")

    # ---------- Quantity & actions ----------
    st.info(f"**Available in inventory (read-only):** {inventory_total}")

    new_qty = st.number_input(
        "Declare current selling area quantity",
        min_value=0, value=0, step=1, key="declare_qty", label_visibility="visible"
    )

    manual_locid = st.text_input(
        "Or type a locid (optional)",
        value=chosen_locid,
        key="declare_locid_text",
        label_visibility="collapsed",
        help="This overrides the clicked shelf if filled."
    ).strip()
    final_locid = manual_locid or chosen_locid

    c1, c2 = st.columns([2, 1])
    confirm_clicked = c1.button("✅ Confirm Declaration", key="btn_confirm_declaration")
    if c2.button("🔄 New Scan", key="btn_new_scan"):
        for k in ["barcode_cam", "barcode_input", "declare_qty", "declare_locid_text"]:
            st.session_state.pop(k, None)
        st.session_state["picked_locid"] = ""
        st.rerun()

    if confirm_clicked:
        if not final_locid:
            st.error("Please click a shelf on the map (or type a locid) before confirming.")
            return
        if new_qty <= 0:
            st.error("Quantity must be greater than zero to declare.")
            return

        try:
            handler.insert_declaration(itemid=itemid, locid=final_locid, qty=new_qty, who="DeclarePage")
        except Exception as e:
            st.error("Failed to record declaration. See debug for details.")
            if DEBUG:
                debug_box("insert_declaration Exception", repr(e))
            return

        st.success(f"Recorded declaration for '{item['name']}' at {final_locid} with quantity {new_qty}.")

        st.session_state["latest_declaration"] = {
            "itemid": itemid,
            "itemname": item['name'],
            "barcode": item['barcode'],
            "locid": final_locid,
            "qty": new_qty
        }
        st.rerun()

def show_latest_declaration_and_items():
    latest = st.session_state.get("latest_declaration")
    if latest and "itemid" in latest:
        st.markdown(
            f"""<div style='background:#e7f8e9;border:1.5px solid #47bd72;
                  border-radius:0.5em;padding:0.65em 1em 0.6em 1em;
                  margin-top:1em;font-size:1.09em;'>
                <b>Latest Declaration:</b><br>
                <b>Item:</b> <span style='color:#1c4680'>{latest["itemname"]}</span><br>
                <b>Barcode:</b> <span style='color:#222;font-family:monospace'>{latest["barcode"]}</span><br>
                <b>Location:</b> <span style='color:#098A23'>{latest["locid"]}</span><br>
                <b>Quantity:</b> <span style='color:#C61C1C'>{latest["qty"]}</span>
            </div>""",
            unsafe_allow_html=True
        )
        try:
            recents = DeclareHandler().get_recent_declarations_at_location(latest["locid"])
        except Exception as e:
            st.error("Failed to load recent declarations for this location.")
            if DEBUG:
                debug_box("get_recent_declarations_at_location Exception", repr(e))
            return

        if not recents.empty:
            st.markdown(
                f"<br/><b>Recent declarations at location <span style='color:#098A23'>{latest['locid']}</span>:</b>",
                unsafe_allow_html=True
            )
            st.dataframe(
                recents.rename(columns={
                    "entryid": "Entry ID",
                    "itemid": "Item ID",
                    "name": "Item Name",
                    "barcode": "Barcode",
                    "quantity": "Declared Qty",
                    "entrydate": "Entry Date"
                }),
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("No declarations recorded yet for this shelf location.")

# ---------------- TABS ----------------
with tab1:
    if QR_AVAILABLE:
        st.markdown(
            "<div class='scan-hint'>Aim the barcode at your phone or webcam for instant detection.<br>Hold steady and close to the lens.</div>",
            unsafe_allow_html=True
        )
        barcode = qrcode_scanner(key="barcode_cam") or ""
        if barcode:
            st.success(f"Scanned: {barcode}")
        declare_logic(barcode, reset_callback=lambda: None)
    else:
        st.warning("Camera scanning not available. Please use tab 2 or pip install streamlit-qrcode-scanner.")

with tab2:
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32, label_visibility="visible")
    declare_logic(barcode, reset_callback=lambda: None)

show_latest_declaration_and_items()
