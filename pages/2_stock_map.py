import streamlit as st
from db_handler import DatabaseManager
import plotly.graph_objects as go
from PIL import Image
import math

# ─────────────────────────  MAP HELPERS  ──────────────────────────
class ShelfMapHandler:
    def get_locations(self):
        # ← TODO: replace with real loader / DB call
        return [
            # Example:
            # {"locid": "r12g2", "x_pct": 0.30, "y_pct": 0.55,
            #  "w_pct": 0.10, "h_pct": 0.06, "rotation_deg": 0}
        ]

    def get_png_path(self):
        return "assets/shelf_map.png"      # floor‑plan image

def _img_ratio(path: str) -> float:
    try:
        with open(path, "rb") as f:
            f.seek(16); w = int.from_bytes(f.read(4), "big"); h = int.from_bytes(f.read(4), "big")
        return h / w
    except Exception:
        return 1.0

@st.cache_data(ttl=3600)
def load_locations(_handler):            # leading “_” ⇒ not hashed
    return _handler.get_locations()

@st.cache_resource
def load_bg(_handler):
    return Image.open(_handler.get_png_path())

def map_with_highlights(locs, highlight_locs, img, png_ratio):
    shapes = []
    for row in locs:
        x, y, w, h = map(float, (row["x_pct"], row["y_pct"], row["w_pct"], row["h_pct"]))
        deg = float(row.get("rotation_deg") or 0)
        cx, cy = x + w/2, 1 - (y + h/2)
        y_draw = 1 - y - h
        is_hi = row["locid"] in highlight_locs
        fill = "rgba(128,128,128,0.12)" if not is_hi else "rgba(255,0,0,0.28)"  # grey vs red
        line = dict(width=2 if is_hi else 1, color="#FF0000" if is_hi else "#666666")

        if deg == 0:
            shapes.append(dict(type="rect", x0=x, y0=y_draw, x1=x+w, y1=y_draw+h,
                               line=line, fillcolor=fill))
        else:
            rad, cos, sin = math.radians(deg), math.cos(math.radians(deg)), math.sin(math.radians(deg))
            pts = [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]
            path = "M " + " L ".join(f"{cx+u*cos-v*sin},{cy+u*sin+v*cos}" for u,v in pts) + " Z"
            shapes.append(dict(type="path", path=path, line=line, fillcolor=fill))
        if is_hi:
            r = max(w, h)*0.55
            shapes.append(dict(type="circle",xref="x",yref="y",
                               x0=cx-r,x1=cx+r,y0=cy-r,y1=cy+r,
                               line=dict(color="#FF0000",width=2,dash="dot")))
    fig = go.Figure()
    if img is not None:
        fig.add_layout_image(dict(source=img,xref="x",yref="y",x=0,y=1,
                                  sizex=1,sizey=1,xanchor="left",yanchor="top",layer="below"))
    fig.update_layout(shapes=shapes,height=340,margin=dict(l=12,r=12,t=10,b=5))
    fig.update_xaxes(visible=False,range=[0,1],constrain="domain")
    fig.update_yaxes(visible=False,range=[0,1],scaleanchor="x",scaleratio=png_ratio)
    return fig

