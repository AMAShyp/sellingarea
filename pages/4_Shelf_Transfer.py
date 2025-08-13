import streamlit as st
import pandas as pd
from db_handler import DatabaseManager

# ================== CONFIG: Filtered locids from CSV ==================
LOCID_CSV_PATH = "assets/locid_list.csv"
locid_df = pd.read_csv(LOCID_CSV_PATH)
FILTERED_LOCIDS = sorted(set(str(l).strip() for l in locid_df["locid"].dropna().unique()))

# ================== DATA LAYER (shelfentries-only) ==================
class ShelfTransferHandler(DatabaseManager):
    def get_all_locids(self):
        return FILTERED_LOCIDS

    def get_shelf_items(self, locid: str) -> pd.DataFrame:
        """
        Compute live quantities per item at a given shelf location
        by summing history from shelfentries using ONLY trx_type mapping:

          + STOCKTAKE, RECEIVE, TRANSFER-TO
          - RETURN, TRANSFER-FROM, DEFECT

        We also tolerate common variants like with spaces/underscores.
        """
        q = """
        WITH norm AS (
          SELECT
            se.itemid,
            se.locid,
            se.quantity::numeric AS qty,
            UPPER(TRIM(se.trx_type)) AS t
          FROM shelfentries se
          WHERE se.locid = %s
        ),
        signed AS (
          SELECT
            itemid,
            locid,
            CASE
              -- POSITIVE
              WHEN t IN ('STOCKTAKE','RECEIVE','TRANSFER-TO','TRANSFER TO','TRANSFER_TO') THEN +qty
              -- NEGATIVE
              WHEN t IN ('RETURN','TRANSFER-FROM','TRANSFER FROM','TRANSFER_FROM','DEFECT') THEN -qty
              ELSE 0
            END AS signed_qty
          FROM norm
        )
        SELECT
          s.locid,
          i.itemid,
          i.itemnameenglish AS name,
          i.barcode,
          SUM(s.signed_qty)::numeric AS quantity
        FROM signed s
        JOIN item i ON i.itemid = s.itemid
        GROUP BY s.locid, i.itemid, i.itemnameenglish, i.barcode
        HAVING SUM(s.signed_qty) > 0
        ORDER BY i.itemnameenglish;
        """
        df = self.fetch_data(q, (locid,))
        return df if not df.empty else pd.DataFrame(columns=["locid", "itemid", "name", "barcode", "quantity"])

    def transfer_pair(self, itemid: int, source_locid: str, target_locid: str, qty: int, note: str = "shelf transfer"):
        """
        Insert two shelfentries rows for a shelf-to-shelf transfer:
          1) source_locid with trx_type='TRANSFER-FROM' (negative)
          2) target_locid with trx_type='TRANSFER-TO'   (positive)

        We set expirationdate = CURRENT_DATE to satisfy NOT NULL.
        entryid/created_at/createdby/entrydate rely on table defaults.
        """
        # FROM (outflow on source)
        self.execute_command(
            """
            INSERT INTO shelfentries
              (itemid, quantity, expirationdate, locid, trx_type, note, reference_type)
            VALUES
              (%s, %s, CURRENT_DATE, %s, 'TRANSFER-FROM', %s, 'SHELF_TRANSFER');
            """,
            (int(itemid), int(qty), str(source_locid), note)
        )

        # TO (inflow on target)
        self.execute_command(
            """
            INSERT INTO shelfentries
              (itemid, quantity, expirationdate, locid, trx_type, note, reference_type)
            VALUES
              (%s, %s, CURRENT_DATE, %s, 'TRANSFER-TO', %s, 'SHELF_TRANSFER');
            """,
            (int(itemid), int(qty), str(target_locid), note)
        )

# ================== UI ==================
st.set_page_config(layout="wide")
st.title("🔄 Shelf ➔ Shelf Transfers (append-only via shelfentries)")

