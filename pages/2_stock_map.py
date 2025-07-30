import streamlit as st
from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler
import plotly.graph_objects as go

class BarcodeShelfHandler(DatabaseManager):
    def get_low_stock_items(self, thr=10, limit=10):
        return self.fetch_data("""
            SELECT i.itemid, i.itemnameenglish AS itemname, i.barcode,
                   s.totalquantity AS shelfqty,              -- current on shelf (SUM of shelf.quantity)
                   i.shelfthreshold, i.shelfaverage,
                   s2.locid, s2.quantity as shelf_current_qty
            FROM item i
            JOIN (SELECT itemid, SUM(quantity) AS totalquantity FROM shelf GROUP BY itemid) s
                 ON i.itemid = s.itemid
            JOIN shelf s2 ON s2.itemid = i.itemid
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold,%s)
            ORDER BY s.totalquantity ASC LIMIT %s
        """, (thr, limit))

    def get_first_layer(self, itemid):
        df = self.fetch_data("""
            SELECT expirationdate, quantity, cost_per_unit, locid
            FROM shelf WHERE itemid=%s AND quantity>0
            ORDER BY expirationdate,cost_per_unit LIMIT 1
        """, (itemid,))
        return df.iloc[0].to_dict() if not df.empty else {}

    def get_available_inventory(self, itemid):
        df = self.fetch_data("""
            SELECT SUM(quantity) as available_qty
            FROM inventory
            WHERE itemid=%s AND quantity > 0
        """, (itemid,))
        # Return 0 if no rows, else available quantity as int
        return int(df.iloc[0]['available_qty']) if not df.empty and df.iloc[0]['available_qty'] is not None else 0

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

