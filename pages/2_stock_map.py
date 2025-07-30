import streamlit as st
from db_handler import DatabaseManager
import plotly.graph_objects as go
from PIL import Image

# --- MAP HANDLER ---
class ShelfMapHandler:
    def get_locations(self):
        # Replace with your real loader/DB logic
        return [
            # Example: {"locid": "r12g2", "x_pct": 0.30, "y_pct": 0.55, "w_pct": 0.10, "h_pct": 0.06, "rotation_deg": 0}
        ]
    def get_png_path(self):
        return "assets/shelf_map.png"

def _img_ratio(path: str) -> float:
    try:
        with open(path, "rb") as f:
            f.seek(16)
            width = int.from_bytes(f.read(4), "big")
            height = int.from_bytes(f.read(4), "big")
        return height / width
    except Exception:
        return 1.0

@st.cache_data(ttl=3600)
def load_locations(_handler):
    return _handler.get_locations()
@st.cache_resource
def load_bg(_handler):
    return Image.open(_handler.get_png_path())

def map_with_highlights(locs, highlight_locs, img, png_ratio):
    import math
    shapes = []
    for row in locs:
        x, y, w, h = float(row["x_pct"]), float(row["y_pct"]), float(row["w_pct"]), float(row["h_pct"])
        deg = float(row.get("rotation_deg") or 0.0)
        cx = x + w/2
        cy = 1 - (y + h/2)
        y_draw = 1 - y - h
        is_hi = row["locid"] in highlight_locs if highlight_locs else False
        fill = "rgba(26,188,156,0.09)" if not is_hi else "rgba(255,128,0,0.22)"
        line = dict(width=2 if is_hi else 1, color="#FF8000" if is_hi else "#1ABC9C")
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            path = "M " + " L ".join(f"{cx+u*cos-v*sin},{cy+u*sin+v*cos}" for u, v in pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        if is_hi:
            r = max(w, h) * 0.55
            shapes.append(dict(type="circle", xref="x", yref="y",
                               x0=cx - r, x1=cx + r, y0=cy - r, y1=cy + r,
                               line=dict(color="#FF8000", width=2, dash="dot")))
    fig = go.Figure()
    if img is not None:
        fig.add_layout_image(dict(
            source=img, xref="x", yref="y",
            x=0, y=1, sizex=1, sizey=1,
            xanchor="left", yanchor="top", layer="below"))
    fig.update_layout(shapes=shapes, height=340, margin=dict(l=12,r=12,t=10,b=5))
    fig.update_xaxes(visible=False, range=[0,1], constrain="domain")
    fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=png_ratio)
    fig.update_traces(hoverinfo="skip", selector=dict(type="scatter"))
    return fig

