# streamlit_low_stock_pydeck_nolabelwarn.py
import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk

from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

# ---- PAGE ----
st.set_page_config(layout="wide")
st.title("📤 Low-Stock Items Map (All Inventory Batches Shown) — Pydeck")

# ---- UTILS ----
def to_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def make_rectangle(x, y, w, h, deg):
    cx = x + w / 2
    cy = y + h / 2
    rad = np.deg2rad(float(deg or 0))
    c, s = np.cos(rad), np.sin(rad)
    corners = np.array([[-w/2, -h/2], [w/2, -h/2], [w/2, h/2], [-w/2, h/2]])
    rot = corners @ np.array([[c, -s], [s, c]])
    abs_pts = rot + [cx, cy]
    abs_pts = abs_pts.tolist()
    abs_pts.append(abs_pts[0])
    return abs_pts

def build_deck(shelf_locs, highlight_locs):
    hi = set(map(str, highlight_locs))
    rows = []
    for row in shelf_locs:
        locid = str(row.get("locid"))
        coords = make_rectangle(
            to_float(row["x_pct"]),
            to_float(row["y_pct"]),
            to_float(row["w_pct"]),
            to_float(row["h_pct"]),
            row.get("rotation_deg") or 0
        )
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
    return pdk.Deck(
        layers=[polygon_layer],
        initial_view_state=pdk.ViewState(longitude=0.5, latitude=0.5, zoom=6),
        map_provider=None,
        tooltip={"html": "<b>{label_text}</b>"},
        height=360,
    )

# ---- DATA ----
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
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold,%s)
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
        """, (itemid,))
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_inventory_batches(self, itemid):
        df = self.fetch_data("""
            SELECT quantity, storagelocation, expirationdate
            FROM inventory
            WHERE itemid=%s AND quantity > 0
            ORDER BY expirationdate ASC, quantity DESC
        """, (itemid,))
        return df.to_dict("records") if not df.empty else []

    def get_inventory_total(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (itemid,))
        return int(df.iloc[0]['total']) if not df.empty and df.iloc[0]['total'] is not None else 0

    def move_layer(self, *, itemid, expiration, qty, cost, locid, by):
        self.execute_command("""
            UPDATE inventory SET quantity=quantity-%s
            WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity>=%s
        """, (qty, itemid, expiration, cost, qty))
        self.execute_command("""
            INSERT INTO shelf (itemid,expirationdate,quantity,cost_per_unit,locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid,expirationdate,cost_per_unit,locid)
            DO UPDATE SET quantity=shelf.quantity+EXCLUDED.quantity,lastupdated=CURRENT_TIMESTAMP
        """, (itemid, expiration, qty, cost, locid))
        self.execute_command("""
            INSERT INTO shelfentries(itemid,expirationdate,quantity,createdby,locid)
            VALUES (%s,%s,%s,%s,%s)
        """, (itemid, expiration, qty, by, locid))

# ---- LOAD ----
handler = BarcodeShelfHandler()
map_handler = ShelfMapHandler()

low_items = handler.get_low_stock_items()
if low_items.empty:
    st.success("✅ All items sufficiently stocked.")
    st.stop()

shelf_locs = map_handler.get_locations()

# Highlight shelves for low items
highlight_locs = []
first_layers = {}
for r in low_items.itertuples():
    fl = handler.get_first_layer(r.itemid)
    if fl:
        first_layers[r.itemid] = fl
        highlight_locs.append(fl["locid"])

# ---- MAP ----
st.markdown("#### 🗺️ Red = shelves to refill (labels appear on hover)")
st.pydeck_chart(build_deck(shelf_locs, highlight_locs), use_container_width=True)

# ---- UI STYLES ----
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
.inv-batch{background:#fff1e3;display:inline-block;margin:0.08em 0.3em 0.08em 0;padding:0.08em 0.65em;
           border-radius:.45em;border:1px solid #f1d1aa;font-size:1.03em;}
.good{color:green;font-weight:bold;}.bad{color:#c00;font-weight:bold;}
</style>
""", unsafe_allow_html=True)

# ---- LIST ----
scan_states = st.session_state.setdefault("scan_states", {})

for r in low_items.itertuples():
    fl = first_layers.get(r.itemid)
    if not fl:
        continue
    inv_batches = handler.get_inventory_batches(r.itemid)
    available = handler.get_inventory_total(r.itemid)

    locid = getattr(r, "locid", fl["locid"])
    barcode = getattr(r, "barcode", "")
    name = getattr(r, "itemname", "-")
    avg = float(getattr(r, "shelfaverage", 0) or 0)
    thr = int(getattr(r, "shelfthreshold", 1))
    current_qty = int(getattr(r, "shelfqty", 0))
    suggested = max(int(avg - current_qty), 1) if avg > current_qty else 1
    suggested = min(suggested, available if available > 0 else 1)

    inv_html = "".join(
        f"<div class='inv-batch'>{b.get('quantity', 0)} | {b.get('storagelocation', '-')}"
        f" | {b.get('expirationdate', '-')}</div>"
        for b in inv_batches
    )

    with st.container():
        c1, c2, c3, c4 = st.columns([3, 0.9, 2, 1.3])
        c1.markdown(
            f"<div class='item-card'><b>{name}</b><br>"
            f"📦 {current_qty} (avg: {avg}, thr: {thr}) | 🗺️ {locid}<br>"
            f"🔖 <span style='font-family:monospace'>{barcode}</span><br>"
            f"<b>Inventory batches:</b> {inv_html if inv_html else 'None'}<br>"
            f"<div class='catline'><span class='cat-class'>Class:</span> {r.classcat}</div>"
            f"<div class='catline'><span class='cat-dept'>Department:</span> {r.departmentcat}</div>"
            f"<div class='catline'><span class='cat-sect'>Section:</span> {r.sectioncat}</div>"
            f"<div class='catline'><span class='cat-family'>Family:</span> {r.familycat}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        qty_val = c2.number_input(
            "Quantity to move", min_value=1, max_value=max(available, 1),
            value=suggested, step=1, key=f"qty_{r.itemid}",
            label_visibility="collapsed"
        )

        bc_val = c3.text_input(
            "Barcode input", value="", placeholder="Type or scan...",
            key=f"barcode_input_{r.itemid}", label_visibility="collapsed"
        )

        ok = bc_val.strip() == barcode
        if bc_val:
            c3.markdown(f"<span class='{ 'good' if ok else 'bad'}'>{'✅' if ok else '❌'}</span>", unsafe_allow_html=True)

        if c4.button("🚚 Move", key=f"btn_refill_{r.itemid}", disabled=not ok):
            handler.move_layer(
                itemid=r.itemid, expiration=fl["expirationdate"], qty=int(qty_val),
                cost=fl["cost_per_unit"], locid=locid,
                by=st.session_state.get("user_email", "AutoTransfer")
            )
            st.success(f"Moved {qty_val} of {name} to {locid}")
            st.experimental_rerun()
