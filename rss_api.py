from datetime import datetime, timezone, timedelta
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring
from email.utils import format_datetime
from flask import Flask, g, jsonify, request, Response
import rss_db as db
import rss_config as cfg
from rss_jwt import require_auth
from rss_feed_parser import feed_hash

app = Flask(__name__)


@app.after_request
def cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
    return resp


@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 204


# ── helpers ──────────────────────────────────────────────

def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _article_dto(row, feed_hash_val=None, feed_title=None, category=None):
    return {
        'guid': row['guid'],
        'title': row['title'] or '',
        'link': row['link'] or '',
        'date': _iso(row.get('published_at')),
        'author': row['author'] or '',
        'summary': row['summary'] or '',
        'content': row['content'] or '',
        'image': row['image'] or '',
        'feedId': feed_hash_val or row.get('feed_hash', ''),
        'feedTitle': feed_title or row.get('feed_title', ''),
        'category': category or row.get('category', ''),
        'read': bool(row.get('is_read')),
        'starred': bool(row.get('is_starred')),
    }


# ── feeds ────────────────────────────────────────────────

@app.get('/feeds')
@require_auth
def get_feeds():
    rows = db.query('''
        SELECT f.id, f.feed_hash, f.title, f.url, f.site_url,
               f.last_fetched_at, f.last_error,
               uf.category,
               (SELECT COUNT(*) FROM articles a2 WHERE a2.feed_id = f.id) AS article_count,
               (SELECT COUNT(*) FROM articles a3
                WHERE a3.feed_id = f.id
                AND NOT EXISTS (
                    SELECT 1 FROM user_articles ua
                    WHERE ua.article_id = a3.id AND ua.user_id = %s AND ua.is_read = TRUE
                )) AS unread_count
        FROM feeds f
        JOIN user_feeds uf ON uf.feed_id = f.id
        WHERE uf.user_id = %s
        ORDER BY LOWER(COALESCE(f.title, f.url))
    ''', (g.user_id, g.user_id))
    return jsonify(
        generated=_iso(datetime.now(timezone.utc)),
        feeds=[{
            'id': r['feed_hash'],
            'title': r['title'] or '',
            'url': r['url'],
            'siteUrl': r['site_url'] or '',
            'category': r['category'] or '',
            'articleCount': r['article_count'],
            'lastUpdated': _iso(r['last_fetched_at']),
            'error': r['last_error'],
            'unreadCount': r['unread_count'],
        } for r in rows]
    )


@app.get('/feeds/<hash>/articles')
@require_auth
def get_feed_articles(hash):
    feed = db.query_one('SELECT * FROM feeds WHERE feed_hash = %s', (hash,))
    if not feed:
        return jsonify(error='Feed not found'), 404
    uf = db.query_one(
        'SELECT category FROM user_feeds WHERE user_id = %s AND feed_id = %s',
        (g.user_id, feed['id'])
    )
    if not uf:
        return jsonify(error='Not subscribed'), 403
    rows = db.query('''
        SELECT a.*, ua.is_read, ua.is_starred
        FROM articles a
        LEFT JOIN user_articles ua ON ua.article_id = a.id AND ua.user_id = %s
        WHERE a.feed_id = %s
        ORDER BY a.published_at DESC
    ''', (g.user_id, feed['id']))
    return jsonify(
        feedId=hash,
        feedTitle=feed['title'] or '',
        articles=[_article_dto(r, hash, feed['title'] or '', uf['category'] or '') for r in rows]
    )


@app.post('/feeds')
@require_auth
def subscribe_feed():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify(error='URL is required'), 400
    category = data.get('category', '') or ''
    h = feed_hash(url)
    feed = db.query_one('SELECT * FROM feeds WHERE url = %s', (url,))
    if not feed:
        feed = db.execute_returning(
            'INSERT INTO feeds (url, feed_hash, created_at) VALUES (%s, %s, NOW()) RETURNING *',
            (url, h)
        )
    existing = db.query_one(
        'SELECT id FROM user_feeds WHERE user_id = %s AND feed_id = %s',
        (g.user_id, feed['id'])
    )
    if existing:
        return jsonify(id=feed['feed_hash'], title=feed['title'] or '', status='already subscribed')
    db.execute(
        'INSERT INTO user_feeds (user_id, feed_id, category, added_at) VALUES (%s, %s, %s, NOW())',
        (g.user_id, feed['id'], category)
    )
    return jsonify(id=feed['feed_hash'], title=feed['title'] or '')


@app.delete('/feeds/<hash>')
@require_auth
def unsubscribe_feed(hash):
    feed = db.query_one('SELECT id FROM feeds WHERE feed_hash = %s', (hash,))
    if not feed:
        return '', 204
    db.execute(
        'DELETE FROM user_feeds WHERE user_id = %s AND feed_id = %s',
        (g.user_id, feed['id'])
    )
    return '', 204


