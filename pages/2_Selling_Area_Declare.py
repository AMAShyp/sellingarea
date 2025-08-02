import streamlit as st
import pandas as pd
import datetime
from PO.po_handler import POHandler

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

st.set_page_config(page_title="Manual Purchase Orders", layout="wide")
po_handler = POHandler()
BARCODE_COLUMN = "barcode"

def manual_po_page():
    st.header("📝 Manual Purchase Orders – Add Items")

    if "po_items" not in st.session_state:
        st.session_state["po_items"] = []
    if "po_feedback" not in st.session_state:
        st.session_state["po_feedback"] = ""
    if "latest_po_results" not in st.session_state:
        st.session_state["latest_po_results"] = []

    items_df = po_handler.fetch_data("SELECT * FROM item")
    mapping_df = po_handler.get_item_supplier_mapping()
    suppliers_df = po_handler.get_suppliers()

    if BARCODE_COLUMN not in items_df.columns:
        st.error(f"'{BARCODE_COLUMN}' column NOT FOUND in your item table!")
        st.stop()

    barcode_to_item = {
        str(row[BARCODE_COLUMN]).strip(): row
        for _, row in items_df.iterrows()
        if pd.notnull(row[BARCODE_COLUMN]) and str(row[BARCODE_COLUMN]).strip()
    }

    if st.session_state["po_feedback"]:
        st.success(st.session_state["po_feedback"])
        st.session_state["po_feedback"] = ""

    tab1, tab2 = st.tabs(["📷 Camera Scan", "⌨️ Type Barcode"])

    def get_suppliers_for_item(item_id):
        mappings = mapping_df[mapping_df["itemid"] == item_id]
        return [
            (int(m["supplierid"]), suppliers_df[suppliers_df["supplierid"] == int(m["supplierid"])]["suppliername"].values[0])
            for _, m in mappings.iterrows()
            if not suppliers_df[suppliers_df["supplierid"] == int(m["supplierid"])].empty
        ]

    def add_item_by_barcode(barcode):
        code = str(barcode).strip()
        if not code:
            return
        found_row = barcode_to_item.get(code, None)
        if found_row is None and code.lstrip('0') != code:
            found_row = barcode_to_item.get(code.lstrip('0'), None)
        if found_row is None:
            st.warning(f"Barcode '{code}' not found.")
            return
        item_id = int(found_row["itemid"])
        # Skip if already added (by item+supplier)
        if not any(po["item_id"] == item_id for po in st.session_state["po_items"]):
            supplier_options = get_suppliers_for_item(item_id)
            if not supplier_options:
                st.warning(f"No supplier found for item '{found_row['itemnameenglish']}'.")
                return
            supplierid, suppliername = supplier_options[0]
            st.session_state["po_items"].append({
                "item_id": item_id,
                "itemname": found_row["itemnameenglish"],
                "barcode": code,
                "quantity": 1,
                "estimated_price": 0.0,
                "supplierid": supplierid,
                "suppliername": suppliername,
                "supplier_options": supplier_options,
                "supplier_select_idx": 0,
                "classcat": found_row.get("classcat", ""),
                "departmentcat": found_row.get("departmentcat", ""),
                "sectioncat": found_row.get("sectioncat", ""),
                "familycat": found_row.get("familycat", ""),
            })
            st.success(f"Added: {found_row['itemnameenglish']}")
            st.rerun()
        else:
            st.info(f"Item '{found_row['itemnameenglish']}' already added.")

    with tab1:
        st.markdown("**Scan barcode with your webcam**")
        barcode_camera = ""
        if QR_AVAILABLE:
            barcode_camera = qrcode_scanner(key="barcode_camera") or ""
            if barcode_camera:
                add_item_by_barcode(barcode_camera)
        else:
            st.warning("Camera barcode scanning requires `streamlit-qrcode-scanner`. Please install it or use the next tab.")

    with tab2:
        st.markdown("**Or enter barcode manually**")
        with st.form("add_barcode_form", clear_on_submit=True):
            bc_col1, bc_col2 = st.columns([5,1])
            barcode_in = bc_col1.text_input(
                "Scan/Enter Barcode",
                value="",
                label_visibility="visible",
                autocomplete="off",
                key="barcode_input"
            )
            add_click = bc_col2.form_submit_button("Add Item")
            if add_click and barcode_in:
                add_item_by_barcode(barcode_in)

    # --- Card-style items panel ---
    st.write("### Current Items")
    po_items = st.session_state["po_items"]
    if not po_items:
        st.info("No items added yet. Scan a barcode to begin.")
    else:
        to_remove = []
        for idx, po in enumerate(po_items):
            card = st.container()
            with card:
                # Card header: name and barcode
                st.markdown(
                    f"<div style='font-size:18px;font-weight:700;color:#174e89;margin-bottom:2px;'>🛒 {po['itemname']}</div>"
                    f"<div style='font-size:14px;color:#086b37;margin-bottom:3px;'>Barcode: <code>{po['barcode']}</code></div>",
                    unsafe_allow_html=True,
                )
                tags = [
                    f"<span style='background:#fff3e0;color:#C61C1C;border-radius:7px;padding:3px 12px 3px 12px;font-size:13.5px;margin-right:6px;'><b>Class:</b> {po.get('classcat','')}</span>",
                    f"<span style='background:#e3f2fd;color:#004CBB;border-radius:7px;padding:3px 12px;font-size:13.5px;margin-right:6px;'><b>Department:</b> {po.get('departmentcat','')}</span>",
                    f"<span style='background:#eafaf1;color:#098A23;border-radius:7px;padding:3px 12px;font-size:13.5px;margin-right:6px;'><b>Section:</b> {po.get('sectioncat','')}</span>",
                    f"<span style='background:#fff8e1;color:#FF8800;border-radius:7px;padding:3px 12px;font-size:13.5px;'><b>Family:</b> {po.get('familycat','')}</span>",
                ]
                st.markdown(f"<div style='margin-bottom:4px;'>{''.join(tags)}</div>", unsafe_allow_html=True)
                # Edit controls row
                c1, c2, c3, c4, c5 = st.columns([2,2,2,2,1])
                qty = c1.number_input("Qty", min_value=1, value=po["quantity"], step=1, key=f"qty_{idx}")
                price = c2.number_input("Est. Price", min_value=0.0, value=po["estimated_price"], step=0.01, key=f"price_{idx}")

                # --- Supplier picker ---
                supplier_options = po.get("supplier_options", [])
                supplier_names = [n for _, n in supplier_options] if supplier_options else [po["suppliername"]]
                current_idx = po.get("supplier_select_idx", 0)
                supplier_idx = c3.selectbox(
                    "Supplier", supplier_names, index=current_idx, key=f"sup_{idx}"
                )
                # When supplier changed, update supplierid/name in state
                if supplier_idx != current_idx:
                    sel_supplierid, sel_suppliername = supplier_options[supplier_idx]
                    po["supplierid"] = sel_supplierid
                    po["suppliername"] = sel_suppliername
                    po["supplier_select_idx"] = supplier_idx

                c4.markdown(f"**Current:** {po['suppliername']}")
                remove = c5.button("Remove", key=f"rm_{idx}")
                po["quantity"] = qty
                po["estimated_price"] = price
                if remove:
                    to_remove.append(idx)
                st.markdown("---")
        if to_remove:
            for idx in reversed(to_remove):
                st.session_state["po_items"].pop(idx)
            st.rerun()

    # --- Delivery date/time ---
    st.write("### 📅 Delivery Info")
    date_col, time_col = st.columns(2)
    delivery_date = date_col.date_input("Delivery Date", value=datetime.date.today(), min_value=datetime.date.today())
    delivery_time = time_col.time_input("Delivery Time", value=datetime.time(9,0))

    # --- Generate POs button ---
    if st.button("🧾 Generate Purchase Orders"):
        if not po_items:
            st.error("Please add at least one item before generating purchase orders.")
        else:
            po_by_supplier = {}
            for po in po_items:
                supid = po["supplierid"]
                if supid not in po_by_supplier:
                    po_by_supplier[supid] = {
                        "suppliername": po["suppliername"],
                        "items": []
                    }
                po_by_supplier[supid]["items"].append({
                    "item_id": po["item_id"],
                    "quantity": po["quantity"],
                    "estimated_price": po["estimated_price"] if po["estimated_price"] > 0 else None,
                    "itemname": po["itemname"],
                    "barcode": po["barcode"],
                })
            expected_dt = datetime.datetime.combine(delivery_date, delivery_time)
            created_by = st.session_state.get("user_email", "ManualUser")
            results = []
            any_success = False
            for supid, supinfo in po_by_supplier.items():
                try:
                    poid = po_handler.create_manual_po(
                        supid, expected_dt, supinfo["items"], created_by)
                    results.append((supid, supinfo["suppliername"], poid, supinfo["items"]))
                    any_success = True
                except Exception as e:
                    results.append((supid, supinfo["suppliername"], None, supinfo["items"]))
            if any_success:
                st.session_state["po_feedback"] = "✅ Purchase Orders generated successfully!"
            else:
                st.session_state["po_feedback"] = "❌ Failed to generate any purchase order."
            st.session_state["po_items"] = []
            st.session_state["latest_po_results"] = results
            st.rerun()

    results = st.session_state["latest_po_results"]
    st.header("📄 Generated Purchase Orders")
    if not results:
        st.info("No purchase orders generated yet.")
    else:
        for supid, supname, poid, items in results:
            with st.expander(f"Supplier: {supname} (PO ID: {poid if poid else 'FAILED'})"):
                for po in items:
                    row = f"🛒 **{po['itemname']}**  \nBarcode: `{po['barcode']}`  \nQty: {po['quantity']}  \nEst. Price: {po['estimated_price'] if po['estimated_price'] else 'N/A'}"
                    st.markdown(row)
                st.markdown("---")

manual_po_page()
