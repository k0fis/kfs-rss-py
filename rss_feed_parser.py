import hashlib
import re
from datetime import datetime, timezone
from html import unescape

HTML_TAG_RE = re.compile(r'<[^>]+>')
IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')


def feed_hash(url):
    return hashlib.sha1(url.encode()).hexdigest()[:8]


def extract_guid(entry):
    if getattr(entry, 'id', None):
        return entry.id
    if getattr(entry, 'link', None):
        return entry.link
    if getattr(entry, 'title', None):
        return entry.title
    return str(id(entry))


def extract_link(entry):
    return getattr(entry, 'link', '') or getattr(entry, 'id', '') or ''


def extract_author(entry):
    return getattr(entry, 'author', '') or ''


def extract_content(entry):
    best = ''
    for c in getattr(entry, 'content', []) or []:
        val = c.get('value', '')
        if len(val) > len(best):
            best = val
    desc = getattr(entry, 'summary', '') or ''
    if len(desc) > len(best):
        best = desc
    return best


def extract_summary(entry, content):
    desc = getattr(entry, 'summary', '') or ''
    source = desc if desc and len(desc) < len(content) else content
    plain = HTML_TAG_RE.sub('', source)
    plain = unescape(plain)
    plain = re.sub(r'\s+', ' ', plain).strip()
    if len(plain) > 300:
        plain = plain[:297] + '...'
    return plain


def _is_image_url(url):
    if not url:
        return False
    lower = url.lower()
    return any(ext in lower for ext in IMAGE_EXTS) or 'image' in lower


def extract_image(entry):
    # 1. Media RSS (media_thumbnail, media_content)
    for attr in ('media_thumbnail', 'media_content'):
        media = getattr(entry, attr, None)
        if media:
            items = media if isinstance(media, list) else [media]
            for item in items:
                url = item.get('url', '') if isinstance(item, dict) else ''
                if _is_image_url(url):
                    return url
    # 2. Enclosures
    for enc in getattr(entry, 'enclosures', []) or []:
        if enc.get('type', '').startswith('image/'):
            return enc.get('href', '') or enc.get('url', '')
    # 3. First <img> in content
    content = extract_content(entry)
    m = IMG_SRC_RE.search(content)
    if m:
        return m.group(1)
    return ''


def extract_date(entry):
    for attr in ('published_parsed', 'updated_parsed'):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)