handler = ShelfTransferHandler()
all_locids = handler.get_all_locids()

if len(all_locids) < 2:
    st.warning("At least two shelf locations are required to transfer.")
    st.stop()

colA, colB = st.columns(2)
with colA:
    source_locid = st.selectbox(
        "Select Source Shelf Location (locid):",
        options=all_locids,
        index=0,
        key="s2s_source"
    )
with colB:
    target_locid_options = [l for l in all_locids if l != source_locid]
    target_locid = st.selectbox(
        "Select Target Shelf Location (locid):",
        options=target_locid_options,
        index=0,
        key="s2s_target"
    )

source_items = handler.get_shelf_items(source_locid)

if source_items.empty:
    st.info(f"No items currently available on shelf `{source_locid}` (derived from shelfentries).")
else:
    st.markdown(f"### Transfer from `{source_locid}` to `{target_locid}`")

    transfer_dict = {}
    transfer_table = []
    for _, row in source_items.iterrows():
        itemid = int(row["itemid"])
        name = row["name"]
        barcode = row["barcode"]
        shelf_qty = int(row["quantity"])
        col1, col2, col3, col4 = st.columns([2.6, 1.6, 1.6, 1.2])
        with col1:
            st.markdown(
                f"**{name}**<br><span style='color:#bbb;font-size:0.92em'>Barcode:</span> "
                f"<span style='font-family:monospace;font-size:1em'>{barcode}</span>",
                unsafe_allow_html=True
            )
        with col2:
            st.markdown(f"<b>Available at source:</b> {shelf_qty}", unsafe_allow_html=True)
        with col3:
            qty_to_transfer = st.number_input(
                "Transfer Qty",
                min_value=0,
                max_value=shelf_qty,
                value=0,
                step=1,
                key=f"s2s_{source_locid}_{target_locid}_{itemid}"
            )
        transfer_dict[itemid] = (name, barcode, shelf_qty, int(qty_to_transfer))
        transfer_table.append({
            "Item Name": name,
            "Barcode": barcode,
            "Available at Source": shelf_qty,
            "Transfer Qty": int(qty_to_transfer)
        })

    st.markdown("#### Transfer preview")
    preview_df = pd.DataFrame([t for t in transfer_table if t["Transfer Qty"] > 0])
    if not preview_df.empty:
        st.dataframe(preview_df, hide_index=True, use_container_width=True)
    else:
        st.info("No items selected for transfer yet.")

    note = st.text_input("Note (optional)", value="shelf transfer", help="Will be saved to shelfentries.note")

    if st.button("🚚 Execute Transfer", type="primary", key="s2s_exec"):
        any_transferred = False
        errors = []

        for itemid, (name, barcode, shelf_qty, qty_to_transfer) in transfer_dict.items():
            if qty_to_transfer > 0 and qty_to_transfer <= shelf_qty:
                try:
                    handler.transfer_pair(
                        itemid=itemid,
                        source_locid=source_locid,
                        target_locid=target_locid,
                        qty=qty_to_transfer,
                        note=note.strip() or "shelf transfer"
                    )
                    any_transferred = True
                except Exception as e:
                    errors.append(f"{name} ({barcode}): {e}")

        if any_transferred and not errors:
            st.success("Transfer recorded (two shelfentries rows per item).")
        elif any_transferred and errors:
            st.warning("Transfer partially recorded. Some items failed:")
            for err in errors:
                st.write(f"- {err}")
        else:
            st.info("No items selected for transfer or invalid quantities.")

        st.rerun()

st.markdown(
    "<div style='margin-top:2em;color:#888;font-size:0.95em'>"
    "This page writes only to <b>shelfentries</b>. Each transfer inserts two rows: "
    "<code>TRANSFER-FROM</code> at the source shelf and <code>TRANSFER-TO</code> at the target shelf. "
    "Quantities shown are derived from the full shelfentries history using trx_type signs only.</div>",
    unsafe_allow_html=True
)
