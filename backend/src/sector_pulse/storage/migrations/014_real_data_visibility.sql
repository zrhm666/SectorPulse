CREATE TABLE IF NOT EXISTS news_query_documents (
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, query_id, document_id),
    FOREIGN KEY (run_id, query_id)
        REFERENCES news_queries(run_id, query_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_query_documents_run
    ON news_query_documents(run_id);
