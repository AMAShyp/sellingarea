# selling_area/shelf_handler.py
from __future__ import annotations

from typing import Optional, Iterable
import pandas as pd

from db_handler import DatabaseManager
from pg8000.exceptions import DatabaseError


SCHEMA = "sellingarea"


class ShelfHandler(DatabaseManager):
    """Handles database operations related to the Shelf (Selling Area)."""

    # ───────────────────────── internal helpers ─────────────────────────
    def _safe_fetch(self, sql: str, params: Optional[Iterable] = None, *, empty_cols: Optional[list[str]] = None) -> pd.DataFrame:
        """
        Fetch helper that returns an empty DataFrame on permission errors (SQLSTATE 42501),
        so the UI doesn't crash while DB grants are being fixed.
        """
        try:
            return self.fetch_data(sql, params)
        except DatabaseError as e:
            if getattr(e, "sqlstate", None) == "42501":  # insufficient_privilege
                return pd.DataFrame(columns=empty_cols or [])
            raise

    def _safe_execute(self, sql: str, params: Optional[Iterable] = None) -> None:
        """
        Execute helper that silently ignores permission errors for non-critical writes
        (e.g., logging to shelfentries). Critical writes are performed via explicit
        try/except in the calling method if needed.
        """
        try:
            self.execute_command(sql, params)
        except DatabaseError as e:
            if getattr(e, "sqlstate", None) == "42501":
                # swallow only for non-critical side effects (callers decide)
                return
            raise

    # ───────────────────────── shelf queries ─────────────────────────
    def get_shelf_items(self) -> pd.DataFrame:
        sql = f"""
            SELECT 
                s.shelfid,
                s.itemid,
                i.itemnameenglish AS itemname,
                s.quantity,
                s.expirationdate,
                s.cost_per_unit,
                s.lastupdated,
                s.locid
            FROM   {SCHEMA}.shelf s
            JOIN   {SCHEMA}.item  i ON s.itemid = i.itemid
            ORDER  BY s.locid, i.itemnameenglish, s.expirationdate;
        """
        empty = ["shelfid", "itemid", "itemname", "quantity", "expirationdate", "cost_per_unit", "lastupdated", "locid"]
        return self._safe_fetch(sql, empty_cols=empty)

    # ─────────────────────── add / update shelf (single call) ──────────────────
    def add_to_shelf(
        self,
        itemid: int,
        expirationdate,
        quantity: int,
        created_by: str,
        cost_per_unit: float,
        locid: Optional[str] = None,
        cur=None,  # optional open cursor for transaction use
    ) -> None:
        """
        Upserts into Shelf and logs to ShelfEntries.
        If `cur` is supplied, uses that cursor (no commit); otherwise opens its own cursor/commit.
        NOTE: For the UPSERT to work, ensure a unique constraint on (itemid, expirationdate, cost_per_unit, locid):
              ALTER TABLE sellingarea.shelf
              ADD CONSTRAINT shelf_unique_layer UNIQUE (itemid, expirationdate, cost_per_unit, locid);
        """
        itemid_py   = int(itemid)
        qty_py      = int(quantity)
        cost_py     = float(cost_per_unit)

        own_cursor = False
        if cur is None:
            self._ensure_live_conn()
            cur = self.conn.cursor()
            own_cursor = True

        try:
            # Upsert shelf row (unique on item+expiry+cost+locid)
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.shelf (itemid, expirationdate, quantity, cost_per_unit, locid)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (itemid, expirationdate, cost_per_unit, locid)
                DO UPDATE SET quantity    = {SCHEMA}.shelf.quantity + EXCLUDED.quantity,
                              lastupdated = CURRENT_TIMESTAMP;
                """,
                (itemid_py, expirationdate, qty_py, cost_py, locid),
            )

            # Movement log (best-effort; ignore permission issues on shelfentries)
            try:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.shelfentries (itemid, expirationdate, quantity, createdby, locid)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (itemid_py, expirationdate, qty_py, created_by, locid),
                )
            except DatabaseError as e:
                if getattr(e, "sqlstate", None) != "42501":
                    # non-permission DB errors should bubble up
                    raise
                # If no INSERT privilege on shelfentries, we skip logging but keep the shelf update.

            if own_cursor:
                self.conn.commit()
        finally:
            if own_cursor:
                try:
                    cur.close()
                except Exception:
                    pass

    # ───────────────────── inventory look-ups ───────────────────────
    def get_inventory_items(self) -> pd.DataFrame:
        sql = f"""
            SELECT 
                inv.itemid,
                i.itemnameenglish AS itemname,
                inv.quantity,
                inv.expirationdate,
                inv.storagelocation,
                inv.cost_per_unit
            FROM   {SCHEMA}.inventory inv
            JOIN   {SCHEMA}.item       i ON inv.itemid = i.itemid
            WHERE  inv.quantity > 0
            ORDER  BY i.itemnameenglish, inv.expirationdate;
        """
        empty = ["itemid", "itemname", "quantity", "expirationdate", "storagelocation", "cost_per_unit"]
        return self._safe_fetch(sql, empty_cols=empty)

    # ───────────────────── fast transfer from inventory ─────────────
    def transfer_from_inventory(
        self,
        itemid: int,
        expirationdate,
        quantity: int,
        cost_per_unit: float,
        created_by: str,
        locid: Optional[str] = None,
    ) -> None:
        """
        Moves a specific cost layer (item + expiry + cost) from Inventory → Shelf in ONE transaction (one commit).
        Validates available quantity to prevent negative balances.
        """
        itemid_py   = int(itemid)
        qty_py      = int(quantity)
        cost_py     = float(cost_per_unit)

        self._ensure_live_conn()

        # single atomic block
        with self.conn:
            with self.conn.cursor() as cur:
                # Validate enough inventory exists for the exact layer
                cur.execute(
                    f"""
                    SELECT quantity
                    FROM   {SCHEMA}.inventory
                    WHERE  itemid = %s
                      AND  expirationdate = %s
                      AND  cost_per_unit = %s
                    FOR UPDATE;
                    """,
                    (itemid_py, expirationdate, cost_py),
                )
                row = cur.fetchone()
                current_qty = int(row[0]) if row else 0
                if current_qty < qty_py:
                    raise ValueError("Not enough inventory available for the requested layer transfer.")

                # Decrement that exact layer in inventory
                cur.execute(
                    f"""
                    UPDATE {SCHEMA}.inventory
                    SET    quantity = quantity - %s
                    WHERE  itemid = %s
                      AND  expirationdate = %s
                      AND  cost_per_unit  = %s
                      AND  quantity >= %s;
                    """,
                    (qty_py, itemid_py, expirationdate, cost_py, qty_py),
                )
                if cur.rowcount == 0:
                    # Shouldn't happen due to the check above, but guard anyway
                    raise ValueError("Inventory update failed (concurrent change or insufficient quantity).")

                # Upsert into shelf + log entry (reusing same cursor/transaction)
                self.add_to_shelf(
                    itemid_py,
                    expirationdate,
                    qty_py,
                    created_by,
                    cost_py,
                    locid,
                    cur=cur,
                )

    # ───────────────────── alerts / misc helpers ────────────────────
    def get_low_shelf_stock(self, threshold: int = 10) -> pd.DataFrame:
        sql = f"""
            SELECT 
                s.itemid,
                i.itemnameenglish AS itemname,
                s.quantity,
                s.expirationdate,
                s.locid
            FROM   {SCHEMA}.shelf s
            JOIN   {SCHEMA}.item  i ON s.itemid = i.itemid
            WHERE  s.quantity <= %s
            ORDER  BY s.locid, s.quantity ASC;
        """
        empty = ["itemid", "itemname", "quantity", "expirationdate", "locid"]
        return self._safe_fetch(sql, (int(threshold),), empty_cols=empty)

    def get_inventory_by_barcode(self, barcode: str) -> pd.DataFrame:
        sql = f"""
            SELECT 
                inv.itemid,
                i.itemnameenglish AS itemname,
                inv.quantity,
                inv.expirationdate,
                inv.cost_per_unit,
                inv.storagelocation
            FROM   {SCHEMA}.inventory inv
            JOIN   {SCHEMA}.item       i ON inv.itemid = i.itemid
            WHERE  i.barcode = %s AND inv.quantity > 0
            ORDER  BY inv.expirationdate;
        """
        empty = ["itemid", "itemname", "quantity", "expirationdate", "cost_per_unit", "storagelocation"]
        return self._safe_fetch(sql, (barcode,), empty_cols=empty)

    # -------------- item master helpers -----------------
    def get_all_items(self) -> pd.DataFrame:
        sql = f"""
            SELECT 
                itemid,
                itemnameenglish AS itemname,
                shelfthreshold,
                shelfaverage
            FROM {SCHEMA}.item
            ORDER BY itemnameenglish;
        """
        df = self._safe_fetch(sql, empty_cols=["itemid", "itemname", "shelfthreshold", "shelfaverage"])
        if not df.empty:
            df["shelfthreshold"] = df["shelfthreshold"].astype("Int64")
            df["shelfaverage"]   = df["shelfaverage"].astype("Int64")
        return df

    def update_shelf_settings(self, itemid: int, new_threshold: int, new_average: int) -> None:
        sql = f"""
            UPDATE {SCHEMA}.item
            SET    shelfthreshold = %s,
                   shelfaverage   = %s
            WHERE  itemid = %s;
        """
        self._safe_execute(sql, (int(new_threshold), int(new_average), int(itemid)))

    def get_shelf_quantity_by_item(self) -> pd.DataFrame:
        sql = f"""
            SELECT 
                i.itemid,
                i.itemnameenglish AS itemname,
                COALESCE(SUM(s.quantity), 0) AS totalquantity,
                i.shelfthreshold,
                i.shelfaverage
            FROM   {SCHEMA}.item  i
            LEFT JOIN {SCHEMA}.shelf s ON i.itemid = s.itemid
            GROUP  BY i.itemid, i.itemnameenglish, i.shelfthreshold, i.shelfaverage
            ORDER  BY i.itemnameenglish;
        """
        df = self._safe_fetch(
            sql,
            empty_cols=["itemid", "itemname", "totalquantity", "shelfthreshold", "shelfaverage"],
        )
        if not df.empty:
            df["shelfthreshold"] = df["shelfthreshold"].astype("Int64")
            df["shelfaverage"]   = df["shelfaverage"].astype("Int64")
            df["totalquantity"]  = df["totalquantity"].astype(int)
        return df

    # ───────── shortage resolver (transfer side) ─────────
    def resolve_shortages(self, *, itemid: int, qty_need: int, user: str) -> int:
        """
        Consume open shortages for this itemid (oldest first).
        Returns the qty still left to put on shelf.
        """
        rows = self._safe_fetch(
            f"""
            SELECT shortageid, shortage_qty
            FROM   {SCHEMA}.shelf_shortage
            WHERE  itemid = %s AND resolved = FALSE
            ORDER  BY logged_at
            """,
            (int(itemid),),
            empty_cols=["shortageid", "shortage_qty"],
        )

        remaining = int(qty_need)
        for r in rows.itertuples():
            if remaining == 0:
                break
            take = min(remaining, int(r.shortage_qty))

            # shrink or resolve the shortage row
            self._safe_execute(
                f"""
                UPDATE {SCHEMA}.shelf_shortage
                SET    shortage_qty = shortage_qty - %s,
                       resolved      = (shortage_qty - %s = 0),
                       resolved_qty  = COALESCE(resolved_qty,0) + %s,
                       resolved_at   = CASE
                                         WHEN shortage_qty - %s = 0
                                         THEN CURRENT_TIMESTAMP
                                       END,
                       resolved_by   = %s
                WHERE  shortageid = %s
                """,
                (take, take, take, take, user, r.shortageid),
            )
            remaining -= take

        # optional tidy-up of zero rows
        self._safe_execute(f"DELETE FROM {SCHEMA}.shelf_shortage WHERE shortage_qty = 0;")

        return remaining
