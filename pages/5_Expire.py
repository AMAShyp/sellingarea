import streamlit as st
import pandas as pd
import datetime
from db_handler import DatabaseManager

# ================== CONFIG ==================
TODAY = pd.Timestamp(datetime.date.today())

st.set_page_config(layout="wide")
st.title("⏳ Near-Expiry by Remaining Stock (fast & read-only)")

# ================== DATA LAYER ==================
class ExpiryHandler(DatabaseManager):
    def get_item_meta(self):
        """Basic item metadata (name/barcode) to join in the UI."""
        return self.fetch_data("SELECT itemid, itemnameenglish AS name, barcode FROM item")

    def get_final_qty_per_item(self):
        """
        Compute final on-hand per item:
          inventory: +RECEIVE - RETURN - DEFECT
          salesitems: - quantity
          sale_return_items: + quantity
        """
        q = """
        WITH inv AS (
          SELECT itemid,
                 SUM(CASE
                       WHEN UPPER(TRIM(trx_type))='RECEIVE' THEN quantity::numeric
                       WHEN UPPER(TRIM(trx_type)) IN ('RETURN','DEFECT') THEN -quantity::numeric
                       ELSE 0::numeric
                     END) AS inv_qty
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
        SELECT COALESCE(inv.itemid, s.itemid, r.itemid) AS itemid,
               COALESCE(inv.inv_qty, 0)
             - COALESCE(s.sales_qty, 0)
             + COALESCE(r.sale_return_qty, 0) AS final_qty
        FROM inv
        FULL JOIN sales s ON s.itemid = inv.itemid
        FULL JOIN sale_ret r ON r.itemid = COALESCE(inv.itemid, s.itemid)
        """
        return self.fetch_data(q)

    def get_near_expiry_allocations(self, near_days: int):
        """
        One-shot SQL:
          1) compute final_qty per item (positive only)
          2) take newest RECEIVE batches per item until covering final_qty
          3) compute near-expiry qty & batch counts, and return per-batch detail
        Returns (summary_df, detail_df)
        """
        q = """
        WITH final_qty AS (
          WITH inv AS (
            SELECT itemid,
                   SUM(CASE
                         WHEN UPPER(TRIM(trx_type))='RECEIVE' THEN quantity::numeric
                         WHEN UPPER(TRIM(trx_type)) IN ('RETURN','DEFECT') THEN -quantity::numeric
                         ELSE 0::numeric
                       END) AS inv_qty
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
          SELECT COALESCE(inv.itemid, s.itemid, r.itemid) AS itemid,
                 COALESCE(inv.inv_qty, 0)
               - COALESCE(s.sales_qty, 0)
               + COALESCE(r.sale_return_qty, 0) AS final_qty
          FROM inv
          FULL JOIN sales s ON s.itemid = inv.itemid
          FULL JOIN sale_ret r ON r.itemid = COALESCE(inv.itemid, s.itemid)
        ),
        pos_final AS (
          SELECT itemid, final_qty
          FROM final_qty
          WHERE final_qty > 0
        ),
        recv AS (
          SELECT
            i.itemid,
            i.batchid,
            i.quantity::numeric AS qty,
            i.expirationdate,
            COALESCE(i.datereceived::timestamp, i.created_at::timestamp) AS received_ts
          FROM inventory i
          WHERE UPPER(TRIM(i.trx_type))='RECEIVE'
        ),
        recv_needed AS (
          -- only RECEIVE rows for items that have stock
          SELECT r.*
          FROM recv r
          JOIN pos_final f ON f.itemid = r.itemid
        ),
        ranked AS (
          -- newest-first per item with running sum
          SELECT
            r.itemid,
            r.batchid,
            r.qty,
            r.expirationdate,
            r.received_ts,
            SUM(r.qty) OVER (
              PARTITION BY r.itemid
              ORDER BY r.received_ts DESC NULLS LAST, r.batchid DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running
          FROM recv_needed r
        ),
        cut AS (
          -- compute how much to take from each batch to cover final_qty
          SELECT
            rk.itemid,
            rk.batchid,
            rk.qty,
            rk.expirationdate,
            rk.received_ts,
            f.final_qty,
            (rk.running - rk.qty) AS prev_running,
            GREATEST(
              0::numeric,
              LEAST(rk.qty, f.final_qty - (rk.running - rk.qty))
            ) AS take
          FROM ranked rk
          JOIN pos_final f ON f.itemid = rk.itemid
          WHERE (rk.running - rk.qty) < f.final_qty  -- batches past this point are not needed
        ),
        detail AS (
          SELECT
            c.itemid,
            c.batchid,
            c.qty AS batch_qty,
            c.take AS used_from_batch,
            c.expirationdate,
            c.received_ts,
            (CASE
               WHEN c.expirationdate IS NOT NULL
                AND c.expirationdate <= CURRENT_DATE + (%s * INTERVAL '1 day')
               THEN TRUE ELSE FALSE
             END) AS is_near_expiry,
            (CASE
               WHEN c.expirationdate IS NOT NULL
               THEN (c.expirationdate - CURRENT_DATE)
               ELSE NULL
             END) AS days_left
          FROM cut c
          WHERE c.take > 0
        ),
        summary AS (
          SELECT
            d.itemid,
            SUM(d.used_from_batch) FILTER (WHERE d.is_near_expiry) AS near_expiry_qty,
            COUNT(*)              FILTER (WHERE d.is_near_expiry) AS near_expiry_batches
          FROM detail d
          GROUP BY d.itemid
        )
        SELECT
          'summary' AS _kind,
          s.itemid,
          NULL::bigint AS batchid,
          NULL::numeric AS batch_qty,
          NULL::numeric AS used_from_batch,
          NULL::date AS expirationdate,
          NULL::timestamp AS received_ts,
          s.near_expiry_qty,
          s.near_expiry_batches,
          NULL::int AS days_left
        FROM summary s
        UNION ALL
        SELECT
          'detail' AS _kind,
          d.itemid,
          d.batchid,
          d.batch_qty,
          d.used_from_batch,
          d.expirationdate,
          d.received_ts,
          NULL::numeric AS near_expiry_qty,
          NULL::bigint AS near_expiry_batches,
          d.days_left
        FROM detail d
        ORDER BY 1, 2, 6 DESC, 3 DESC
        """
        raw = self.fetch_data(q, (int(near_days),))
        if raw is None or raw.empty:
            return (pd.DataFrame(), pd.DataFrame())
        summary = raw[raw["_kind"] == "summary"].drop(columns=["_kind"])
        detail  = raw[raw["_kind"] == "detail"].drop(columns=["_kind"])
        return (summary, detail)

