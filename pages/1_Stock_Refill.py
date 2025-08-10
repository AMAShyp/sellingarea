# streamlit_low_stock_pydeck_stable.py
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

# ---------------- PAGE SETUP ----------------
st.set_page_config(layout="wide")
st.title("📤 Low‑Stock Items Map (All Inventory Batches Shown) — Pydeck")

# ---------------- UTILITIES ----------------
def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def make_rectangle(x, y, w, h, deg):
    """Closed polygon ([lon, lat] list) in normalized 0..1 canvas with rotation."""
    cx = x + w / 2.0
    cy = y + h / 2.0
    rad = np.deg2rad(float(deg or 0.0))
    c, s = np.cos(rad), np.sin(rad)
    corners = np.array([[-w/2, -h/2], [w/2, -h/2], [w/2, h/2], [-w/2, h/2]])
    rot = corners @ np.array([[c, -s], [s, c]])
    abs_pts = rot + [cx, cy]
    poly = abs_pts.tolist()
    poly.append(poly[0])  # close
    return poly

def build_deck(shelf_locs, highlight_locs):
    """All shelves, highlighted ones in red; single-line tooltip label."""
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
            "label_text": str(row.get("label") or locid),
            "fill_color": ([220, 53, 69, 190] if is_hi else [180, 180, 180, 70]),
            "line_color": ([216, 0, 12, 255] if is_hi else [120, 120, 120, 255]),
        })

    df = pd.DataFrame(rows)
    polygon_layer = pdk.Layer(
        "PolygonLayer",
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
    view_state = pdk.ViewState(longitude=0.5, latitude=0.5, zoom=6, min_zoom=4, max_zoom=20, pitch=0, bearing=0)
    return pdk.Deck(
        layers=[polygon_layer],
        initial_view_state=view_state,
        map_provider=None,
        tooltip={
            "html": "<b>{label_text}</b>",
            "style": {"backgroundColor": "white", "color": "#222", "fontSize": "14px", "font-family": "monospace"},
        },
        height=360,
    )

# ---------------- DATA ACCESS ----------------
class BarcodeShelfHandler(DatabaseManager):
    def get_low_stock_items(self, thr=10, limit=10):
        return self.fetch_data("""
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode,
                   i.familycat, i.sectioncat, i.departmentcat, i.classcat,
                   s.totalquantity AS shelfqty,
                   i.shelfthreshold, i.shelfaverage,
                   s2.locid, s2.quantity as shelf_current_qty
            FROM item i
            JOIN (SELECT itemid, SUM(quantity) AS totalquantity FROM shelf GROUP BY itemid) s
                 ON i.itemid = s.itemid
            JOIN shelf s2 ON s2.itemid = i.itemid
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold, %s)
            ORDER BY s.totalquantity ASC
            LIMIT %s
        """, (thr, limit))

    def get_first_layer(self, itemid):
        df = self.fetch_data("""
            SELECT expirationdate, quantity, cost_per_unit, locid
            FROM shelf
            WHERE itemid=%s AND quantity>0
            ORDER BY expirationdate, cost_per_unit
            LIMIT 1
        """, (int(itemid),))
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_inventory_batches(self, itemid):
        df = self.fetch_data("""
            SELECT quantity, storagelocation, expirationdate
            FROM inventory
            WHERE itemid=%s AND quantity > 0
            ORDER BY expirationdate ASC, quantity DESC
        """, (int(itemid),))
        return df.to_dict("records") if not df.empty else []

    def get_inventory_total(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (int(itemid),))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] is not None else 0

    def move_layer(self, *, itemid, expiration, qty, cost, locid, by):
        # atomic-ish sequence; DB should ideally wrap this in a transaction
        self.execute_command("""
            UPDATE inventory
            SET quantity = quantity - %s
            WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity >= %s
        """, (qty, int(itemid), expiration, cost, qty))
        self.execute_command("""
            INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
            DO UPDATE SET quantity = shelf.quantity + EXCLUDED.quantity,
                          lastupdated = CURRENT_TIMESTAMP
        """, (int(itemid), expiration, qty, cost, locid))
        self.execute_command("""
            INSERT INTO shelfentries(itemid, expirationdate, quantity, createdby, locid)
            VALUES (%s, %s, %s, %s, %s)
        """, (int(itemid), expiration, qty, by, locid))

# ---------------- CACHING (SAFE) ----------------
@st.cache_data(show_spinner=False)
def load_shelf_locs():
    # geometry rarely changes; safe to cache for session
    return ShelfMapHandler().get_locations()

# ---------------- STATE ----------------
if "scan_states" not in st.session_state:
    st.session_state["scan_states"] = {}
if "last_action" not in st.session_state:
    st.session_state["last_action"] = None  # used to debounce reruns

# ---------------- LOAD DATA ----------------
handler = BarcodeShelfHandler()
low_items = handler.get_low_stock_items()
if low_items.empty:
    st.success("✅ All items sufficiently stocked.")
    st.stop()

shelf_locs = load_shelf_locs()

# Precompute first layers ONCE (prevents duplicate DB hits and stabilizes UI)
first_layers = {}
highlight_locids = set()
for r in low_items.itertuples():
    fl = handler.get_first_layer(r.itemid)
    if fl:
        first_layers[r.itemid] = fl
        if fl.get("locid"):
            highlight_locids.add(str(fl["locid"]))

# ---------------- MAP ----------------
st.markdown("#### 🗺️ Red = shelves to refill (single-line label on hover)")
try:
    deck = build_deck(shelf_locs, sorted(highlight_locids))
    st.pydeck_chart(deck, use_container_width=True)
except Exception as e:
    st.error(f"Map render error: {e}")

