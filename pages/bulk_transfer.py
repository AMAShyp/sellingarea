# ── selling_area/bulk_transfer.py ────────────────────────────────────
"""
Bulk shelf-transfer tab (multi-item, CSV/XLSX upload).
"""

from __future__ import annotations
import re
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from selling_area.transfer import BarcodeShelfHandler

# ───────────────────────── config ────────────────────────────────────
KEY_PFX   = "bt_"
BATCH_KEY = KEY_PFX + "batch"
handler   = BarcodeShelfHandler()

HIDDEN = "·"                         # 1-char label placeholder

# ───────────────────────── helpers ───────────────────────────────────
def norm_bc(val: str) -> str:
    txt = str(val).replace("\u00A0", " ").strip()
    if re.fullmatch(r"\d+\.\d+E\+\d+", txt, flags=re.I):
        txt = f"{int(float(txt))}"
    if txt.endswith(".0"):
        txt = txt[:-2]
    return txt

# 🟢 helper for uniform exp-string
def exp_str(val) -> str:
    """'2026-07-16' <- date | timestamp | str with time."""
    return str(val).split(" ")[0]

# cache barcode→layers with clean date strings
@st.cache_data(ttl=60, show_spinner=False)
def layers_for_barcode(bc: str) -> List[Dict[str, Any]]:
    df = handler.get_layers(bc)
    if df.empty:
        return []
    df["expirationdate"] = df["expirationdate"].map(exp_str)   # 🟢
    return df.to_dict("records")

@st.cache_data(ttl=300, show_spinner=False)
def all_locids() -> List[str]:
    df = handler.fetch_data("SELECT locid FROM shelf_map_locations ORDER BY locid")
    return df["locid"].tolist() if not df.empty else []

# ───────────────────────── table utilities ───────────────────────────
def _k(i: int, name: str) -> str: return f"{KEY_PFX}{name}_{i}"

def _init_row(i: int) -> None:
    for k, d in {_k(i, "bc"):"", _k(i,"name"):"", _k(i,"exp"):"",
                _k(i,"qty"):1, _k(i,"loc"):"", _k(i,"layers"):[], _k(i,"prev"):""}\
            .items():
        st.session_state.setdefault(k, d)

@st.fragment
def rows_fragment(n: int) -> None:
    if KEY_PFX+"css" not in st.session_state:
        st.markdown(
            "<style>div[data-testid='stHorizontalBlock']{margin-bottom:2px}"
            "div[data-testid='column']>div:first-child{padding:1px 0}</style>",
            unsafe_allow_html=True)
        st.session_state[KEY_PFX+"css"] = True

    hdr = st.columns(5, gap="small")
    for c,t in zip(hdr,
        ["**Barcode**","**Item&nbsp;Name**","**Expiration**","**Qty**","**Location**"]):
        c.markdown(t,unsafe_allow_html=True)

    loc_opts = all_locids()

    for i in range(n):
        _init_row(i)
        cols = st.columns(5, gap="small")

        bc_raw = cols[0].text_input(HIDDEN, key=_k(i,"bc"),
                                    label_visibility="collapsed")
        bc_val = norm_bc(bc_raw)

        if bc_val and bc_val!=st.session_state[_k(i,"prev")]:
            lays = layers_for_barcode(bc_val)
            st.session_state[_k(i,"layers")] = lays
            st.session_state[_k(i,"name")]   = lays[0]["itemname"] if lays else ""
            st.session_state[_k(i,"exp")]    = ""
            if lays and st.session_state[_k(i,"loc")] == "":
                last = handler.last_locid(lays[0]["itemid"])
                st.session_state[_k(i,"loc")] = last or ""
            st.session_state[_k(i,"prev")] = bc_val

        cols[1].text_input(HIDDEN, key=_k(i,"name"), disabled=True,
                           label_visibility="collapsed")

        layers = st.session_state[_k(i,"layers")]
        exp_opts = [f"{l['expirationdate']} (Qty {l['qty']})" for l in layers]
        exp_sel  = cols[2].selectbox(HIDDEN, [""]+exp_opts, key=_k(i,"exp"),
                                     label_visibility="collapsed")
        exp_date = exp_sel.split(" ")[0] if exp_sel else ""
        avail    = sum(l["qty"] for l in layers if l["expirationdate"]==exp_date)

        cols[3].number_input(HIDDEN, key=_k(i,"qty"),
                             min_value=1, max_value=max(avail,1),
                             value=min(1,avail) or 1, step=1,
                             label_visibility="collapsed")

        cur_loc = st.session_state[_k(i,"loc")]
        choices = [""]+loc_opts if cur_loc=="" else loc_opts
        cols[4].selectbox(HIDDEN, choices, key=_k(i,"loc"),
                          label_visibility="collapsed")

def _validate_rows(n: int):
    errors,batch=[],[]
    for i in range(n):
        bc  = norm_bc(st.session_state[_k(i,"bc")])
        exp = st.session_state[_k(i,"exp")].split(" ")[0].strip()
        qty = int(st.session_state[_k(i,"qty")])
        loc = st.session_state[_k(i,"loc")].strip()
        lays= st.session_state[_k(i,"layers")]

        if not bc:  errors.append(f"Line {i+1}: barcode missing."); continue
        if not exp: errors.append(f"Line {i+1}: expiration missing.");continue
        if not loc: errors.append(f"Line {i+1}: location missing.");  continue

        sel  = [l for l in lays if l["expirationdate"]==exp]         # 🟢
        stock= sum(l["qty"] for l in sel)
        if qty>stock: errors.append(f"Line {i+1}: only {stock} available.");continue
        batch.append({"itemid":sel[0]["itemid"],"need":qty,
                      "loc":loc,"layers":sel})
    return errors,batch