# ================== UI ==================
handler = ExpiryHandler()

st.markdown("### Threshold")
near_days = st.number_input("Near-expiry if ≤ days from today", min_value=1, max_value=365, value=30, step=1)
st.caption("We count units expiring within this many days among the newest RECEIVE batches that cover the item's current stock.")

# Step A: show final quantities by item (context)
final_df = handler.get_final_qty_per_item()
if final_df is None or final_df.empty:
    st.info("No data to compute final quantities.")
    st.stop()

final_df = final_df[final_df["final_qty"] > 0].copy()

meta = handler.get_item_meta()
if meta is not None and not meta.empty:
    final_df = final_df.merge(meta, on="itemid", how="left")
else:
    # Ensure columns exist for display
    final_df["name"] = None
    final_df["barcode"] = None

st.markdown("#### Final quantities by item")
st.dataframe(
    final_df.rename(columns={
        "itemid": "Item ID",
        "name": "Item Name",
        "barcode": "Barcode",
        "final_qty": "Final Qty"
    })[["Item ID", "Item Name", "Barcode", "Final Qty"]],
    use_container_width=True, hide_index=True
)

# Step B: fast set-based allocation + near-expiry counts
summary_df, detail_df = handler.get_near_expiry_allocations(near_days)

# Attach names/barcodes for nicer output
if not summary_df.empty:
    if meta is not None and not meta.empty:
        summary_df = summary_df.merge(meta, on="itemid", how="left")
    else:
        summary_df["name"] = None
        summary_df["barcode"] = None

if not detail_df.empty:
    if meta is not None and not meta.empty:
        detail_df = detail_df.merge(meta, on="itemid", how="left")
    else:
        detail_df["name"] = None
        detail_df["barcode"] = None

# ---- Summary table: safe rename + safe column selection (fixes KeyError) ----
st.markdown("#### Near-expiry summary (among newest RECEIVE batches covering Final Qty)")

if summary_df.empty:
    st.info("No near-expiry units found (within the threshold) or no RECEIVE batches to allocate.")
else:
    # Ensure columns exist
    for col in ["name", "barcode", "near_expiry_qty", "near_expiry_batches"]:
        if col not in summary_df.columns:
            summary_df[col] = 0 if col in ["near_expiry_qty", "near_expiry_batches"] else None

    near_col = f"Near-Expiry ≤ {near_days}d"

    sum_view = summary_df.rename(columns={
        "itemid": "Item ID",
        "name": "Item Name",
        "barcode": "Barcode",
        "near_expiry_qty": near_col,
        "near_expiry_batches": "Affected Batches",
    })

    desired_cols = ["Item ID", "Item Name", "Barcode", near_col, "Affected Batches"]
    available_cols = [c for c in desired_cols if c in sum_view.columns]

    st.dataframe(sum_view[available_cols], use_container_width=True, hide_index=True)

# ---- Detail table: robust selection ----
st.markdown("#### Batch breakdown used to cover Final Qty (newest RECEIVE first)")
if detail_df.empty:
    st.info("No RECEIVE batches were needed/available for items with stock.")
else:
    for col in ["name", "barcode", "batch_qty", "used_from_batch", "expirationdate", "received_ts", "days_left"]:
        if col not in detail_df.columns:
            detail_df[col] = None

    det_view = detail_df.rename(columns={
        "itemid": "Item ID",
        "name": "Item Name",
        "barcode": "Barcode",
        "batchid": "Batch ID",
        "batch_qty": "Batch Qty",
        "used_from_batch": "Used From Batch",
        "expirationdate": "Expiry Date",
        "received_ts": "Received At",
        "days_left": "Days Left",
    })

    desired_cols = ["Item ID", "Item Name", "Barcode", "Batch ID", "Batch Qty", "Used From Batch", "Expiry Date", "Days Left", "Received At"]
    available_cols = [c for c in desired_cols if c in det_view.columns]

    st.dataframe(det_view[available_cols], use_container_width=True, hide_index=True)