# ---------------- STYLES ----------------
st.markdown("""
<style>
.item-card{padding:0.22rem 0.39rem 0.42rem 0.39rem;border-radius:.6rem;background:#f7fcfa;
           border:1px solid #c7ebe5;font-size:1.07em;margin-bottom:0;}
.catline{margin:0.13em 0 0.15em 0;font-size:1.1em;}
.cat-class{color:#C61C1C;font-weight:bold;}
.cat-dept{color:#004CBB;font-weight:bold;}
.cat-sect{color:#098A23;font-weight:bold;}
.cat-family{color:#FF8800;font-weight:bold;}
.cat-val{color:#222;}
.inv-batch{background:#fff1e3;display:inline-block;margin:0.08em 0.3em 0.08em 0;padding:0.08em 0.65em 0.08em 0.65em;
           border-radius:.45em;border:1px solid #f1d1aa;font-size:1.03em;}
.good{color:green;font-weight:bold;}.bad{color:#c00;font-weight:bold;}
.scan-hint{font-size:1.05em;color:#087911;font-weight:600;background:#eafdff;padding:.2em .6em;border-radius:.45em;}
</style>
""", unsafe_allow_html=True)

# ---------------- PER-ITEM UI ----------------
scan_states = st.session_state["scan_states"]

for r in low_items.itertuples():
    fl = first_layers.get(r.itemid)
    if not fl:
        continue

    inv_batches = handler.get_inventory_batches(r.itemid)
    available_in_inventory = handler.get_inventory_total(r.itemid)

    locid = getattr(r, "locid", fl.get("locid", ""))
    barcode = getattr(r, "barcode", "-")
    itemname = getattr(r, "itemname", "-")
    shelfavg = float(getattr(r, "shelfaverage", 0) or 0)
    shelfthreshold = int(getattr(r, "shelfthreshold", 1))
    current_qty = int(getattr(r, "shelfqty", 0))
    familycat = getattr(r, "familycat", "-")
    sectioncat = getattr(r, "sectioncat", "-")
    departmentcat = getattr(r, "departmentcat", "-")
    classcat = getattr(r, "classcat", "-")

    suggested = int(shelfavg - current_qty) if shelfavg > current_qty else 1
    suggested = max(suggested, 1)
    max_refill = max(available_in_inventory, 1)

    inv_batches_html = ""
    for batch in inv_batches:
        qty = int(batch.get("quantity", 0) or 0)
        storloc = batch.get("storagelocation", "-")
        exp = str(batch.get("expirationdate", "-"))
        inv_batches_html += f"<div class='inv-batch'>{qty} units &nbsp;|&nbsp; {storloc} &nbsp;|&nbsp; {exp}</div>"

    # Row-scoped keys
    input_key = f"barcode_input_{r.itemid}"
    cam_key = f"barcode_cam_{r.itemid}"
    show_scan = (scan_states.get("active_scan") == r.itemid) if QR_AVAILABLE else False

    with st.container():
        c1, c2, c3, c4 = st.columns([3, 0.9, 2, 1.3])

        # Item card
        c1.markdown(
            f"<div class='item-card'><b>{itemname}</b><br>"
            f"📦 {current_qty} (avg: {shelfavg}, thr: {shelfthreshold}) | 🗺️ {locid}<br>"
            f"🔖 <span style='font-family:monospace'>{barcode}</span><br>"
            f"<b>Inventory batches:</b> {inv_batches_html if inv_batches else '<span style=\"color:#C61C1C;\">None in stock</span>'}<br>"
            f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{classcat}</span></div>"
            f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{departmentcat}</span></div>"
            f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{sectioncat}</span></div>"
            f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{familycat}</span></div>"
            f"</div>",
            unsafe_allow_html=True
        )

        # Quantity to move
        qty_val = c2.number_input(
            "", min_value=1, max_value=max_refill,
            value=min(suggested, max_refill), step=1,
            key=f"qty_{r.itemid}", label_visibility="collapsed"
        )

        # Barcode input + optional scanner
        bc_col = c3
        if QR_AVAILABLE:
            # Toggle scanner for this row only; no auto-rerun loop
            if c4.button("📷 Scan", key=f"btn_scan_{r.itemid}", help="Scan barcode with camera", type="secondary"):
                st.session_state["scan_states"] = {"active_scan": r.itemid}
                st.session_state["last_action"] = f"scan_open_{r.itemid}"
                st.rerun()

            if show_scan:
                st.markdown("<div class='scan-hint'>Aim barcode for this item at the camera below.</div>", unsafe_allow_html=True)
                scanned = qrcode_scanner(key=cam_key) or ""
                if scanned:
                    st.session_state[input_key] = scanned
                    st.session_state["scan_states"] = {}  # close scanner
                    st.session_state["last_action"] = f"scan_done_{r.itemid}"
                    st.rerun()

        barcode_val = bc_col.text_input("", key=input_key, placeholder="Type or scan...", label_visibility="collapsed")
        ok = (barcode_val.strip() == barcode)
        if barcode_val:
            bc_col.markdown(f"<span class='{'good' if ok else 'bad'}'>{'✅' if ok else '❌'}</span>", unsafe_allow_html=True)

        # Refill button (reruns only once on click)
        if c4.button("🚚", key=f"btn_refill_{r.itemid}", disabled=not ok, type="primary"):
            try:
                handler.move_layer(
                    itemid=r.itemid,
                    expiration=fl["expirationdate"],
                    qty=int(qty_val),
                    cost=fl["cost_per_unit"],
                    locid=locid,
                    by=st.session_state.get("user_email", "AutoTransfer"),
                )
                st.success(f"✅ {itemname} → {qty_val} to {locid}")
                st.session_state["last_action"] = f"refilled_{r.itemid}"
                st.rerun()
            except Exception as ex:
                st.error(f"Failed to move stock: {ex}")
