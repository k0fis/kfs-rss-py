-- Feed LLM config
ALTER TABLE feeds ADD COLUMN llm_lang VARCHAR(5);
ALTER TABLE feeds ADD COLUMN llm_mode VARCHAR(20);

-- Article LLM result
ALTER TABLE articles ADD COLUMN llm_summary TEXT;

-- LLM processing queue
CREATE TABLE llm_queue (
    id              BIGSERIAL PRIMARY KEY,
    article_id      BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    feed_id         BIGINT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    mode            VARCHAR(20) NOT NULL,
    source_text     TEXT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    result_text     TEXT,
    error_message   TEXT,
    retry_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_at   TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_llm_queue_status ON llm_queue (status, created_at);