def map_with_highlights(locs, highlight_locs, label_offset=0.018):
    import math
    shapes = []
    for row in locs:
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        is_hi = row["locid"] in highlight_locs
        fill = "rgba(220,53,69,0.34)" if is_hi else "rgba(180,180,180,0.11)"
        line = dict(width=2 if is_hi else 1.2, color="#d8000c" if is_hi else "#888")
        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h, line=line, fillcolor=fill))
        else:
            rad = math.radians(deg)
            cos, sin = math.cos(rad), math.sin(rad)
            pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            path = "M " + " L ".join(f"{cx+u*cos-v*sin},{cy+u*sin+v*cos}" for u, v in pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        if is_hi:
            r = max(w, h) * 0.5
            shapes.append(dict(type="circle",xref="x",yref="y",
                               x0=cx-r,x1=cx+r,y0=cy-r,y1=cy+r,
                               line=dict(color="#d8000c",width=2,dash="dot")))
    fig = go.Figure()
    fig.update_layout(shapes=shapes, height=340, margin=dict(l=12,r=12,t=10,b=5),
                      plot_bgcolor="#f8f9fa")
    fig.update_xaxes(visible=False, range=[0,1], constrain="domain", fixedrange=True)
    fig.update_yaxes(visible=False, range=[0,1], scaleanchor="x", scaleratio=1, fixedrange=True)
    for row in locs:
        if row["locid"] in highlight_locs:
            x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
            fig.add_annotation(
                x=x + w/2,
                y=1 - (y + h/2) + label_offset,
                text=row.get("label",row["locid"]),
                showarrow=False,
                font=dict(size=11, color="#c90000", family="monospace"),
                align="center",
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="#d8000c",
                borderpad=2,
                opacity=0.97,
            )
    return fig

handler = BarcodeShelfHandler()
map_handler = ShelfMapHandler()
st.set_page_config(layout="wide")
st.title("📤 Low-Stock Items Map (Max refill = available in inventory)")

low_items = handler.get_low_stock_items()
if low_items.empty:
    st.success("✅ All items sufficiently stocked."); st.stop()
locs = map_handler.get_locations()
hi_locs = sorted({handler.get_first_layer(r.itemid).get("locid","") for r in low_items.itertuples() if handler.get_first_layer(r.itemid)})

st.markdown("#### 🗺️ Red = shelves to refill; labels above each red shelf")
st.plotly_chart(map_with_highlights(locs, hi_locs), use_container_width=True, key="main_map")

st.markdown("""
<style>
.item-card{padding:0.22rem 0.39rem;border-radius:.5rem;background:#f8fdfc;
           border:1px solid #c7ebe5;font-size:1.01em;margin-bottom:0}
.good{color:green;font-weight:bold}.bad{color:#c00;font-weight:bold}
.refill-btn button{background:#1abc9c!important;color:#fff!important;font-weight:bold;
                   border-radius:.45rem!important;padding:.15rem .57rem!important;margin-top:.03rem}
.debugbox{background:#f6f7fa;color:#303040;padding:0.18em 0.8em 0.12em 0.8em;font-size:0.98em;margin-bottom:0.1em;border-radius:0.45em;border:1.5px dotted #b1c1d1}
</style>""",unsafe_allow_html=True)

for r in low_items.itertuples():
    layer = handler.get_first_layer(r.itemid)
    if not layer: continue
    locid = getattr(r, "locid", layer.get("locid",""))
    barcode = getattr(r, "barcode", "-")
    itemname = getattr(r, "itemname", "-")
    shelfavg = float(getattr(r, "shelfaverage", 0) or 0)
    shelfthreshold = int(getattr(r, "shelfthreshold", 1))
    current_qty = int(getattr(r, "shelfqty", 0))
    shelf_current_qty = int(getattr(r, "shelf_current_qty", layer.get("quantity", 0)))
    available_in_inventory = handler.get_available_inventory(r.itemid)
    suggested = int(shelfavg - current_qty) if shelfavg > current_qty else 1
    suggested = max(suggested, 1)
    max_refill = max(available_in_inventory, 1)

    debug_text = (
        f"<div class='debugbox'><b>Debug Info:</b><br>"
        f"<b>itemid</b>: {r.itemid}<br>"
        f"<b>From shelf table</b>:<br>"
        f" &nbsp; - <b>locid</b>: <code>{locid}</code><br>"
        f" &nbsp; - <b>current shelf qty</b>: <code>{shelf_current_qty}</code> (shelf.quantity, shelf_map_handler.get_first_layer)<br>"
        f"<b>From item table</b>:<br>"
        f" &nbsp; - <b>shelfqty</b>: <code>{current_qty}</code> (SUM(shelf.quantity))<br>"
        f" &nbsp; - <b>shelfaverage</b>: <code>{shelfavg}</code><br>"
        f" &nbsp; - <b>shelfthreshold</b>: <code>{shelfthreshold}</code><br>"
        f" &nbsp; - <b>barcode</b>: <code>{barcode}</code><br>"
        f" <b>From inventory table</b>:<br>"
        f" &nbsp; - <b>available_in_inventory</b>: <code>{available_in_inventory}</code><br>"
        f"<b>Suggested refill (prefill):</b> {suggested}<br>"
        f"<b>Max allowed (inventory):</b> {max_refill}<br>"
        "</div>"
    )
    qk=f"q_{r.itemid}"; bck=f"bc_{r.itemid}"; btnk=f"btn_{r.itemid}"
    c1,c2,c3,c4 = st.columns([3,0.9,2,0.7])
    c1.markdown(f"<div class='item-card'><b>{itemname}</b><br>"
                f"📦 {current_qty} (avg: {shelfavg}, thr: {shelfthreshold}) | 🗺️ {locid}<br>"
                f"🔖 <span style='font-family:monospace'>{barcode}</span>"
                f"{debug_text}</div>",unsafe_allow_html=True)
    qty = c2.number_input(
        "", min_value=1, max_value=max_refill,
        value=suggested if suggested <= max_refill else max_refill, step=1,
        key=qk, label_visibility="collapsed"
    )
    bc  = c3.text_input("",key=bck,placeholder="scan",label_visibility="collapsed")
    ok  = bc.strip()==barcode
    if bc: c3.markdown(f"<span class='{ 'good' if ok else 'bad'}'>{'✅' if ok else '❌'}</span>",unsafe_allow_html=True)
    fire=c4.button("🚚",key=btnk,disabled=not ok,type="primary")
    if fire:
        handler.move_layer(itemid=r.itemid,expiration=layer["expirationdate"],
                           qty=int(qty),cost=layer["cost_per_unit"],locid=locid,
                           by=st.session_state.get("user_email","AutoTransfer"))
        st.success(f"✅ {itemname} → {qty} to {locid}"); st.rerun()
