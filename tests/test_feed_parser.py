from rss_feed_parser import (
    feed_hash, extract_guid, extract_content, extract_summary,
    extract_image, extract_date, extract_author, extract_link,
)


class FakeEntry:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        return None


def test_feed_hash():
    h = feed_hash('https://example.com/feed.xml')
    assert len(h) == 8
    assert feed_hash('https://example.com/feed.xml') == h


def test_extract_guid_priority():
    assert extract_guid(FakeEntry(id='guid1', link='link1')) == 'guid1'
    assert extract_guid(FakeEntry(link='link1')) == 'link1'
    assert extract_guid(FakeEntry(title='title1')) == 'title1'


def test_extract_content():
    entry = FakeEntry(
        content=[{'value': 'short'}, {'value': 'this is much longer content'}],
        summary='medium summary'
    )
    assert extract_content(entry) == 'this is much longer content'


def test_extract_summary_strips_html():
    entry = FakeEntry(summary='<p>Hello <b>world</b></p>')
    result = extract_summary(entry, '<p>Hello <b>world</b></p> and more content here')
    assert '<' not in result
    assert 'Hello world' in result


def test_extract_summary_truncates():
    entry = FakeEntry(summary='x' * 500)
    result = extract_summary(entry, '')
    assert len(result) <= 300


def test_extract_image_from_enclosure():
    entry = FakeEntry(
        enclosures=[{'type': 'image/jpeg', 'href': 'https://img.com/photo.jpg'}]
    )
    assert extract_image(entry) == 'https://img.com/photo.jpg'


def test_extract_image_from_content():
    entry = FakeEntry(
        content=[{'value': '<p>text</p><img src="https://img.com/pic.png" />'}],
        summary=''
    )
    assert extract_image(entry) == 'https://img.com/pic.png'


def test_extract_date_fallback():
    entry = FakeEntry()
    dt = extract_date(entry)
    assert dt is not None  # falls back to now()


def test_extract_author():
    assert extract_author(FakeEntry(author='John')) == 'John'
    assert extract_author(FakeEntry()) == ''


def test_extract_link():
    assert extract_link(FakeEntry(link='http://a.com', id='http://b.com')) == 'http://a.com'
    assert extract_link(FakeEntry(id='http://b.com')) == 'http://b.com'