# --- BARCODE HANDLER ---
class BarcodeShelfHandler(DatabaseManager):
    def get_low_stock_items(self, threshold=10, limit=10):
        return self.fetch_data(
            """
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode, 
                   s.totalquantity AS shelfqty, i.shelfthreshold
            FROM item i
            JOIN (
                SELECT itemid, SUM(quantity) AS totalquantity
                FROM shelf
                GROUP BY itemid
            ) s ON i.itemid = s.itemid
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold, %s)
            ORDER BY s.totalquantity ASC
            LIMIT %s
            """,
            (threshold, limit),
        )
    def get_first_expiry_for_item(self, itemid):
        df = self.fetch_data(
            """
            SELECT expirationdate, quantity, cost_per_unit, locid
            FROM shelf
            WHERE itemid = %s AND quantity > 0
            ORDER BY expirationdate ASC, cost_per_unit ASC
            LIMIT 1
            """,
            (itemid,),
        )
        return df.iloc[0].to_dict() if not df.empty else {}
    def move_layer(self, *, itemid, expiration, qty, cost, locid, by):
        self.execute_command(
            """
            UPDATE inventory
            SET quantity = quantity - %s
            WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity >= %s
            """,
            (qty, itemid, expiration, cost, qty),
        )
        self.execute_command(
            """
            INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
            DO UPDATE SET quantity = shelf.quantity + EXCLUDED.quantity, lastupdated = CURRENT_TIMESTAMP
            """,
            (itemid, expiration, qty, cost, locid),
        )
        self.execute_command(
            """
            INSERT INTO shelfentries (itemid, expirationdate, quantity, createdby, locid)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (itemid, expiration, qty, by, locid),
        )

handler = BarcodeShelfHandler()
map_handler = ShelfMapHandler()

st.set_page_config(layout="wide")
st.title("📤 Auto Refill: Low-Stock Items + Shelf Map")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ All items are sufficiently stocked.")
    st.stop()

locs = load_locations(map_handler)
bg_img = load_bg(map_handler)
img_ratio = _img_ratio(map_handler.get_png_path())

# --- Find all locations to highlight ---
highlight_locs = []
item_locids = []
for idx, row in low_items.iterrows():
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if expiry_layer and expiry_layer.get("locid"):
        highlight_locs.append(expiry_layer["locid"])
        item_locids.append(expiry_layer["locid"])
highlight_locs = list(sorted(set(highlight_locs)))

# --- Render MAP (one map for all) ---
fig = map_with_highlights(locs, highlight_locs, bg_img, img_ratio)
st.markdown("#### 🗺️ Shelves with items to refill are highlighted below:")
st.plotly_chart(fig, use_container_width=True, key="main_map")

# --- List items below the map ---
st.markdown("""
<style>
.item-card {padding:0.29rem 0.4rem;border-radius:0.7rem;background:#f8fdfc;
            border:1px solid #c7ebe5;font-size:1.04em;margin-bottom:0;}
.success-text { color: green; font-weight: bold; margin-top: 0.1em;}
.error-text { color: #cc3300; font-weight: bold; margin-top: 0.1em;}
.refill-btn button {
    background-color:#1ABC9C!important;color:white!important;font-weight:bold;
    border-radius:0.5rem!important;padding:0.21rem 0.7rem!important;margin-top:0.1em;}
</style>
""", unsafe_allow_html=True)

for idx, row in low_items.iterrows():
    expiry_layer = handler.get_first_expiry_for_item(row["itemid"])
    if not expiry_layer:
        st.error(f"❌ Inventory data missing for {row['itemname']}.")
        continue
    shelfqty = int(row["shelfqty"])
    shelfthreshold = int(row["shelfthreshold"])
    to_transfer = max(1, shelfthreshold - shelfqty)
    avail_qty = int(expiry_layer["quantity"])
    suggested_qty = min(to_transfer, avail_qty)
    locid = expiry_layer.get("locid", "")

    qty_key = f"qty_{row['itemid']}"
    barcode_key = f"barcode_{row['itemid']}"
    button_key = f"refill_{row['itemid']}"

    cols = st.columns([2.9, 0.9, 2, 0.7])
    cols[0].markdown(
        f"<div class='item-card'><b>{row['itemname']}</b><br>"
        f"📦 Shelf: {shelfqty}/{shelfthreshold} | 🗺️ {locid}<br>"
        f"<span style='font-size:0.95em;'>🔖 <span style='font-family:monospace;'>{row['barcode']}</span></span></div>",
        unsafe_allow_html=True)
    qty = cols[1].number_input("Qty", 1, avail_qty, suggested_qty, key=qty_key, label_visibility="collapsed")
    barcode_input = cols[2].text_input("Barcode", key=barcode_key, placeholder="Scan barcode...", label_visibility="collapsed")
    barcode_correct = barcode_input.strip() == row["barcode"]
    if barcode_input:
        if barcode_correct:
            cols[2].markdown("<div class='success-text'>✅</div>", unsafe_allow_html=True)
        else:
            cols[2].markdown("<div class='error-text'>❌</div>", unsafe_allow_html=True)
    refill_clicked = cols[3].button("🚚", key=button_key, disabled=not barcode_correct, help="Refill", type="primary")
    if refill_clicked:
        user = st.session_state.get("user_email", "AutoTransfer")
        handler.move_layer(
            itemid=row["itemid"],
            expiration=expiry_layer["expirationdate"],
            qty=int(qty),
            cost=expiry_layer["cost_per_unit"],
            locid=locid,
            by=user,
        )
        st.success(f"✅ {row['itemname']} refilled ({qty} units to {locid})!")
        st.rerun()
