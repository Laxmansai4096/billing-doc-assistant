================================================================================
                        PROJECT ARCHITECTURE DIAGRAM
================================================================================

    +-------------------+
    |   User Browser    |
    +---------+---------+
              |
              | Streamlit UI Interaction & State (app.py)
              v
    +-------------------+
    |    app.py         |<=======> [ Query Params Router ] (doc_id, view, page)
    +---------+---------+
              |
              | 1. Triggers run_analysis()
              v
    +-------------------+
    |  core/analyzer.py |<================================================+
    +---------+---------+                                                 |
              |                                                           |
              | 2. Converts & Extracts Layout                             |
              v                                                           |
    +-------------------+                                                 |
    |core/extraction.py |<---> [ LibreOffice / docx2pdf PDF Converter ]   |
    +---------+---------+                                                 |
              |                                                           |
              | Outputs PageBlocks (Text + Markdown Tables)               |
              v                                                           |
    +-------------------+                                                 |
    |core/llm_engine.py |                                                 |
    +---------+---------+                                                 |
              |                                                           |
              | 3. Groups pages into ~9k char batches                     |
              +---> [ Batch Orchestrator ]                                |
              |         | (Sends strict JSON prompts)                     |
              |         v                                                 |
              |     [ OpenAI / Azure OpenAI API ]                         |
              |         | (Returns raw extraction JSON)                   |
              |         v                                                 |
              |     [ Map-Reduce Reducer ]                                |
              |         | (Merges extraction structures)                   |
              |         v                                                 |
              |     [ Ledger Math Engine ]                                |
              |         | (Calculates deterministic subtotal sums)        |
              |         v                                                 |
              |     [ Executive Brief Consolidation ]                     |
              |         | (Builds consolidated markdown briefing summary) |
              |         v                                                 |
              +---------+=================================================+
                        |
                        | 7. Caches & Indexes AnalysisResult
                        v
              +-------------------+
              |  core/storage.py  |
              +---------+---------+
                        |
                        +---> Check SHA-256 Hash Index: [ storage/library.json ]
                        +---> Write/Read Original Document: [ storage/files/ ]
                        +---> Cache parsed JSON outputs: [ storage/analysis/ ]

================================================================================
