import streamlit as st
from db_handler import DatabaseManager
from shelf_map.shelf_map_handler import ShelfMapHandler
import plotly.graph_objects as go

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

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
            ORDER BY s.totalquantity ASC LIMIT %s
        """, (thr, limit))

    def get_first_layer(self, itemid):
        df = self.fetch_data("""
            SELECT expirationdate, quantity, cost_per_unit, locid
            FROM shelf WHERE itemid=%s AND quantity>0
            ORDER BY expirationdate,cost_per_unit LIMIT 1
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
st.title("📤 Low-Stock Items Map (All Inventory Batches Shown)")

low_items = handler.get_low_stock_items()
if low_items.empty:
    st.success("✅ All items sufficiently stocked."); st.stop()
locs = map_handler.get_locations()
hi_locs = sorted({handler.get_first_layer(r.itemid).get("locid","") for r in low_items.itertuples() if handler.get_first_layer(r.itemid)})

st.markdown("#### 🗺️ Red = shelves to refill; labels above each red shelf")
st.plotly_chart(map_with_highlights(locs, hi_locs), use_container_width=True, key="main_map")

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
.refill-btn button{background:#1abc9c!important;color:#fff!important;font-weight:bold;
                   border-radius:.45rem!important;padding:.15rem .57rem!important;margin-top:.03rem}
.scan-hint {font-size:1.15em;color:#087911;font-weight:600;background:#eafdff;padding:.13em .7em .12em .7em;border-radius:.45em;margin:.15em 0 .4em 0;text-align:center;}
</style>""",unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📷 Scan barcode (camera)", "⌨️ Type/paste barcode"])

def get_card(barcode):
    # Renders a single item card (if barcode valid, else nothing)
    for r in low_items.itertuples():
        if barcode and barcode == getattr(r, "barcode", None):
            layer = handler.get_first_layer(r.itemid)
            if not layer: continue
            inv_batches = handler.get_inventory_batches(r.itemid)
            available_in_inventory = handler.get_inventory_total(r.itemid)
            locid = getattr(r, "locid", layer.get("locid",""))
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
                qty = batch.get("quantity", 0)
                storloc = batch.get("storagelocation", "-")
                exp = str(batch.get("expirationdate", "-"))
                inv_batches_html += (
                    f"<div class='inv-batch'>{qty} units &nbsp;|&nbsp; {storloc} &nbsp;|&nbsp; {exp}</div>"
                )
            qk=f"q_{r.itemid}"; bck=f"bc_{r.itemid}"; btnk=f"btn_{r.itemid}"
            c1,c2,c3,c4 = st.columns([3,0.9,2,0.7])
            c1.markdown(
                f"<div class='item-card'><b>{itemname}</b><br>"
                f"📦 {current_qty} (avg: {shelfavg}, thr: {shelfthreshold}) | 🗺️ {locid}<br>"
                f"🔖 <span style='font-family:monospace'>{barcode}</span><br>"
                f"<b>Inventory batches:</b> {inv_batches_html if inv_batches else '<span style=\"color:#C61C1C;\">None in stock</span>'}<br>"
                f"<div class='catline'><span class='cat-class'>Class:</span> <span class='cat-val'>{classcat}</span></div>"
                f"<div class='catline'><span class='cat-dept'>Department:</span> <span class='cat-val'>{departmentcat}</span></div>"
                f"<div class='catline'><span class='cat-sect'>Section:</span> <span class='cat-val'>{sectioncat}</span></div>"
                f"<div class='catline'><span class='cat-family'>Family:</span> <span class='cat-val'>{familycat}</span></div>"
                f"</div>", unsafe_allow_html=True)
            qty = c2.number_input(
                "", min_value=1, max_value=max_refill,
                value=suggested if suggested <= max_refill else max_refill, step=1,
                key=qk, label_visibility="collapsed"
            )
            bc  = c3.text_input("",key=bck,placeholder="scan",label_visibility="collapsed", value=barcode)
            ok  = bc.strip()==barcode
            if bc: c3.markdown(f"<span class='{ 'good' if ok else 'bad'}'>{'✅' if ok else '❌'}</span>",unsafe_allow_html=True)
            fire=c4.button("🚚",key=btnk,disabled=not ok,type="primary")
            if fire:
                handler.move_layer(itemid=r.itemid,expiration=layer["expirationdate"],
                                   qty=int(qty),cost=layer["cost_per_unit"],locid=locid,
                                   by=st.session_state.get("user_email","AutoTransfer"))
                st.success(f"✅ {itemname} → {qty} to {locid}"); st.rerun()
            return True
    return False

def reset_scan():
    for k in list(st.session_state.keys()):
        if k.startswith("barcode_cam") or k.startswith("barcode_input"):
            st.session_state.pop(k)

with tab1:
    barcode = ""
    if QR_AVAILABLE:
        st.markdown("<div class='scan-hint'>Aim the barcode at your phone or webcam for instant detection.<br>Hold steady and close to the lens.</div>", unsafe_allow_html=True)
        barcode = qrcode_scanner(key="barcode_cam") or ""
        if barcode:
            st.success(f"Scanned: {barcode}")
            found = get_card(barcode)
            if found:
                if st.button("🔄 New Scan", type="secondary"):
                    reset_scan()
                    st.rerun()
            else:
                st.error("Barcode scanned, but no matching low-stock item.")
        else:
            st.info("Camera ready. Show barcode to scan.")
    else:
        st.warning("Camera scanning not available. Please use tab 2 or `pip install streamlit-qrcode-scanner`.")

with tab2:
    barcode = st.text_input("Scan or enter barcode", key="barcode_input", max_chars=32)
    found = get_card(barcode)
    if found:
        if st.button("🔄 New Scan", type="secondary"):
            reset_scan()
            st.rerun()