# ───────────────────────── PAGE MAIN ─────────────────────────────────
def bulk_transfer_tab() -> None:
    st.session_state.setdefault(BATCH_KEY, [])
    st.subheader("📤 Bulk Transfer to Shelves")

    n_rows = st.number_input("Rows to transfer",1,50,1,1,key=_k(0,"nrows"))
    rows_fragment(n_rows)

    if st.button("Add table rows to batch", key=_k(0,"add_table")):
        errs,jobs=_validate_rows(n_rows)
        if errs: [st.error(e) for e in errs]
        else:
            st.session_state[BATCH_KEY].extend(jobs)
            st.success(f"✅ Added {len(jobs)} job(s) to batch."); st.rerun()

    # ------------- CSV / XLSX upload ---------------------------------
    st.markdown("---"); st.subheader("📑 Bulk upload (CSV or Excel)")
    tpl_cols=["barcode","expiration_date","quantity","location"]
    st.download_button("Download template CSV", ",".join(tpl_cols),
                       "bulk_transfer_template.csv", key=_k(0,"tpldl"))

    up=st.file_uploader("Upload filled template",type=["csv","xlsx"],key=_k(0,"upl"))
    if up and st.button("Parse file",key=_k(0,"parse")):
        df=(pd.read_excel(up,dtype=str) if up.name.lower().endswith("xlsx")
            else pd.read_csv(up,dtype=str))

        if (miss:=set(tpl_cols)-set(df.columns)):
            st.error(f"Template mismatch. Missing: {', '.join(miss)}"); st.stop()

        df["barcode"]        = df["barcode"].map(norm_bc)
        df["expiration_date"]= df["expiration_date"].astype(str).map(exp_str)  # 🟢
        df["location"]       = df["location"].astype(str).str.strip()
        df["quantity"]       = df["quantity"].astype(int)

        unique=df["barcode"].unique().tolist()
        bc2id={r.barcode:int(r.itemid)
               for r in handler.fetch_data(
                   "SELECT itemid, barcode FROM item WHERE barcode = ANY(%s)",
                   (unique,),).itertuples()}
        if (unk:=set(unique)-set(bc2id)):
            st.error(f"Unknown barcode(s): {', '.join(list(unk)[:5])}"); st.stop()

        bc2layers={bc:layers_for_barcode(bc) for bc in unique}
        jobs,errs=[],[]
        for idx,r in df.iterrows():
            bc,exp,qty,loc=r["barcode"],r["expiration_date"],r["quantity"],r["location"]
            lays=[l for l in bc2layers[bc] if l["expirationdate"]==exp]  # 🟢
            stock=sum(l["qty"] for l in lays)
            if not lays: errs.append(f"Row {idx+1}: expiration not found.")
            elif qty>stock: errs.append(f"Row {idx+1}: only {stock} available.")
            else: jobs.append({"itemid":bc2id[bc],"need":qty,
                               "loc":loc,"layers":lays})
        if errs: [st.error(e) for e in errs]; st.stop()

        if not jobs: st.info("No valid rows found.")
        else:
            st.session_state[BATCH_KEY].extend(jobs)
            st.dataframe(df)
            st.success(f"✅ Parsed {len(jobs)} job(s) into batch."); st.rerun()

    # ----------- review & commit ------------------------------------
    batch=st.session_state[BATCH_KEY]
    st.markdown(f"### Jobs in buffer: **{len(batch)}**")

    if batch and st.button("Proceed to confirmation",key=_k(0,"review")):
        st.session_state[KEY_PFX+"confirm"]=True; st.rerun()

    if st.session_state.get(KEY_PFX+"confirm"):
        st.markdown("### Confirm transfer")
        for j in batch:
            st.write(f"• Item **{j['itemid']}** | Qty {j['need']} → Shelf {j['loc']}")
        ok,cancel=st.columns(2)

        if ok.button("✅ Confirm",key=_k(0,"ok")):
            user=st.session_state.get("user_email","Unknown")
            for job in batch:
                remaining=handler.resolve_shortages(
                    itemid=job["itemid"],qty_need=job["need"],user=user)
                for layer in sorted(job["layers"], key=lambda l:l["cost"]):
                    if remaining==0: break
                    take=min(remaining,layer["qty"])
                    handler.move_layer(itemid=layer["itemid"],
                        expiration=layer["expirationdate"],qty=take,cost=layer["cost"],
                        locid=job["loc"],by=user)
                    remaining-=take
            st.success("✅ Transfer completed.")
            st.session_state[BATCH_KEY]=[]
            st.session_state.pop(KEY_PFX+"confirm",None)
            layers_for_barcode.clear(); st.rerun()

        if cancel.button("❌ Cancel",key=_k(0,"cancel")):
            st.session_state.pop(KEY_PFX+"confirm",None); st.rerun()


if __name__=="__main__":
    bulk_transfer_tab()
