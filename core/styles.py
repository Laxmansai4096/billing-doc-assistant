CUSTOM_CSS = """
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    .stApp {
        background: #f8fafc;
    }

    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }

    .app-header {
        padding: 1.3rem 1.5rem;
        border-radius: 14px;
        background: linear-gradient(135deg, #1e293b 0%, #2563eb 100%);
        color: #ffffff;
        margin-bottom: 1.2rem;
        border: 1px solid rgba(37, 99, 235, 0.15);
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.08);
    }
    .app-header h1 {
        font-size: 1.6rem;
        margin: 0 0 0.35rem 0;
        font-weight: 700;
        color: #ffffff !important;
    }
    .app-header p {
        margin: 0;
        color: #e0e7ff;
        font-size: 0.95rem;
        line-height: 1.5;
        max-width: 1100px;
    }

    .section-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.2rem;
        box-shadow: 0 4px 15px rgba(15, 23, 42, 0.02);
        margin-bottom: 1rem;
    }

    .upload-card {
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.04), rgba(99, 102, 241, 0.04));
        border: 1px solid rgba(59, 130, 246, 0.16);
        border-radius: 12px;
        padding: 0.9rem 1rem;
        margin-bottom: 0.8rem;
    }
    .upload-card .title {
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.25rem;
    }
    .upload-card .subtitle {
        color: #475569;
        font-size: 0.9rem;
        line-height: 1.45;
    }

    .insight-panel {
        border-left: 3px solid #3b82f6;
        padding: 0.95rem 1rem;
        border-radius: 0 10px 10px 0;
        background: #f1f5f9;
        margin-bottom: 1rem;
    }
    .insight-panel h2, .insight-panel h3 {
        color: #0f172a;
        margin-top: 0;
    }
    .insight-panel p, .insight-panel li {
        color: #334155;
        line-height: 1.55;
    }

    .metric-card {
        background: rgba(79, 70, 229, 0.05);
        border: 1px solid rgba(79, 70, 229, 0.15);
        border-radius: 10px;
        padding: 0.9rem 1.1rem;
    }

    .category-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        background: rgba(79, 70, 229, 0.08);
        color: #4f46e5;
        margin-right: 8px;
        letter-spacing: 0.01em;
    }

    .status-match {
        color: #10b981;
        font-weight: 700;
    }
    .status-mismatch {
        color: #ef4444;
        font-weight: 700;
    }
    .status-missing {
        color: #f59e0b;
        font-weight: 700;
    }

    .page-link-btn button {
        padding: 0.16rem 0.65rem !important;
        font-size: 0.76rem !important;
        border-radius: 999px !important;
        min-height: 0 !important;
        margin: 0px !important;
        background: #ffffff !important;
        color: #4f46e5 !important;
        border: 1px solid #e2e8f0 !important;
    }
    .page-link-btn button:hover {
        background: #f1f5f9 !important;
        border-color: #cbd5e1 !important;
    }

    .summary-card {
        border-left: 3px solid #3b82f6;
        padding: 0.85rem 1rem;
        margin-bottom: 0.6rem;
        background: #ffffff;
        border-top: 1px solid #e2e8f0;
        border-right: 1px solid #e2e8f0;
        border-bottom: 1px solid #e2e8f0;
        border-radius: 0 10px 10px 0;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.015);
    }

    .summary-text {
        flex: 1 1 auto;
        color: #0f172a;
        font-size: 0.95rem;
        line-height: 1.48;
        word-break: break-word;
    }

    .summary-links {
        display: flex;
        gap: 0.35rem;
        align-items: center;
        justify-content: flex-end;
        flex: 0 0 auto;
        white-space: nowrap;
    }

    .stTabs [data-baseweb="tab-list"] { gap: 8px; }

    /* Executive brief cards styling (Light Theme) */
    .overview-card {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.02) 0%, rgba(99, 102, 241, 0.02) 100%);
        border: 1px solid rgba(37, 99, 235, 0.12);
        border-left: 4px solid #2563eb;
        border-radius: 12px;
        padding: 1.4rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.02);
        transition: border-color 0.2s, box-shadow 0.2s;
    }
    .overview-card:hover {
        border-color: rgba(37, 99, 235, 0.25);
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.04);
    }
    .brief-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 15px rgba(15, 23, 42, 0.02);
        transition: border-color 0.2s, box-shadow 0.2s;
    }
    .brief-card:hover {
        border-color: rgba(79, 70, 229, 0.35);
        box-shadow: 0 6px 20px rgba(15, 23, 42, 0.04);
    }
    .brief-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.85rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #f1f5f9;
    }
    .brief-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0 !important;
    }
    .brief-list {
        margin: 0;
        padding-left: 1.2rem;
    }
    .brief-list li {
        color: #334155;
        font-size: 0.92rem;
        line-height: 1.5;
        margin-bottom: 0.6rem;
    }
    .brief-list li:last-child {
        margin-bottom: 0;
    }
    
    /* Inline page pill citations */
    .page-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 1px 7px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        background: rgba(79, 70, 229, 0.08);
        color: #4f46e5;
        border: 1px solid rgba(79, 70, 229, 0.25);
        text-decoration: none;
        margin-left: 6px;
        cursor: pointer;
        transition: all 0.15s ease-in-out;
        vertical-align: middle;
    }
    .page-pill:hover {
        background: rgba(79, 70, 229, 0.16);
        color: #4338ca;
        border-color: rgba(79, 70, 229, 0.5);
        text-decoration: none;
        box-shadow: 0 0 6px rgba(79, 70, 229, 0.15);
    }

    /* Add distinct borders and shadows to all DataFrames */
    div.stDataFrame {
        border: 1px solid #e2e8f0 !important;
        border-radius: 8px !important;
        background-color: #ffffff !important;
        padding: 4px !important;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04) !important;
    }

    /* Custom styling for Streamlit container blocks with border=True */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 12px !important;
        padding: 1.25rem !important;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03) !important;
        margin-bottom: 1.2rem !important;
    }
</style>
"""
