import re
import rss_db as db

HTML_TAG = re.compile(r'<[^>]+>')


def enqueue_if_needed(article_id, feed):
    if not feed.get('llm_mode'):
        return
    existing = db.query_one(
        "SELECT id FROM llm_queue WHERE article_id=%s AND status IN ('PENDING','PROCESSING')",
        (article_id,))
    if existing:
        return
    article = db.query_one("SELECT summary, content FROM articles WHERE id=%s", (article_id,))
    if not article:
        return
    source_text = _compute_source(article, feed['llm_mode'])
    if not source_text or len(source_text.strip()) < 20:
        return
    db.execute(
        "INSERT INTO llm_queue (article_id, feed_id, mode, source_text) VALUES (%s,%s,%s,%s)",
        (article_id, feed['id'], feed['llm_mode'], source_text))


def dequeue_next():
    item = db.execute_returning(
        "UPDATE llm_queue SET status='PROCESSING', processing_at=NOW() "
        "WHERE id = (SELECT id FROM llm_queue WHERE status='PENDING' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) "
        "RETURNING id, mode, source_text, article_id, feed_id")
    if not item:
        return None
    article = db.query_one("SELECT title FROM articles WHERE id=%s", (item['article_id'],))
    feed = db.query_one("SELECT title, llm_lang FROM feeds WHERE id=%s", (item['feed_id'],))
    item['article_title'] = article['title'] if article else ''
    item['feed_title'] = feed['title'] if feed else ''
    item['llm_lang'] = feed.get('llm_lang', '') if feed else ''
    return item


def save_result(queue_id, result_text):
    row = db.query_one("SELECT article_id FROM llm_queue WHERE id=%s", (queue_id,))
    if not row:
        return False
    db.execute("UPDATE llm_queue SET status='DONE', result_text=%s, completed_at=NOW() WHERE id=%s",
               (result_text, queue_id))
    db.execute("UPDATE articles SET llm_summary=%s WHERE id=%s", (result_text, row['article_id']))
    return True


def mark_failed(queue_id, error):
    db.execute("UPDATE llm_queue SET status='FAILED', error_message=%s, completed_at=NOW() WHERE id=%s",
               (error[:500], queue_id))


def reset_timed_out(timeout_minutes=5):
    db.execute(
        "UPDATE llm_queue SET status='PENDING', processing_at=NULL, retry_count=retry_count+1 "
        "WHERE status='PROCESSING' AND processing_at < NOW() - interval '%s minutes'",
        (timeout_minutes,))


def queue_status():
    rows = db.query("SELECT status, count(*) as cnt FROM llm_queue GROUP BY status")
    return {r['status']: r['cnt'] for r in rows}


def _compute_source(article, mode):
    if mode == 'translate':
        text = article.get('summary') or ''
        if not text:
            text = _strip_html(article.get('content', ''))[:300]
        return text
    else:
        text = article.get('content') or article.get('summary') or ''
        text = _strip_html(text)
        return text[:2000]


def _strip_html(html):
    if not html:
        return ''
    return HTML_TAG.sub('', html).replace('\n', ' ').strip()
