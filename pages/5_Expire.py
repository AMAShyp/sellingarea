import streamlit as st
import pandas as pd
import datetime
from db_handler import DatabaseManager

# ================== CONFIG ==================
TODAY = pd.Timestamp(datetime.date.today())

st.set_page_config(layout="centered")
st.title("⏳ Near-Expiry Overview (Remaining Stock)")

# ================== DATA LAYER ==================
class ExpiryHandler(DatabaseManager):
    def get_item_meta(self):
        return self.fetch_data("SELECT itemid, itemnameenglish AS name, barcode FROM item")

    def get_quantities_and_allocations(self, near_days: int):
        """
        One-shot SQL that:
          1) Computes per-item quantities:
              - recv_qty (inventory RECEIVE)
              - rtn_def_qty (inventory RETURN + DEFECT)
              - sales_qty (salesitems)
              - sale_return_qty (sale_return_items)
              - final_qty = recv_qty - rtn_def_qty - sales_qty + sale_return_qty
          2) For items with final_qty>0, takes the NEWEST RECEIVE batches per item
             until we cover final_qty (per-item running sum).
          3) Returns:
             - QUANT per item (recv/rtn_def/sales/ret/final)
             - DETAIL rows for the allocated batches (used_from_batch, days_left)
        """
        q = """
        WITH inv_break AS (
          SELECT
            itemid,
            SUM(CASE WHEN UPPER(TRIM(trx_type))='RECEIVE' THEN quantity::numeric ELSE 0::numeric END) AS recv_qty,
            SUM(CASE WHEN UPPER(TRIM(trx_type)) IN ('RETURN','DEFECT') THEN quantity::numeric ELSE 0::numeric END) AS rtn_def_qty
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
        quant AS (
          SELECT
            COALESCE(i.itemid, s.itemid, r.itemid) AS itemid,
            COALESCE(i.recv_qty, 0)        AS recv_qty,
            COALESCE(i.rtn_def_qty, 0)     AS rtn_def_qty,
            COALESCE(s.sales_qty, 0)       AS sales_qty,
            COALESCE(r.sale_return_qty, 0) AS sale_return_qty,
            COALESCE(i.recv_qty, 0)
          - COALESCE(i.rtn_def_qty, 0)
          - COALESCE(s.sales_qty, 0)
          + COALESCE(r.sale_return_qty, 0) AS final_qty
          FROM inv_break i
          FULL JOIN sales s     ON s.itemid = i.itemid
          FULL JOIN sale_ret r  ON r.itemid = COALESCE(i.itemid, s.itemid)
        ),
        pos_final AS (
          SELECT itemid, final_qty
          FROM quant
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
            GREATEST(0::numeric, LEAST(rk.qty, f.final_qty - (rk.running - rk.qty))) AS take
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
                THEN (c.expirationdate - CURRENT_DATE)
               ELSE NULL
             END) AS days_left,
            (CASE
               WHEN c.expirationdate IS NOT NULL
                AND c.expirationdate <= CURRENT_DATE + (%s * INTERVAL '1 day')
               THEN TRUE ELSE FALSE
             END) AS is_within_threshold
          FROM cut c
          WHERE c.take > 0
        )
        SELECT 'quant' AS _kind, q.*, NULL::bigint AS batchid, NULL::numeric AS batch_qty,
               NULL::numeric AS used_from_batch, NULL::date AS expirationdate, NULL::timestamp AS received_ts,
               NULL::int AS days_left, NULL::boolean AS is_within_threshold
        FROM quant q
        UNION ALL
        SELECT 'detail' AS _kind, d.itemid, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric,
               d.batchid, d.batch_qty, d.used_from_batch, d.expirationdate, d.received_ts,
               d.days_left, d.is_within_threshold
        FROM detail d
        ORDER BY 1, 2, 11 DESC NULLS LAST, 9 DESC NULLS LAST
        """
        raw = self.fetch_data(q, (int(near_days),))
        if raw is None or raw.empty:
            return pd.DataFrame(), pd.DataFrame()
        quant_df  = raw[raw["_kind"]=="quant"].drop(columns=["_kind"])
        detail_df = raw[raw["_kind"]=="detail"].drop(columns=["_kind"])
        return quant_df, detail_df

# ================== UI ==================
handler = ExpiryHandler()

