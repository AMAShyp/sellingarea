import streamlit as st
import pandas as pd
import datetime
from db_handler import DatabaseManager

# ================== CONFIG ==================
TODAY = pd.Timestamp(datetime.date.today())

st.set_page_config(layout="centered")
st.title("⏳ Near-Expiry Overview")

# ================== DATA LAYER ==================
class ExpiryHandler(DatabaseManager):
    def get_item_meta(self):
        """Basic item metadata (name/barcode) to join in the UI."""
        return self.fetch_data("SELECT itemid, itemnameenglish AS name, barcode FROM item")

    def get_near_expiry_allocations(self, near_days: int):
        """
        One-shot SQL:
          1) compute final_qty per item (inventory +RECEIVE -RETURN -DEFECT - sales + sale_returns)
          2) take newest RECEIVE batches per item until covering final_qty
          3) return both summary (per item) and detail (per batch used)
        Returns (summary_df, detail_df)
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
        ),
        final_qty AS (
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
          SELECT r.*
          FROM recv r
          JOIN pos_final f ON f.itemid = r.itemid
        ),
        ranked AS (
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
          WHERE (rk.running - rk.qty) < f.final_qty
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

# Only one control: the threshold in days
with st.sidebar:
    near_days = st.number_input("Near-expiry if ≤ days", min_value=1, max_value=365, value=30, step=1)
    st.caption("Counts units expiring within this many days among the newest RECEIVE batches that cover the item's remaining stock.")

# Fetch results
summary_df, detail_df = handler.get_near_expiry_allocations(near_days)

# Attach names/barcodes (for display)
meta = handler.get_item_meta()
if not summary_df.empty:
    if meta is not None and not meta.empty:
        summary_df = summary_df.merge(meta, on="itemid", how="left")
    else:
        summary_df["name"] = None
        summary_df["barcode"] = None

if not detail_df.empty:
    if meta is not None and not meta.empty:
        detail_df = detail_df.merge(meta, on="itemid", how="left")

# Build the compact output you want
if summary_df.empty:
    st.success("🎉 No items near expiry within the selected threshold.")
else:
    # Per item: soonest days left & date among near-expiry batches
    near_detail = pd.DataFrame()
    if not detail_df.empty:
        nd = detail_df.copy()
        nd = nd[nd["days_left"].notna()]  # only batches with an expiry date
        # Keep only near-expiry rows
        nd = nd.merge(summary_df[["itemid"]], on="itemid", how="inner")
        # For soonest expiry per item, filter to batches that are within threshold
        # We can recompute is_near here quickly:
        # (days_left <= near_days) implied by SQL condition already, but detail includes all used batches.
        nd = nd[nd["days_left"] <= near_days]
        if not nd.empty:
            soonest = nd.sort_values(["itemid", "days_left"]).groupby("itemid", as_index=False).first()
            near_detail = soonest[["itemid", "days_left", "expirationdate"]].rename(
                columns={"days_left": "soonest_days_left", "expirationdate": "soonest_expiry_date"}
            )

    # Merge soonest info into summary
    out = summary_df.merge(near_detail, on="itemid", how="left")

    # KPI header
    total_items = (out["near_expiry_qty"] > 0).sum()
    total_units = int(out["near_expiry_qty"].fillna(0).sum())

    c1, c2 = st.columns(2)
    c1.metric("Items near expiry", f"{total_items}")
    c2.metric(f"Units near expiry (≤ {near_days}d)", f"{total_units}")

    # Friendly display
    near_col = f"Near-Expiry ≤ {near_days}d"

    # Ensure columns exist
    for col in ["name", "barcode", "near_expiry_qty", "soonest_days_left", "soonest_expiry_date", "near_expiry_batches"]:
        if col not in out.columns:
            out[col] = None

    show = out.rename(columns={
        "itemid": "Item ID",
        "name": "Item Name",
        "barcode": "Barcode",
        "near_expiry_qty": near_col,
        "near_expiry_batches": "Affected Batches",
        "soonest_days_left": "Soonest Days Left",
        "soonest_expiry_date": "Soonest Expiry Date"
    })[["Item ID", "Item Name", "Barcode", near_col, "Soonest Days Left", "Soonest Expiry Date", "Affected Batches"]]

    # Sort by soonest first, then by quantity (desc)
    if "Soonest Days Left" in show.columns:
        show = show.sort_values(["Soonest Days Left", near_col], ascending=[True, False])

    st.markdown("### Items near expiry")
    st.dataframe(show, use_container_width=True, hide_index=True)
