import streamlit as st
from db_handler import DatabaseManager

# ──────────────────────────── DB Handler ────────────────────────────
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

    def get_first_expiry_for_item(self, itemid: int):
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

    def move_layer(
        self, *, itemid, expiration, qty, cost, locid, by
    ):
        self.execute_command(
            """
            UPDATE inventory
            SET    quantity = quantity - %s
            WHERE  itemid=%s AND expirationdate=%s AND cost_per_unit=%s
              AND  quantity >= %s
            """,
            (qty, itemid, expiration, cost, qty),
        )
        self.execute_command(
            """
            INSERT INTO shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
            DO UPDATE SET quantity = shelf.quantity + EXCLUDED.quantity,
                          lastupdated = CURRENT_TIMESTAMP
            """,
            (itemid, expiration, qty, cost, locid),
        )
        self.execute_command(
            """
            INSERT INTO shelfentries
            (itemid, expirationdate, quantity, createdby, locid)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (itemid, expiration, qty, by, locid),
        )

# ───────────────────────────── Styling ─────────────────────────────
st.markdown(
    """
<style>
.card-row {
  display: flex;
  align-items: center;
  gap: 1.4rem;
  padding: 1rem 1.4rem;
  margin-bottom: 1.2rem;
  border: 1.5px solid #E4EBEE;
  border-radius: 0.9rem;
  box-shadow: 0 2px 6px rgba(44,62,80,0.08);
  background: #FCFEFF;
}
.card-row .name {
  font-size: 1.15rem;
  font-weight: 700;
  color: #205072;
  min-width: 250px;
}
.card-row .meta {
  font-size: 0.94rem;
  line-height: 1.35;
  min-width: 170px;
}
.card-row .loc {
  font-family: monospace;
  background: #F4FAFA;
  padding: 0.1rem 0.45rem;
  border-radius: 0.45rem;
}
.quantity-box input {
  font-size: 1.08rem !important;
  font-weight: 600 !important;
  border-radius: 0.6rem !important;
  padding: 0.25rem 0.7rem !important;
}
.barcode-box input {
  font-size: 1.02rem !important;
  border-radius: 0.6rem !important;
  padding: 0.3rem 0.8rem !important;
}
.refill-btn button {
  font-size: 1.05rem !important;
  font-weight: 600 !important;
  padding: 0.45rem 1.7rem !important;
  border-radius: 0.7rem !important;
  background: linear-gradient(95deg,#1ABC9C 0%,#26d7aa 100%) !important;
  color: #fff !important;
  border: none !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────── Page ─────────────────────────────────
handler = BarcodeShelfHandler()

st.subheader("📉 Low‑Stock Refill (Barcode Confirmation)")

low_items = handler.get_low_stock_items(threshold=10, limit=10)
if low_items.empty:
    st.success("✅ All shelf quantities meet their thresholds.")
    st.stop()

for _, row in low_items.iterrows():
    layer = handler.get_first_expiry_for_item(row.itemid)
    if not layer:
        st.error(f"No shelf layer for {row.itemname}.")
        continue

    need      = int(row.shelfthreshold) - int(row.shelfqty)
    available = max(1, int(layer["quantity"]))
    default_q = max(1, min(need, available))

    qty_key   = f"qty_{row.itemid}"
    bc_key    = f"bc_{row.itemid}"
    btn_key   = f"btn_{row.itemid}"

    # ── CARD ROW ─────────────────────────────────────────────
    st.markdown('<div class="card-row">', unsafe_allow_html=True)

    st.markdown(
        f'<div class="name">🛒 {row.itemname}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="meta">
            <div>Barcode:&nbsp;<span style="font-family:monospace;">{row.barcode}</span></div>
            <div>Shelf&nbsp;Qty:&nbsp;<b>{row.shelfqty}</b> / Thresh&nbsp;<b>{row.shelfthreshold}</b></div>
            <div>Loc:&nbsp;<span class="loc">{layer.get('locid','')}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        qty = st.number_input(
            "Qty",
            min_value=1,
            max_value=available,
            value=default_q,
            key=qty_key,
            label_visibility="collapsed",
            help=f"Available in back‑store: {available}",
            format="%i",
        )

    with st.container():
        bc_entered = st.text_input(
            "Barcode",
            value="",
            key=bc_key,
            label_visibility="collapsed",
            placeholder="scan / type",
        )

    match = bc_entered.strip() == str(row.barcode)

    with st.container():
        clicked = st.button(
            "🚚 Refill",
            key=btn_key,
            disabled=not match,
            type="primary",
            help="Scan correct barcode to enable",
        )

    st.markdown("</div>", unsafe_allow_html=True)  # close card-row

    # Feedback + action
    if bc_entered and not match:
        st.error("Barcode does not match. Please scan the correct one.", icon="⚠️")
    elif bc_entered and match:
        st.success("Barcode confirmed ✔️")

    if clicked:
        handler.move_layer(
            itemid=row.itemid,
            expiration=layer["expirationdate"],
            qty=int(qty),
            cost=layer["cost_per_unit"],
            locid=layer["locid"],
            by=st.session_state.get("user_email", "AutoTransfer"),
        )
        st.success(
            f"✅ {row.itemname} refilled by {qty} → shelf {layer['locid']}", icon="🎉"
        )
        st.rerun()
