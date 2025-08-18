# pages/4_DB_Tables.py
import streamlit as st
import pandas as pd
from db_handler import DatabaseManager

st.set_page_config(page_title="DB Tables Browser", layout="wide")
st.title("📚 Database Tables Browser")

# ───────────────────────────────────────────────────────────────
# Setup
# ───────────────────────────────────────────────────────────────
db = DatabaseManager()

@st.cache_data(show_spinner=False, ttl=60)
def load_tables(include_views: bool) -> pd.DataFrame:
    """Return list of tables (and optionally views) from information_schema."""
    if include_views:
        q = """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """
    else:
        q = """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
        """
    return db.fetch_data(q)

@st.cache_data(show_spinner=True, ttl=30)
def get_row_count(schema: str, table: str) -> int:
    """Count rows in a table (can be slow on large tables)."""
    # Safe: schema and table names come from the catalog; not user-typed.
    df = db.fetch_data(f'SELECT COUNT(*) AS c FROM "{schema}"."{table}"')
    return int(df["c"].iat[0]) if not df.empty else 0

@st.cache_data(show_spinner=False, ttl=60)
def get_columns(schema: str, table: str) -> pd.DataFrame:
    """Column definitions for a table."""
    q = """
        SELECT
            ordinal_position,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    return db.fetch_data(q, (schema, table))

@st.cache_data(show_spinner=True, ttl=30)
def preview_table(schema: str, table: str, limit: int) -> pd.DataFrame:
    """Preview first N rows from a table."""
    return db.fetch_data(f'SELECT * FROM "{schema}"."{table}" LIMIT {int(limit)}')

# ───────────────────────────────────────────────────────────────
# Controls
# ───────────────────────────────────────────────────────────────
colA, colB, colC, colD = st.columns([1, 1, 1, 1.2])

with colA:
    include_views = st.toggle("Include views", value=False, help="Also list views alongside tables.")

with colB:
    with_counts = st.toggle("Show row counts (slow)", value=False, help="Runs COUNT(*) per table. Can be slow on big tables.")

with colC:
    default_limit = st.number_input("Preview rows", min_value=5, max_value=1000, step=5, value=50)

with colD:
    st.caption("Search filters")
    name_filter = st.text_input("Table name contains", placeholder="e.g. sales", label_visibility="collapsed")

# ───────────────────────────────────────────────────────────────
# Table list
# ───────────────────────────────────────────────────────────────
tables_df = load_tables(include_views)
schemas = sorted(tables_df["table_schema"].unique().tolist())
schema_pick = st.multiselect("Schemas", options=schemas, default=schemas)

filtered = tables_df[tables_df["table_schema"].isin(schema_pick)].copy()
if name_filter:
    nf = name_filter.lower()
    filtered = filtered[filtered["table_name"].str.lower().str.contains(nf)]

if with_counts and not filtered.empty:
    st.info("Counting rows… This may take a moment on large tables.", icon="⏳")
    counts = []
    for _, r in filtered.iterrows():
        try:
            counts.append(get_row_count(r["table_schema"], r["table_name"]))
        except Exception as e:
            counts.append(None)
    filtered.insert(2, "row_count", counts)

st.subheader("Objects")
st.dataframe(
    filtered.reset_index(drop=True),
    use_container_width=True,
    hide_index=True,
)

# ───────────────────────────────────────────────────────────────
# Selection + details
# ───────────────────────────────────────────────────────────────
st.divider()
st.subheader("Inspect a table / view")

# Build selection list like: public.salesitems
choices = [f'{s}.{t}' for s, t in zip(filtered["table_schema"], filtered["table_name"])]
selection = st.selectbox("Pick a table", options=choices if choices else ["— none —"])

if choices:
    schema, table = selection.split(".", 1)

    cols1, cols2 = st.columns([1, 3])
    with cols1:
        if st.button("🔄 Refresh metadata", use_container_width=True):
            load_tables.clear()
            get_columns.clear()
            get_row_count.clear()
            preview_table.clear()
            st.experimental_rerun()

        show_cols = st.checkbox("Show columns", value=True)
        do_preview = st.checkbox("Preview data", value=True)
        limit = st.number_input("Limit", min_value=1, max_value=5000, value=int(default_limit), step=10)

        if with_counts:
            try:
                rc = get_row_count(schema, table)
                st.metric("Row count", f"{rc:,}")
            except Exception as e:
                st.warning(f"Row count failed: {e}")

    with cols2:
        tabs = st.tabs(["Columns", "Preview", "SQL"])
        with tabs[0]:
            if show_cols:
                try:
                    cols_df = get_columns(schema, table)
                    st.dataframe(cols_df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Failed to load columns: {e}")

        with tabs[1]:
            if do_preview:
                try:
                    data_df = preview_table(schema, table, limit)
                    st.dataframe(data_df, use_container_width=True)
                    st.download_button(
                        "⬇️ Download CSV",
                        data=data_df.to_csv(index=False).encode("utf-8"),
                        file_name=f"{schema}.{table}.csv",
                        mime="text/csv",
                    )
                except Exception as e:
                    st.error(f"Preview failed: {e}")

        with tabs[2]:
            st.code(f'SELECT * FROM "{schema}"."{table}" LIMIT {int(limit)};', language="sql")

else:
    st.info("No tables to show with the current filters.")
