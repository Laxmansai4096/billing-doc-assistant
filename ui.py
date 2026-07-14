import os
import re
import tempfile
from io import BytesIO

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core import storage
from core.analyzer import analyze_document
from core.styles import CUSTOM_CSS
from core.viewer import pdf_iframe_html, pdf_open_new_tab_link, find_page_block


def run_ui():
    load_dotenv()

    st.set_page_config(
        page_title="Project Billing Intelligence",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


    # ---------------------------------------------------------------------------
    # Session state
    # ---------------------------------------------------------------------------

    defaults = {
        "active_doc_id": None,
        "active_view": None,       # None | "summary" | "account"
        "viewer_open": False,
        "viewer_page_label": None,
        "viewer_page_num": 1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # --- Query parameters handling ---
    if any(k in st.query_params for k in ["view_page", "view_label", "doc_id", "view"]):
        try:
            val_doc_id = st.query_params.get("doc_id")
            val_view = st.query_params.get("view")
            val_label = st.query_params.get("view_label")
            val_page = st.query_params.get("view_page")
            
            if val_doc_id:
                st.session_state.active_doc_id = val_doc_id
            if val_view:
                st.session_state.active_view = val_view
            if val_label:
                st.session_state.viewer_page_label = val_label
            if val_page:
                st.session_state.viewer_page_num = int(val_page)
            st.session_state.viewer_open = True
            # Clear query params so reloading/refreshing doesn't re-trigger
            st.query_params.clear()
        except Exception:
            pass


    def parse_executive_summary(text: str) -> dict:
        sections = {}
        parts = re.split(r"^##\s*", text, flags=re.MULTILINE)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n")
            title = lines[0].strip().rstrip(":").strip()
            content_lines = lines[1:]
            
            is_paragraph_section = "overview" in title.lower() or "main idea" in title.lower()
            if is_paragraph_section:
                sections[title] = "\n".join(content_lines).strip()
            else:
                bullets = []
                for line in content_lines:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    line_clean = re.sub(r"^[-*+]\s*|^\d+\.\s*", "", line_str).strip()
                    if line_clean:
                        bullets.append(line_clean)
                if title:
                    sections[title] = bullets
                    
        standard_keys = ["Document Overview", "Key Commercial Terms", "Legal, Risk & Obligations", "Important Dates & Milestones"]
        normalized_sections = {}
        
        for key in standard_keys:
            found_key = None
            for k in list(sections.keys()):
                if key.lower() in k.lower() or k.lower() in key.lower():
                    found_key = k
                    break
            if found_key:
                normalized_sections[key] = sections.pop(found_key)
            else:
                if key == "Document Overview":
                    normalized_sections[key] = ""
                else:
                    normalized_sections[key] = []
                    
        # Backward compatibility for old "Executive Summary" key
        for k in list(sections.keys()):
            if "executive summary" in k.lower():
                val = sections.pop(k)
                if isinstance(val, list):
                    normalized_sections["Document Overview"] = " ".join(val)
                else:
                    normalized_sections["Document Overview"] = str(val)
                    
        for k, v in sections.items():
            normalized_sections[k] = v
            
        has_content = False
        if normalized_sections.get("Document Overview"):
            has_content = True
        else:
            for k, v in normalized_sections.items():
                if k != "Document Overview" and len(v) > 0:
                    has_content = True
                    break
                    
        if not has_content and text.strip():
            clean_text = text.strip()
            normalized_sections["Document Overview"] = clean_text
            
        return normalized_sections


    def select_document(record_id: str):
        st.session_state.active_doc_id = record_id
        st.session_state.active_view = None
        st.session_state.viewer_open = False


    def open_viewer(label: str, page_num: int = None):
        st.session_state.viewer_page_label = label
        if page_num:
            st.session_state.viewer_page_num = page_num
        st.session_state.viewer_open = True


    def run_analysis(record_id: str, filename: str, left_container):
        path = storage.get_file_path(record_id)
        with left_container:
            progress_bar = st.progress(0.0, text="Starting analysis...")

        def progress_cb(frac, msg):
            progress_bar.progress(min(frac, 1.0), text=msg)

        try:
            result = analyze_document(path, filename, progress_cb=progress_cb)
            storage.mark_analyzed(record_id, result)
            progress_bar.empty()
            return result
        except Exception as e:
            progress_bar.empty()
            st.error(f"Analysis failed: {e}")
            return None


    # ---------------------------------------------------------------------------
    # Header
    # ---------------------------------------------------------------------------

    st.markdown(
        """
        <div class="app-header">
            <h1>📊 Project Billing Intelligence</h1>
            <p>Upload a project contract / billing document to get an executive summary,
            a full billing breakdown, and an automatic ledger reconciliation — every fact linked back to its source page.
            Every document you upload is saved so you can come back to it anytime.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    api_key_present = bool(os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"))
    model_name = os.getenv("CHAT_MODEL", "gpt-4o-mini")


    # ---------------------------------------------------------------------------
    # Two-pane layout
    # ---------------------------------------------------------------------------

    left, right = st.columns([1, 2.3], gap="large")


    # =====================================================================
    # LEFT PANE — upload, document library, view selector
    # =====================================================================

    with left:
        st.subheader("📁 Documents")

        if api_key_present:
            st.caption(f"✅ Model ready · `{model_name}`")
        else:
            st.error("No API key found. Set AZURE_OPENAI_API_KEY / OPENAI_API_KEY in your .env file.")

        st.markdown("**Upload New Document**")
        st.markdown(
            """
            <div class="upload-card">
                <div class="title">Document intake</div>
                <div class="subtitle">Upload PDFs, Word files, or other text-based documents. They are converted into a PDF-friendly workflow before analysis so the review remains consistent and polished.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "PDF, DOCX, DOC, TXT, or other text-based files",
            type=["pdf", "docx", "doc", "pptx", "ppt", "xls", "xlsx", "odt", "rtf", "txt"],
            label_visibility="collapsed",
            key="uploader",
        )

        if uploaded_file is not None:
            if st.button("🚀 Add & Analyze", type="primary", use_container_width=True, disabled=not api_key_present):
                file_bytes = uploaded_file.read()
                record = storage.add_or_get_record(file_bytes, uploaded_file.name)

                if record["analyzed"]:
                    st.info(f"'{uploaded_file.name}' was already uploaded before — loading the saved analysis.")
                    select_document(record["id"])
                else:
                    progress_slot = st.container()
                    result = run_analysis(record["id"], uploaded_file.name, progress_slot)
                    if result is not None:
                        select_document(record["id"])
                st.rerun()

        st.divider()
        st.markdown("**🗂️ Previously Uploaded**")

        library = storage.list_library()
        if not library:
            st.caption("No documents uploaded yet.")
        else:
            for record in library:
                row = st.columns([5, 1])
                is_active = st.session_state.active_doc_id == record["id"]
                badge = "✅" if record.get("analyzed") else "⏳"
                label = f"{'👉 ' if is_active else ''}{badge} {record['filename']}"
                with row[0]:
                    if st.button(label, key=f"select_{record['id']}", use_container_width=True):
                        select_document(record['id'])
                        if not record.get("analyzed"):
                            result = run_analysis(record['id'], record['filename'], st.container())
                        st.rerun()
                with row[1]:
                    if st.button("✕", key=f"delete_{record['id']}", help="Remove from library"):
                        storage.delete_record(record['id'])
                        if st.session_state.active_doc_id == record['id']:
                            for k in defaults:
                                st.session_state[k] = defaults[k]
                        st.rerun()
                st.caption(record["uploaded_at"].replace("T", " "))

        st.divider()
        st.markdown("**🔍 View**")

        has_active_doc = st.session_state.active_doc_id is not None
        active_record = storage.get_record(st.session_state.active_doc_id) if has_active_doc else None
        is_ready = has_active_doc and active_record and active_record.get("analyzed")

        view_cols = st.columns(2)
        with view_cols[0]:
            if st.button("📋 Summary", use_container_width=True, disabled=not is_ready,
                         type="primary" if st.session_state.active_view == "summary" else "secondary"):
                st.session_state.active_view = "summary"
                st.session_state.viewer_open = False
                st.rerun()
        with view_cols[1]:
            if st.button("💰 Accounts", use_container_width=True, disabled=not is_ready,
                         type="primary" if st.session_state.active_view == "account" else "secondary"):
                st.session_state.active_view = "account"
                st.session_state.viewer_open = False
                st.rerun()

        if not is_ready and has_active_doc:
            st.caption("This document hasn't finished analyzing yet.")


    # =====================================================================
    # RIGHT PANE — instructions / summary / accounts
    # =====================================================================

    with right:

        analysis = None
        if st.session_state.active_doc_id and is_ready:
            analysis = storage.load_analysis(st.session_state.active_doc_id)

        doc_type = active_record["doc_type"] if active_record else None
        pdf_bytes = storage.get_file_bytes(st.session_state.active_doc_id) if (doc_type == "pdf" and analysis) else None

        def page_link_button(label: str, key: str, page_num: int = None):
            st.markdown('<div class="page-link-btn">', unsafe_allow_html=True)
            if st.button(f"🔗 {label}", key=key):
                open_viewer(label, page_num)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        def render_viewer_panel():
            with st.expander("📖 Document Viewer", expanded=True):
                close_cols = st.columns([5, 1])
                with close_cols[1]:
                    if st.button("✕ Close", key="close_viewer"):
                        st.session_state.viewer_open = False
                        st.rerun()

                if doc_type == "pdf" and pdf_bytes:
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        page_num = st.number_input(
                            "Go to page", min_value=1, value=st.session_state.viewer_page_num or 1, step=1,
                            key="page_num_input",
                        )
                        if st.button("Go", use_container_width=True, key="go_page_btn"):
                            st.session_state.viewer_page_num = int(page_num)
                            st.rerun()
                        st.markdown(
                            pdf_open_new_tab_link(pdf_bytes, st.session_state.viewer_page_num, "Open in new tab"),
                            unsafe_allow_html=True,
                        )
                        st.caption("Page jump works best in Chrome / Edge with the built-in PDF viewer.")
                    with col_b:
                        st.markdown(pdf_iframe_html(pdf_bytes, st.session_state.viewer_page_num), unsafe_allow_html=True)
                else:
                    st.info("This is a DOCX file, which has no fixed page layout — showing the extracted text for the selected section instead.")
                    labels = [p.label for p in analysis.pages]
                    default_idx = labels.index(st.session_state.viewer_page_label) if st.session_state.viewer_page_label in labels else 0
                    selected_label = st.selectbox("Section", labels, index=default_idx, key="docx_section_select")
                    page_block = find_page_block(analysis.pages, selected_label)
                    if page_block:
                        st.text_area("Extracted content", page_block.text, height=400, key="docx_section_text")

        # -------------------------------------------------------------
        # No view selected yet -> instructions
        # -------------------------------------------------------------
        if st.session_state.active_view is None:
            if has_active_doc and active_record:
                st.success(f"**{active_record['filename']}** is ready. Choose what you'd like to see:")
            st.markdown(
                """
                ### 👋 Getting started

                1. **Upload New Document** (left) — pick a PDF or DOCX project billing file and click
                   **🚀 Add & Analyze**. It only needs to be analyzed once; it's saved to your library automatically.
                2. **Previously Uploaded** (left) — click any past document to reload it instantly, no
                   re-analysis needed. Use **✕** to remove one you no longer need.
                3. **📋 Summary** — every important term, obligation, deadline, and risk from the document,
                   each tagged with the exact page it came from, with a one-click link to jump straight to that page.
                4. **💰 Accounts** — every billing line item (Human Resources, Cloud, UI/UX, Full Stack
                   Engineering, etc.) found anywhere in the document, plus the final ledger telling you
                   whether the numbers actually add up to the total stated in the file.

                Select or upload a document, then click **Summary** or **Accounts** above to begin.
                """
            )

        # -------------------------------------------------------------
        # Summary view
        # -------------------------------------------------------------
        elif st.session_state.active_view == "summary" and analysis:
            if st.session_state.viewer_open:
                render_viewer_panel()

            st.subheader(f"📋 Executive Brief — {analysis.filename}")

            if analysis.warnings:
                with st.expander(f"⚠️ {len(analysis.warnings)} warning(s)", expanded=False):
                    for w in analysis.warnings:
                        st.warning(w)

            brief_sections = parse_executive_summary(analysis.executive_summary)
            overview_text = brief_sections.get("Document Overview", "")

            if overview_text:
                st.markdown(f"""
                <div class="overview-card">
                    <div class="brief-header">
                        <span style="font-size: 1.25rem;">ℹ️</span>
                        <h5 class="brief-title">Document Overview & Main Idea</h5>
                    </div>
                    <div style="font-size: 0.98rem; color: #334155; line-height: 1.6;">
                        {overview_text}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            has_legal = len(brief_sections.get("Legal, Risk & Obligations", [])) > 0
            has_comm = len(brief_sections.get("Key Commercial Terms", [])) > 0
            has_dates = len(brief_sections.get("Important Dates & Milestones", [])) > 0

            if has_legal or has_comm or has_dates:
                col1, col2 = st.columns(2, gap="medium")
                
                with col1:
                    bullets_comm = brief_sections.get("Key Commercial Terms", [])
                    bullets_comm_html = "".join(f"<li>{b}</li>" for b in bullets_comm) or "<li>No details extracted.</li>"
                    st.markdown(f"""
                    <div class="brief-card">
                        <div class="brief-header">
                            <span style="font-size: 1.25rem;">💼</span>
                            <h5 class="brief-title">Key Commercial Terms</h5>
                        </div>
                        <ul class="brief-list">
                            {bullets_comm_html}
                        </ul>
                    </div>
                    """, unsafe_allow_html=True)

                with col2:
                    bullets_legal = brief_sections.get("Legal, Risk & Obligations", [])
                    bullets_legal_html = "".join(f"<li>{b}</li>" for b in bullets_legal) or "<li>No details extracted.</li>"
                    st.markdown(f"""
                    <div class="brief-card">
                        <div class="brief-header">
                            <span style="font-size: 1.25rem;">🛡️</span>
                            <h5 class="brief-title">Legal, Risk & Obligations</h5>
                        </div>
                        <ul class="brief-list">
                            {bullets_legal_html}
                        </ul>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    bullets_dates = brief_sections.get("Important Dates & Milestones", [])
                    bullets_dates_html = "".join(f"<li>{b}</li>" for b in bullets_dates) or "<li>No details extracted.</li>"
                    st.markdown(f"""
                    <div class="brief-card">
                        <div class="brief-header">
                            <span style="font-size: 1.25rem;">📅</span>
                            <h5 class="brief-title">Timeline & Milestones</h5>
                        </div>
                        <ul class="brief-list">
                            {bullets_dates_html}
                        </ul>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown(f"#### Key Highlights ({len(analysis.summary_points)})")
            
            # Replace category filter with a search input
            search_query = st.text_input("🔍 Search Key Highlights", placeholder="Type keywords to filter highlights (e.g. rate, date, liability)...")
            search_clean = search_query.strip().lower()
            
            if search_clean:
                filtered = [
                    sp for sp in analysis.summary_points
                    if search_clean in sp.point.lower() or search_clean in sp.category.lower()
                ]
            else:
                filtered = analysis.summary_points

            if not filtered:
                st.caption("No key highlights match your search query.")
            else:
                # Group highlights by category
                from collections import defaultdict
                grouped_highlights = defaultdict(list)
                for sp in filtered:
                    grouped_highlights[sp.category].append(sp)
                
                doc_id = st.session_state.active_doc_id
                active_view = st.session_state.active_view
                
                for cat in sorted(grouped_highlights.keys()):
                    st.markdown(f'<div style="margin-top: 1.2rem; margin-bottom: 0.6rem; font-weight: 700; font-size: 1rem; color: #1e3a8a;">📁 {cat}</div>', unsafe_allow_html=True)
                    for sp in grouped_highlights[cat]:
                        pills = []
                        for page_label in sp.pages:
                            page_block = find_page_block(analysis.pages, page_label)
                            page_num = page_block.page_number if page_block else None
                            if page_num:
                                pills.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_page={page_num}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                            else:
                                pills.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                        pills_html = "".join(pills)
                        
                        st.markdown(
                            f'<div class="summary-card"><div class="summary-text">{sp.point}{pills_html}</div></div>',
                            unsafe_allow_html=True,
                        )

        # -------------------------------------------------------------
        # Accounts view (billing + final ledger, combined)
        # -------------------------------------------------------------
        elif st.session_state.active_view == "account" and analysis:
            if st.session_state.viewer_open:
                render_viewer_panel()

            st.subheader(f"💰 Accounts & Billing — {analysis.filename}")

            st.markdown("#### Final Total")
            if not analysis.reconciliations:
                st.info("No billing amounts or stated totals were found to reconcile.")
            else:
                for rec in analysis.reconciliations:
                    cols = st.columns([1, 1.2, 1.2, 1, 1.4])
                    cols[0].markdown(f"**Currency**\n\n{rec.currency}")
                    cols[1].markdown(f"**Computed Total**\n\n{rec.computed_total:,.2f}")
                    if rec.stated_total_amount is not None:
                        cols[2].markdown(f"**Total in Document** ({rec.stated_total_label})\n\n{rec.stated_total_amount:,.2f}")
                        cols[3].markdown(f"**Difference**\n\n{rec.difference:,.2f}")
                    else:
                        cols[2].markdown("**Total in Document**\n\n—")
                        cols[3].markdown("**Difference**\n\n—")
                    status_class = {
                        "Match": "status-match", "Mismatch": "status-mismatch",
                        "No stated total found": "status-missing",
                    }.get(rec.status, "")
                    icon = {"Match": "✅", "Mismatch": "❌", "No stated total found": "⚠️"}.get(rec.status, "")
                    cols[4].markdown(f'**Status**\n\n<span class="{status_class}">{icon} {rec.status}</span>', unsafe_allow_html=True)
                st.divider()

            st.markdown(f"#### Billing Line Items ({len(analysis.billing_items)})")
            if not analysis.billing_items:
                st.info("No billing line items with numeric amounts were detected in this document.")
            else:
                df = pd.DataFrame([bi.to_dict() for bi in analysis.billing_items]).rename(columns={
                    "heading": "Heading", "description": "Description", "quantity": "Qty",
                    "unit_price": "Unit Price", "amount": "Amount", "currency": "Currency", "page": "Page",
                })
                headings = sorted(df["Heading"].unique())

                doc_id = st.session_state.active_doc_id
                active_view = st.session_state.active_view

                def render_billing_group(heading_name: str):
                    df_grp = df[df["Heading"] == heading_name]
                    if df_grp.empty:
                        return
                    with st.container(border=True):
                        grp_pages = sorted(list(set(df_grp["Page"].unique())))
                        grp_pills = []
                        for page_label in grp_pages:
                            page_block = find_page_block(analysis.pages, page_label)
                            page_num = page_block.page_number if page_block else None
                            if page_num:
                                grp_pills.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_page={page_num}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                            else:
                                grp_pills.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                        grp_pills_html = "".join(grp_pills)
                        
                        st.markdown(f'<div style="margin-bottom: 0.8rem;"><strong>📦 {heading_name}</strong> <span style="margin-left: 10px;">{grp_pills_html}</span></div>', unsafe_allow_html=True)
                        st.dataframe(
                            df_grp[["Description", "Qty", "Unit Price", "Amount", "Currency", "Page"]],
                            use_container_width=True, hide_index=True,
                            column_config={
                                "Amount": st.column_config.NumberColumn(format="%.2f"),
                                "Unit Price": st.column_config.NumberColumn(format="%.2f"),
                            },
                        )

                tab_titles = ["📋 All Categories"] + [f"📦 {h}" for h in headings]
                heading_tabs = st.tabs(tab_titles)
                
                with heading_tabs[0]:
                    for heading in headings:
                        render_billing_group(heading)
                        
                for idx, heading in enumerate(headings):
                    with heading_tabs[idx + 1]:
                        render_billing_group(heading)

                st.markdown("##### Subtotals by Heading")
                cat_df = pd.DataFrame([r.to_dict() for r in analysis.category_rows]).rename(columns={
                    "heading": "Heading", "currency": "Currency", "computed_total": "Total", "item_count": "# Items",
                })
                if not cat_df.empty:
                    st.dataframe(cat_df[["Heading", "Currency", "Total", "# Items"]], use_container_width=True,
                                 hide_index=True, column_config={"Total": st.column_config.NumberColumn(format="%.2f")})

            if analysis.stated_totals:
                st.markdown("##### All Stated Totals Found in Document")
                st_df = pd.DataFrame([s.to_dict() for s in analysis.stated_totals]).rename(columns={
                    "label": "Label", "amount": "Amount", "currency": "Currency", "page": "Page",
                })
                st.dataframe(st_df[["Label", "Amount", "Currency", "Page"]], use_container_width=True, hide_index=True,
                             column_config={"Amount": st.column_config.NumberColumn(format="%.2f")})
                unique_total_pages = sorted(list(set(s.page for s in analysis.stated_totals)))
                pills_totals = []
                doc_id = st.session_state.active_doc_id
                active_view = st.session_state.active_view
                for page_label in unique_total_pages:
                    page_block = find_page_block(analysis.pages, page_label)
                    page_num = page_block.page_number if page_block else None
                    if page_num:
                        pills_totals.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_page={page_num}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                    else:
                        pills_totals.append(f'<a href="?doc_id={doc_id}&view={active_view}&view_label={page_label}" class="page-pill" target="_self">📄 {page_label}</a>')
                pills_totals_html = "".join(pills_totals)
                st.markdown(f'<div style="margin-top: 0.6rem; margin-bottom: 1.5rem; font-size: 0.95rem;"><strong>Source Pages:</strong> {pills_totals_html}</div>', unsafe_allow_html=True)

            if analysis.billing_items or analysis.reconciliations:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    if analysis.billing_items:
                        pd.DataFrame([bi.to_dict() for bi in analysis.billing_items]).to_excel(writer, sheet_name="Billing Items", index=False)
                    if analysis.category_rows:
                        pd.DataFrame([r.to_dict() for r in analysis.category_rows]).to_excel(writer, sheet_name="Subtotals", index=False)
                    if analysis.reconciliations:
                        pd.DataFrame([r.to_dict() for r in analysis.reconciliations]).to_excel(writer, sheet_name="Reconciliation", index=False)
                    if analysis.stated_totals:
                        pd.DataFrame([s.to_dict() for s in analysis.stated_totals]).to_excel(writer, sheet_name="Stated Totals", index=False)
                st.download_button(
                    "⬇️ Download Accounts & Ledger (Excel)", data=buffer.getvalue(),
                    file_name=f"{analysis.filename}_accounts.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


if __name__ == "__main__":
    run_ui()