# ───────────────────────  BARCODE/DB  ────────────────────────────
class BarcodeShelfHandler(DatabaseManager):
    def get_low_stock_items(self, thr=10, limit=10):
        return self.fetch_data("""
            SELECT i.itemid,i.itemnameenglish AS itemname,i.barcode,
                   s.totalquantity AS shelfqty,i.shelfthreshold
            FROM item i
            JOIN (SELECT itemid,SUM(quantity) AS totalquantity FROM shelf GROUP BY itemid) s
                 ON i.itemid=s.itemid
            WHERE s.totalquantity <= COALESCE(i.shelfthreshold,%s)
            ORDER BY s.totalquantity ASC LIMIT %s""",(thr,limit))

    def get_first_layer(self,itemid):
        df=self.fetch_data("""
            SELECT expirationdate,quantity,cost_per_unit,locid
            FROM shelf WHERE itemid=%s AND quantity>0
            ORDER BY expirationdate,cost_per_unit LIMIT 1""",(itemid,))
        return df.iloc[0].to_dict() if not df.empty else {}

    def move_layer(self,*,itemid,expiration,qty,cost,locid,by):
        self.execute_command("""
            UPDATE inventory SET quantity=quantity-%s
            WHERE itemid=%s AND expirationdate=%s AND cost_per_unit=%s AND quantity>=%s""",
            (qty,itemid,expiration,cost,qty))
        self.execute_command("""
            INSERT INTO shelf (itemid,expirationdate,quantity,cost_per_unit,locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid,expirationdate,cost_per_unit,locid)
            DO UPDATE SET quantity=shelf.quantity+EXCLUDED.quantity,lastupdated=CURRENT_TIMESTAMP""",
            (itemid,expiration,qty,cost,locid))
        self.execute_command("""
            INSERT INTO shelfentries(itemid,expirationdate,quantity,createdby,locid)
            VALUES (%s,%s,%s,%s,%s)""",(itemid,expiration,qty,by,locid))

handler, map_handler = BarcodeShelfHandler(), ShelfMapHandler()

# ─────────────────────────  UI  ────────────────────────────
st.set_page_config(layout="wide")
st.title("📤 Low‑Stock Refill & Map")

low_items = handler.get_low_stock_items()
if low_items.empty:
    st.success("✅ All items sufficiently stocked."); st.stop()

locs   = load_locations(map_handler)
bg_img = load_bg(map_handler)
ratio  = _img_ratio(map_handler.get_png_path())
hi_locs = sorted({handler.get_first_layer(r.itemid).get("locid","") for r in low_items.itertuples() if handler.get_first_layer(r.itemid)})

st.markdown("#### 🗺️ Shelves needing refill (in **red**)")
st.plotly_chart(map_with_highlights(locs,hi_locs,bg_img,ratio),use_container_width=True,key="main_map")

st.markdown("""
<style>
.item-card{padding:0.25rem 0.45rem;border-radius:.6rem;background:#f8fdfc;
           border:1px solid #c7ebe5;font-size:1.02em;margin-bottom:0}
.good{color:green;font-weight:bold}.bad{color:#c00;font-weight:bold}
.refill-btn button{background:#1abc9c!important;color:#fff!important;font-weight:bold;
                   border-radius:.45rem!important;padding:.18rem .65rem!important;margin-top:.05rem}
</style>""",unsafe_allow_html=True)

for r in low_items.itertuples():
    layer = handler.get_first_layer(r.itemid)
    if not layer: continue
    locid = layer.get("locid","")
    avail = int(layer["quantity"]); need = max(1,int(r.shelfthreshold)-int(r.shelfqty))
    sugg  = min(need,avail)

    qk=f"q_{r.itemid}"; bck=f"bc_{r.itemid}"; btnk=f"btn_{r.itemid}"
    c1,c2,c3,c4 = st.columns([3,0.9,2,0.7])
    c1.markdown(f"<div class='item-card'><b>{r.itemname}</b><br>"
                f"📦 {r.shelfqty}/{r.shelfthreshold} | 🗺️ {locid}<br>"
                f"🔖 <span style='font-family:monospace'>{r.barcode}</span></div>",unsafe_allow_html=True)
    qty = c2.number_input("",1,avail,sugg,key=qk,label_visibility="collapsed")
    bc  = c3.text_input("",key=bck,placeholder="scan",label_visibility="collapsed")
    ok  = bc.strip()==r.barcode
    if bc: c3.markdown(f"<span class='{ 'good' if ok else 'bad'}'>{'✅' if ok else '❌'}</span>",unsafe_allow_html=True)
    fire=c4.button("🚚",key=btnk,disabled=not ok,type="primary")
    if fire:
        handler.move_layer(itemid=r.itemid,expiration=layer["expirationdate"],
                           qty=int(qty),cost=layer["cost_per_unit"],locid=locid,
                           by=st.session_state.get("user_email","AutoTransfer"))
        st.success(f"✅ {r.itemname} → {qty} to {locid}"); st.rerun()