@app.patch('/feeds/<hash>')
@require_auth
def update_feed(hash):
    data = request.get_json(force=True)
    category = data.get('category', '')
    feed = db.query_one('SELECT id FROM feeds WHERE feed_hash = %s', (hash,))
    if not feed:
        return jsonify(error='Feed not found'), 404
    db.execute(
        'UPDATE user_feeds SET category = %s WHERE user_id = %s AND feed_id = %s',
        (category, g.user_id, feed['id'])
    )
    return '', 204


@app.post('/feeds/refresh')
@require_auth
def refresh_feeds():
    from rss_fetch import refresh_user_feeds
    result = refresh_user_feeds(g.user_id)
    return jsonify(**result)


# ── articles state ───────────────────────────────────────

def _get_article_ids(guids):
    if not guids:
        return []
    placeholders = ','.join(['%s'] * len(guids))
    return db.query(
        f'SELECT id, guid FROM articles WHERE guid IN ({placeholders})', tuple(guids)
    )


def _upsert_user_article(user_id, article_id, **fields):
    existing = db.query_one(
        'SELECT id FROM user_articles WHERE user_id = %s AND article_id = %s',
        (user_id, article_id)
    )
    if existing:
        sets = ', '.join(f'{k} = %s' for k in fields)
        vals = list(fields.values()) + [user_id, article_id]
        db.execute(
            f'UPDATE user_articles SET {sets} WHERE user_id = %s AND article_id = %s', tuple(vals)
        )
    else:
        cols = ['user_id', 'article_id'] + list(fields.keys())
        placeholders = ', '.join(['%s'] * len(cols))
        vals = [user_id, article_id] + list(fields.values())
        db.execute(
            f'INSERT INTO user_articles ({", ".join(cols)}) VALUES ({placeholders})', tuple(vals)
        )


@app.post('/articles/read')
@require_auth
def mark_read():
    data = request.get_json(force=True)
    articles = _get_article_ids(data.get('guids', []))
    now = datetime.now(timezone.utc)
    for a in articles:
        _upsert_user_article(g.user_id, a['id'], is_read=True, read_at=now)
    return '', 204


@app.delete('/articles/read')
@require_auth
def mark_unread():
    data = request.get_json(force=True)
    articles = _get_article_ids(data.get('guids', []))
    for a in articles:
        _upsert_user_article(g.user_id, a['id'], is_read=False, read_at=None)
    return '', 204


@app.post('/articles/read/all')
@require_auth
def mark_all_read():
    data = request.get_json(force=True) if request.data else {}
    feed_hash_val = data.get('feedHash')
    now = datetime.now(timezone.utc)
    if feed_hash_val:
        feed = db.query_one('SELECT id FROM feeds WHERE feed_hash = %s', (feed_hash_val,))
        if not feed:
            return '', 204
        articles = db.query('SELECT id FROM articles WHERE feed_id = %s', (feed['id'],))
    else:
        articles = db.query('''
            SELECT a.id FROM articles a
            JOIN user_feeds uf ON uf.feed_id = a.feed_id
            WHERE uf.user_id = %s
        ''', (g.user_id,))
    for a in articles:
        _upsert_user_article(g.user_id, a['id'], is_read=True, read_at=now)
    return '', 204


@app.post('/articles/star')
@require_auth
def star_article():
    data = request.get_json(force=True)
    guid = data.get('guid', '')
    article = db.query_one('SELECT id FROM articles WHERE guid = %s', (guid,))
    if not article:
        return jsonify(error='Article not found'), 404
    now = datetime.now(timezone.utc)
    _upsert_user_article(g.user_id, article['id'], is_starred=True, starred_at=now)
    return '', 204


@app.delete('/articles/star')
@require_auth
def unstar_article():
    data = request.get_json(force=True)
    guid = data.get('guid', '')
    article = db.query_one('SELECT id FROM articles WHERE guid = %s', (guid,))
    if not article:
        return '', 204
    _upsert_user_article(g.user_id, article['id'], is_starred=False, starred_at=None)
    return '', 204


@app.get('/articles/starred')
@require_auth
def get_starred():
    rows = db.query('''
        SELECT a.*, ua.is_read, ua.is_starred, f.feed_hash, f.title AS feed_title,
               COALESCE(uf.category, '') AS category
        FROM user_articles ua
        JOIN articles a ON a.id = ua.article_id
        JOIN feeds f ON f.id = a.feed_id
        LEFT JOIN user_feeds uf ON uf.feed_id = f.id AND uf.user_id = %s
        WHERE ua.user_id = %s AND ua.is_starred = TRUE
        ORDER BY ua.starred_at DESC
    ''', (g.user_id, g.user_id))
    return jsonify(articles=[_article_dto(r) for r in rows])


