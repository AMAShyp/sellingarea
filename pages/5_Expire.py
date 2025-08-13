import streamlit as st
import pandas as pd
import datetime
from db_handler import DatabaseManager

# ================== CONFIG ==================
TODAY = pd.Timestamp(datetime.date.today())

st.set_page_config(layout="wide")
st.title("⏳ Near-Expiry by Remaining Stock (based on latest received batches)")

# ================== DATA LAYER ==================
class ExpiryHandler(DatabaseManager):
    def get_final_qty_per_item(self):
        """
        Compute final on-hand per item:
          inventory: +RECEIVE - RETURN - DEFECT
          salesitems: - quantity
          sale_return_items: + quantity
        Returns DataFrame: columns [itemid, final_qty]
        """
        q = """
        WITH inv AS (
          SELECT
            itemid,
            SUM(
              CASE
                WHEN UPPER(TRIM(trx_type)) = 'RECEIVE' THEN quantity::numeric
                WHEN UPPER(TRIM(trx_type)) IN ('RETURN','DEFECT') THEN -quantity::numeric
                ELSE 0::numeric
              END
            ) AS inv_qty
          FROM inventory
          GROUP BY itemid
        ),
        sales AS (
          SELECT itemid, SUM(quantity::numeric) AS sales_qty
          FROM salesitems
          GROUP BY itemid
        ),
        sale_ret AS (
          SELECT itemid, SUM(quantity::numeric) AS sale_return_qty
          FROM sale_return_items
          GROUP BY itemid
        )
        SELECT
          COALESCE(inv.itemid, s.itemid, r.itemid) AS itemid,
          COALESCE(inv.inv_qty, 0)
          - COALESCE(s.sales_qty, 0)
          + COALESCE(r.sale_return_qty, 0) AS final_qty
        FROM inv
        FULL JOIN sales s ON s.itemid = inv.itemid
        FULL JOIN sale_ret r ON r.itemid = COALESCE(inv.itemid, s.itemid)
        """
        return self.fetch_data(q)

    def get_item_meta(self):
        """Basic item metadata (name/barcode) to join in the UI."""
        q = "SELECT itemid, itemnameenglish AS name, barcode FROM item"
        return self.fetch_data(q)

    def get_latest_receive_batches(self, itemid, limit=10000):
        """
        Fetch RECEIVE batches for an item ordered by newest first.
        We will walk these until we cover the final qty.
        """
        q = """
        SELECT
          batchid,
          itemid,
          quantity::numeric AS qty,
          expirationdate,
          COALESCE(datereceived::timestamp, created_at)::timestamp AS received_ts
        FROM inventory
        WHERE itemid = %s AND UPPER(TRIM(trx_type)) = 'RECEIVE'
        ORDER BY received_ts DESC NULLS LAST, batchid DESC
        LIMIT %s
        """
        return self.fetch_data(q, (int(itemid), int(limit)))

# ================== UI ==================
handler = ExpiryHandler()

st.markdown("### Step 1 — Configure near-expiry threshold")
col_a, col_b = st.columns([1, 3])
with col_a:
    near_days = st.number_input("Consider near-expiry if ≤ (days)", min_value=1, max_value=365, value=30, step=1)
with col_b:
    st.caption("Items expiring within this many days from **today** will be counted as near-expiry when scanning the latest received batches that cover remaining stock.")

st.markdown("### Step 2 — Compute remaining stock per item")

final_df = handler.get_final_qty_per_item()
if final_df is None or final_df.empty:
    st.info("No data available to compute final quantities.")
    st.stop()

# Only items with positive stock
final_df = final_df[final_df["final_qty"] > 0].copy()

# Join item metadata for nicer output
meta = handler.get_item_meta()
if meta is not None and not meta.empty:
    final_df = final_df.merge(meta, on="itemid", how="left")
else:
    final_df["name"] = None
    final_df["barcode"] = None

st.dataframe(
    final_df.rename(columns={"itemid":"Item ID","name":"Item Name","barcode":"Barcode","final_qty":"Final Qty"}),
    use_container_width=True, hide_index=True
)

st.markdown("### Step 3 — Scan latest RECEIVE batches to cover each item’s remaining stock")

# Process each item: walk latest RECEIVE batches until we cover final_qty
rows_summary = []
rows_detail = []  # per-batch breakdown for the table below

for _, r in final_df.iterrows():
    itemid = int(r["itemid"])
    final_qty = float(r["final_qty"])
    item_name = r.get("name")
    barcode = r.get("barcode")

    batches = handler.get_latest_receive_batches(itemid)
    if batches is None or batches.empty:
        # No receive batches found; nothing to allocate (but final_qty > 0)
        rows_summary.append({
            "itemid": itemid,
            "name": item_name,
            "barcode": barcode,
            "final_qty": final_qty,
            "near_expiry_qty": 0,
            "near_expiry_batches": 0
        })
        continue

    remain = final_qty
    near_qty = 0
    near_batches = 0

    # iterate newest to older
    for _, b in batches.iterrows():
        if remain <= 0:
            break
        take = min(remain, float(b["qty"]) if b["qty"] is not None else 0.0)
        if take <= 0:
            continue

        exp = pd.to_datetime(b["expirationdate"]) if pd.notna(b["expirationdate"]) else pd.NaT
        days_left = (exp - TODAY).days if pd.notna(exp) else None
        is_near = (days_left is not None) and (days_left <= near_days)

        if is_near:
            near_qty += take
            near_batches += 1

        rows_detail.append({
            "itemid": itemid,
            "name": item_name,
            "barcode": barcode,
            "final_qty": final_qty,
            "used_from_batch": take,
            "batchid": b["batchid"],
            "batch_qty": float(b["qty"]) if b["qty"] is not None else None,
            "expirationdate": exp.date().isoformat() if pd.notna(exp) else None,
            "days_left": days_left,
            "is_near_expiry": bool(is_near),
        })

        remain -= take

    rows_summary.append({
        "itemid": itemid,
        "name": item_name,
        "barcode": barcode,
        "final_qty": final_qty,
        "near_expiry_qty": near_qty,
        "near_expiry_batches": near_batches
    })

# Summary table: how many items are near expiry per item (from latest batches covering the stock)
summary_df = pd.DataFrame(rows_summary).sort_values(["name","itemid"]).reset_index(drop=True)
st.markdown("#### Near-expiry summary (units within threshold among newest batches covering current stock)")
st.dataframe(
    summary_df.rename(columns={
        "itemid": "Item ID",
        "name": "Item Name",
        "barcode": "Barcode",
        "final_qty": "Final Qty",
        "near_expiry_qty": f"Near-Expiry ≤ {near_days}d",
        "near_expiry_batches": "Affected Batches"
    }),
    use_container_width=True, hide_index=True
)

# Detail table: which batches were counted
detail_df = pd.DataFrame(rows_detail)
if not detail_df.empty:
    st.markdown("#### Batch breakdown (newest RECEIVE batches used to cover current stock)")
    st.dataframe(
        detail_df.rename(columns={
            "itemid": "Item ID",
            "name": "Item Name",
            "barcode": "Barcode",
            "final_qty": "Item Final Qty",
            "used_from_batch": "Used From Batch",
            "batchid": "Batch ID",
            "batch_qty": "Batch Qty",
            "expirationdate": "Expiry Date",
            "days_left": "Days Left",
            "is_near_expiry": "Near?"
        }),
        use_container_width=True, hide_index=True
    )
else:
    st.info("No RECEIVE batches found to allocate against current stock.")