st.markdown("#### Settings")
near_days = st.number_input("Near-expiry threshold (days)", min_value=1, max_value=365, value=30, step=1,
                            help="Units expiring within this many days are counted in “Units ≤ X days”.")

# Fetch data
quant_df, detail_df = handler.get_quantities_and_allocations(near_days)

# Keep only items with positive Net Remain
if not quant_df.empty:
    quant_df = quant_df[quant_df["final_qty"] > 0].copy()

# Attach item meta
meta = handler.get_item_meta()
if not quant_df.empty and meta is not None and not meta.empty:
    quant_df = quant_df.merge(meta, on="itemid", how="left")

# ===== Build expiry stats from allocated batches (detail_df) =====
stats = None
if not detail_df.empty:
    d = detail_df.copy()
    # Only rows that contributed to Net Remain
    d = d[d["used_from_batch"].notna() & (d["used_from_batch"] > 0)]
    # Days-left metrics computed on rows that have non-null days_left
    d_valid = d[d["days_left"].notna()].copy()

    # Soonest, weighted average, latest days left
    # Weighted avg by used_from_batch
    if not d_valid.empty:
        # groupby computations
        grp = d_valid.groupby("itemid", as_index=False)
        soonest = grp["days_left"].min().rename(columns={"days_left":"soonest_days_left"})
        latest  = grp["days_left"].max().rename(columns={"days_left":"latest_days_left"})
        wavg    = grp.apply(lambda g: (g["days_left"]*g["used_from_batch"]).sum()/g["used_from_batch"].sum()) \
                    .reset_index().rename(columns={0:"avg_days_left"})
        stats = soonest.merge(latest, on="itemid", how="outer").merge(wavg, on="itemid", how="outer")
    else:
        stats = pd.DataFrame(columns=["itemid","soonest_days_left","latest_days_left","avg_days_left"])

    # Count units within threshold (≤ near_days) among allocated batches
    within = d[(d["days_left"].notna()) & (d["days_left"] <= near_days)].groupby("itemid", as_index=False)["used_from_batch"].sum()
    within = within.rename(columns={"used_from_batch": "units_within_threshold"})
    stats = stats.merge(within, on="itemid", how="left") if stats is not None else within
else:
    stats = pd.DataFrame(columns=["itemid","soonest_days_left","latest_days_left","avg_days_left","units_within_threshold"])

# Merge stats into quantities
out = quant_df.copy() if not quant_df.empty else pd.DataFrame()
if not out.empty:
    out = out.merge(stats, on="itemid", how="left")
    # Ensure display columns exist
    for col in ["name","barcode","recv_qty","rtn_def_qty","sales_qty","sale_return_qty","final_qty",
                "soonest_days_left","avg_days_left","latest_days_left","units_within_threshold"]:
        if col not in out.columns:
            out[col] = None

    # Friendly table
    days_col = f"Units ≤ {near_days}d"
    table = out.rename(columns={
        "name": "Item Name",
        "barcode": "Barcode",
        "recv_qty": "Total Inv Qty",
        "rtn_def_qty": "Returned in Inv",
        "sales_qty": "Sold Qty",
        "sale_return_qty": "Sale-Returned Qty",
        "final_qty": "Net Remain",
        "soonest_days_left": "Soonest Days Left",
        "avg_days_left": "Avg Days Left",
        "latest_days_left": "Latest Days Left",
        "units_within_threshold": days_col
    })[["Item Name","Barcode","Total Inv Qty","Returned in Inv","Sold Qty","Sale-Returned Qty","Net Remain",
         "Soonest Days Left","Avg Days Left","Latest Days Left",days_col]]

    # Sort: items expiring sooner first, then highest risk (more units ≤ X)
    if "Soonest Days Left" in table.columns:
        table = table.sort_values(by=["Soonest Days Left", days_col, "Net Remain"],
                                  ascending=[True, False, False], na_position="last")

    # KPIs
    total_items_near = int((table[days_col].fillna(0) > 0).sum())
    total_units_near = int(table[days_col].fillna(0).sum())

    c1, c2 = st.columns(2)
    c1.metric("Items near expiry", f"{total_items_near}")
    c2.metric(f"Units near expiry (≤ {near_days}d)", f"{total_units_near}")

    st.markdown("### Items near expiry and days left")
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    st.success("🎉 No positive remaining stock to evaluate.")