# ── search ───────────────────────────────────────────────

@app.get('/search')
@require_auth
def search_articles():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 50)), 200)
    if not q:
        return jsonify(articles=[])
    ts_query = ' & '.join(q.split())
    rows = db.query('''
        SELECT a.*, ua.is_read, ua.is_starred, f.feed_hash, f.title AS feed_title,
               COALESCE(uf.category, '') AS category
        FROM articles a
        JOIN feeds f ON f.id = a.feed_id
        JOIN user_feeds uf ON uf.feed_id = f.id AND uf.user_id = %s
        LEFT JOIN user_articles ua ON ua.article_id = a.id AND ua.user_id = %s
        WHERE a.search_vector @@ to_tsquery('simple', %s)
        ORDER BY ts_rank(a.search_vector, to_tsquery('simple', %s)) DESC
        LIMIT %s
    ''', (g.user_id, g.user_id, ts_query, ts_query, limit))
    return jsonify(articles=[_article_dto(r) for r in rows])


# ── reports ──────────────────────────────────────────────

def _report(days, period_label):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query('''
        SELECT a.title, a.link, a.published_at, f.title AS feed_title,
               COALESCE(uf.category, '') AS category
        FROM articles a
        JOIN feeds f ON f.id = a.feed_id
        JOIN user_feeds uf ON uf.feed_id = f.id AND uf.user_id = %s
        WHERE a.published_at > %s
        ORDER BY a.published_at DESC
    ''', (g.user_id, cutoff))
    return jsonify(
        generated=_iso(datetime.now(timezone.utc)),
        period=period_label,
        count=len(rows),
        articles=[{
            'title': r['title'] or '',
            'link': r['link'] or '',
            'date': _iso(r['published_at']),
            'feed': r['feed_title'] or '',
            'category': r['category'],
        } for r in rows]
    )


@app.get('/reports/daily')
@require_auth
def daily_report():
    return _report(1, 'last 24h')


@app.get('/reports/weekly')
@require_auth
def weekly_report():
    return _report(7, 'last 7 days')


# ── OPML ─────────────────────────────────────────────────

@app.get('/feeds/opml')
@require_auth
def export_opml():
    rows = db.query('''
        SELECT f.url, f.title, f.site_url, uf.category
        FROM feeds f
        JOIN user_feeds uf ON uf.feed_id = f.id
        WHERE uf.user_id = %s
        ORDER BY uf.category, LOWER(COALESCE(f.title, f.url))
    ''', (g.user_id,))
    opml = Element('opml', version='1.0')
    head = SubElement(opml, 'head')
    SubElement(head, 'title').text = 'kfs-rss subscriptions'
    SubElement(head, 'dateCreated').text = format_datetime(datetime.now(timezone.utc))
    body = SubElement(opml, 'body')
    categories = {}
    for r in rows:
        cat = r['category'] or ''
        if cat not in categories:
            if cat:
                categories[cat] = SubElement(body, 'outline', text=cat, title=cat)
            else:
                categories[cat] = body
        parent = categories[cat]
        attrs = {'type': 'rss', 'text': r['title'] or r['url'], 'title': r['title'] or '',
                 'xmlUrl': r['url']}
        if r['site_url']:
            attrs['htmlUrl'] = r['site_url']
        SubElement(parent, 'outline', **attrs)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(opml, encoding='unicode')
    return Response(xml, mimetype='text/xml')


@app.post('/feeds/opml')
@require_auth
def import_opml():
    data = request.get_data(as_text=True)
    root = fromstring(data)
    added = 0
    skipped = 0
    for outline in root.iter('outline'):
        xml_url = outline.get('xmlUrl')
        if not xml_url:
            continue
        parent = None
        for el in root.iter('outline'):
            if outline in list(el):
                parent = el
                break
        category = ''
        if parent is not None and not parent.get('xmlUrl'):
            category = parent.get('text', '')
        h = feed_hash(xml_url)
        feed = db.query_one('SELECT * FROM feeds WHERE url = %s', (xml_url,))
        if not feed:
            feed = db.execute_returning(
                'INSERT INTO feeds (url, feed_hash, created_at) VALUES (%s, %s, NOW()) RETURNING *',
                (xml_url, h)
            )
        existing = db.query_one(
            'SELECT id FROM user_feeds WHERE user_id = %s AND feed_id = %s',
            (g.user_id, feed['id'])
        )
        if existing:
            skipped += 1
        else:
            db.execute(
                'INSERT INTO user_feeds (user_id, feed_id, category, added_at) VALUES (%s, %s, %s, NOW())',
                (g.user_id, feed['id'], category)
            )
            added += 1
    return jsonify(added=added, skipped=skipped)


# ── main ─────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=cfg.PORT, debug=True)
