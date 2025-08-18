import os
import uuid
import pandas as pd
import psycopg2
from psycopg2 import OperationalError
import streamlit as st

# ───────────────────────────────────────────────────────────────
# 1) One cached connection per user session
# ───────────────────────────────────────────────────────────────
def _session_key() -> str:
    """Return a unique key for the current user session."""
    if "_session_key" not in st.session_state:
        st.session_state["_session_key"] = uuid.uuid4().hex
    return st.session_state["_session_key"]


@st.cache_resource(show_spinner=False)
def get_conn(dsn: str, key: str):
    """
    Create (once per session) and return a PostgreSQL connection.
    Adds TCP keepalives to survive brief network hiccups.
    """
    conn = psycopg2.connect(
        dsn,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    try:
        st.on_session_end(conn.close)
    except Exception:
        pass
    return conn

# ───────────────────────────────────────────────────────────────
# 2) Database manager with auto-reconnect logic
# ───────────────────────────────────────────────────────────────
class DatabaseManager:
    """General DB interactions using a cached connection."""

    def __init__(self):
        # Prefer env var override; fallback to Streamlit secrets.
        self.dsn  = os.getenv("DATABASE_URL", st.secrets["neon"]["dsn"])
        self._key = _session_key()
        self.conn = get_conn(self.dsn, self._key)  # reuse within this session

    # ────────── internal helpers ──────────
    def _ensure_live_conn(self):
        """
        Ensure we have a live connection:
          - If closed → reconnect
          - Else, ping with SELECT 1; on failure → reconnect
        """
        # psycopg2: .closed == 0 means open; >0 means closed
        if getattr(self.conn, "closed", 1) != 0:
            get_conn.clear()
            self.conn = get_conn(self.dsn, self._key)
            return

        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
        except OperationalError:
            # connection dropped; rebuild the cached resource
            get_conn.clear()
            self.conn = get_conn(self.dsn, self._key)

    def _fetch_df(self, query: str, params=None) -> pd.DataFrame:
        self._ensure_live_conn()
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                rows = cur.fetchall()
                cols = [c[0] for c in cur.description]
        except OperationalError:
            # transient conn issue → reconnect once and retry
            get_conn.clear()
            self.conn = get_conn(self.dsn, self._key)
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                rows = cur.fetchall()
                cols = [c[0] for c in cur.description]
        except Exception:
            self.conn.rollback()  # recover from broken transaction
            raise
        return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame()

    def _execute(self, query: str, params=None, returning=False):
        self._ensure_live_conn()
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                res = cur.fetchone() if returning else None
            self.conn.commit()
            return res
        except OperationalError:
            # transient conn issue → reconnect once and retry
            get_conn.clear()
            self.conn = get_conn(self.dsn, self._key)
            with self.conn.cursor() as cur:
                cur.execute(query, params or ())
                res = cur.fetchone() if returning else None
            self.conn.commit()
            return res
        except Exception:
            self.conn.rollback()  # reset failed transaction
            raise

    # ────────── public API ──────────
    def fetch_data(self, query, params=None):
        return self._fetch_df(query, params)

    def execute_command(self, query, params=None):
        self._execute(query, params)

    def execute_command_returning(self, query, params=None):
        return self._execute(query, params, returning=True)

    # ─────────── Dropdown Management ───────────
    def get_all_sections(self):
        df = self.fetch_data("SELECT DISTINCT section FROM dropdowns")
        return df["section"].tolist()

    def get_dropdown_values(self, section):
        q = "SELECT value FROM dropdowns WHERE section = %s"
        df = self.fetch_data(q, (section,))
        return df["value"].tolist()

    # ─────────── Supplier Management ───────────
    def get_suppliers(self):
        return self.fetch_data(
            "SELECT supplierid, suppliername FROM supplier"
        )

    # ─────────── Inventory Management ───────────
    def add_inventory(self, data: dict):
        cols = ", ".join(data.keys())
        ph   = ", ".join(["%s"] * len(data))
        q = f"INSERT INTO inventory ({cols}) VALUES ({ph})"
        self.execute_command(q, list(data.values()))

    # ─────────── Foreign-key checks ───────────
    def check_foreign_key_references(self, referenced_table: str, referenced_column: str, value) -> list[str]:
        """
        Return a list of tables that still reference the given value
        through a FOREIGN KEY constraint.
        Empty list → safe to delete.
        """
        fk_sql = """
            SELECT tc.table_schema,
                   tc.table_name
            FROM   information_schema.table_constraints AS tc
            JOIN   information_schema.key_column_usage AS kcu
                   ON tc.constraint_name = kcu.constraint_name
            JOIN   information_schema.constraint_column_usage AS ccu
                   ON ccu.constraint_name = tc.constraint_name
            WHERE  tc.constraint_type = 'FOREIGN KEY'
              AND  ccu.table_name      = %s
              AND  ccu.column_name     = %s;
        """
        fks = self.fetch_data(fk_sql, (referenced_table, referenced_column))

        conflicts: list[str] = []
        for _, row in fks.iterrows():
            schema = row["table_schema"]
            table  = row["table_name"]

            exists_sql = f"""
                SELECT EXISTS(
                    SELECT 1
                    FROM   {schema}.{table}
                    WHERE  {referenced_column} = %s
                );
            """
            exists = self.fetch_data(exists_sql, (value,)).iat[0, 0]
            if exists:
                conflicts.append(f"{schema}.{table}")

        return sorted(set(conflicts))
