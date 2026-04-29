#!/usr/bin/env python3
"""rss-fetch.py — stahuje feedy, ukládá články, čistí staré záznamy.

Spouštěn z cronu: */30 * * * *
Také volán z rss_api.py pro on-demand refresh.
"""
import time
from datetime import datetime, timezone, timedelta
import feedparser
import requests
import rss_db as db
import rss_config as cfg
from rss_feed_parser import (
    extract_guid, extract_link, extract_author,
    extract_content, extract_summary, extract_image, extract_date,
)


def _fetch_single(feed):
    headers = {'User-Agent': cfg.USER_AGENT}
    if feed['etag']:
        headers['If-None-Match'] = feed['etag']
    if feed['last_modified']:
        headers['If-Modified-Since'] = feed['last_modified']
    try:
        resp = requests.get(feed['url'], headers=headers, timeout=cfg.FETCH_TIMEOUT)
    except Exception as e:
        db.execute('UPDATE feeds SET last_error = %s WHERE id = %s', (str(e)[:500], feed['id']))
        return 'error'
    if resp.status_code == 304:
        db.execute(
            'UPDATE feeds SET last_fetched_at = NOW(), last_error = NULL WHERE id = %s',
            (feed['id'],)
        )
        return 'cached'
    if resp.status_code != 200:
        err = f'HTTP {resp.status_code}'
        db.execute('UPDATE feeds SET last_error = %s WHERE id = %s', (err, feed['id']))
        return 'error'
    parsed = feedparser.parse(resp.content)
    if not parsed.entries and parsed.bozo:
        err = str(getattr(parsed, 'bozo_exception', 'Parse error'))[:500]
        db.execute('UPDATE feeds SET last_error = %s WHERE id = %s', (err, feed['id']))
        return 'error'
    # Update feed metadata
    title = getattr(parsed.feed, 'title', None) or feed['title']
    site_url = getattr(parsed.feed, 'link', None) or feed['site_url']
    etag = resp.headers.get('ETag') or feed['etag']
    last_modified = resp.headers.get('Last-Modified') or feed['last_modified']
    db.execute('''
        UPDATE feeds SET title = %s, site_url = %s, etag = %s, last_modified = %s,
            last_fetched_at = NOW(), last_error = NULL
        WHERE id = %s
    ''', (title, site_url, etag, last_modified, feed['id']))
    # Upsert articles
    for entry in parsed.entries:
        guid = extract_guid(entry)
        link = extract_link(entry)
        author = extract_author(entry)
        content = extract_content(entry)
        summary = extract_summary(entry, content)
        image = extract_image(entry)
        pub_date = extract_date(entry)
        title_a = getattr(entry, 'title', '') or ''
        row = db.execute_returning('''
            INSERT INTO articles (feed_id, guid, title, link, author, summary, content, image, published_at, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (feed_id, guid) DO UPDATE SET
                title = EXCLUDED.title, link = EXCLUDED.link, author = EXCLUDED.author,
                summary = EXCLUDED.summary, content = EXCLUDED.content,
                image = EXCLUDED.image, published_at = EXCLUDED.published_at
            RETURNING id, (xmax = 0) AS is_new
        ''', (feed['id'], guid, title_a, link, author, summary, content, image, pub_date))
        if row and row['is_new']:
            from rss_llm_queue import enqueue_if_needed
            enqueue_if_needed(row['id'], feed)
    return 'fetched'


def _cleanup():
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.RETENTION_DAYS)
    deleted = db.execute('''
        DELETE FROM articles
        WHERE published_at < %s
        AND id NOT IN (SELECT article_id FROM user_articles WHERE is_starred = TRUE)
    ''', (cutoff,))
    if deleted:
        print(f'  Cleanup: {deleted} old articles deleted')
    # Per-feed limit
    feeds = db.query('SELECT DISTINCT f.id FROM feeds f JOIN user_feeds uf ON uf.feed_id = f.id')
    for f in feeds:
        count = db.query_one('SELECT COUNT(*) AS cnt FROM articles WHERE feed_id = %s', (f['id'],))
        if count['cnt'] > cfg.MAX_ARTICLES_PER_FEED:
            excess = count['cnt'] - cfg.MAX_ARTICLES_PER_FEED
            db.execute('''
                DELETE FROM articles WHERE id IN (
                    SELECT a.id FROM articles a
                    WHERE a.feed_id = %s
                    AND a.id NOT IN (SELECT article_id FROM user_articles WHERE is_starred = TRUE)
                    ORDER BY a.published_at ASC
                    LIMIT %s
                )
            ''', (f['id'], excess))


def fetch_all():
    from rss_llm_queue import reset_timed_out
    reset_timed_out()
    feeds = db.query(
        'SELECT DISTINCT f.* FROM feeds f JOIN user_feeds uf ON uf.feed_id = f.id'
    )
    print(f'Fetching {len(feeds)} active feeds...')
    fetched = cached = errors = 0
    for feed in feeds:
        result = _fetch_single(feed)
        if result == 'fetched':
            fetched += 1
        elif result == 'cached':
            cached += 1
        else:
            errors += 1
            print(f'  ERROR: {feed["title"] or feed["url"]}')
    print(f'  Done: {fetched} fetched, {cached} cached, {errors} errors')
    _cleanup()
    return {'fetched': fetched, 'cached': cached, 'errors': errors}


def refresh_user_feeds(user_id):
    feeds = db.query('''
        SELECT DISTINCT f.* FROM feeds f
        JOIN user_feeds uf ON uf.feed_id = f.id
        WHERE uf.user_id = %s
    ''', (user_id,))
    fetched = cached = errors = 0
    for feed in feeds:
        result = _fetch_single(feed)
        if result == 'fetched':
            fetched += 1
        elif result == 'cached':
            cached += 1
        else:
            errors += 1
    _cleanup()
    return {'fetched': fetched, 'cached': cached, 'errors': errors}


if __name__ == '__main__':
    t0 = time.time()
    fetch_all()
    print(f'Total time: {time.time() - t0:.1f}s')
