import unittest
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from api import ddunlimited_api as d

BASE = 'https://ddunlimited.net'
SOURCE = d.DDUListSource('Film', BASE + '/viewforum.php?f=1584&cf[1]=21&cfr[1]=21', 'movie', 'movie', '1080p', 'ITA')

def page(topics, links=''):
    rows = ''.join(f'<li class="row"><a class="topictitle" href="./viewtopic.php?f=1584&t={t}">Film {t} (2020)</a><td colspan="2">720p ENG</td></li>' for t in topics)
    return f'<ul class="topiclist">{rows}<li class="row announce"><a class="topictitle" href="./viewtopic.php?f=1584&t=9">Annuncio</a></li></ul><div class="pagination">{links}</div>'

class SourcesTest(unittest.TestCase):
    def test_pages_filters_dedup_and_metadata(self):
        seen = []
        links = '<a href="./viewforum.php?f=1584&start=25">2</a><a href="./viewforum.php?f=7&start=50">other</a><a href="./viewforum.php?f=1584&cf[1]=99&start=75">wrong filter</a>'
        def fetch(url, **kwargs):
            q = parse_qs(urlparse(url).query); seen.append(q)
            self.assertEqual(q['cf[1]'], ['21']); self.assertEqual(q['cfr[1]'], ['21'])
            return page([1, 2], links) if q['start'] == ['0'] else page([2, 3], '<a href="./viewforum.php?f=1584&start=0">1</a>')
        with patch.object(d, '_fetch_html', side_effect=fetch):
            items, pages = d.read_source(SOURCE, BASE)
        self.assertEqual(pages, 2); self.assertEqual(len(items), 3)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all((i.category, i.media_type, i.quality, i.language) == ('movie', 'movie', '1080p', 'ITA') for i in items))

    def test_old_list(self):
        with patch.object(d, '_fetch_html', return_value='<a class="postlink-local" href="./viewtopic.php?t=123">Film 2020</a> 720p ENG<br>'):
            items, pages = d.read_source(d.DDUListSource('old', BASE + '/viewtopic.php?t=4#T', 'movie', 'movie'), BASE)
        self.assertEqual((len(items), pages, items[0].topic_id), (1, 1, '123'))

    def test_challenge_empty_repeat_and_failure(self):
        link = '<a href="./viewforum.php?f=1584&start=25">2</a>'
        for value in ['<title>Just a moment</title>', '<form action="ucp.php?mode=login"><input type="password"></form>', page([])]:
            with self.subTest(value=value), patch.object(d, '_fetch_html', return_value=value):
                with self.assertRaises((d.DDUInvalidSourcePage, d.ddunlimited_browser.DDUBrowserAuthRequired)):
                    d.read_source(SOURCE, BASE)
        with patch.object(d, '_fetch_html', return_value=page([1], link)):
            with self.assertRaisesRegex(d.DDUInvalidSourcePage, 'ripetuta'):
                d.read_source(SOURCE, BASE)
        with patch.object(d, '_fetch_html', side_effect=[page([1], link), RuntimeError('offline')]):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                d.read_source(SOURCE, BASE)

    def test_cancel_between_pages(self):
        cancel = Event()
        with patch.object(d, '_fetch_html', return_value=page([1])):
            with self.assertRaises(d.DDURefreshCancelled):
                d.read_source(SOURCE, BASE, cancel=cancel, progress=lambda *args: cancel.set())

    def test_merge_keeps_movie_and_warns(self):
        a=d.DDUItem('Film', BASE, '1', category='movie', media_type='movie')
        b=d.DDUItem('Film', BASE, '1', category='anime', media_type='series')
        with self.assertLogs(d.logger, level='WARNING'):
            d._merge_item(a,b)
        self.assertEqual((a.category,a.media_type), ('movie','movie'))

    def test_failed_background_refresh_keeps_cache(self):
        class DB:
            def get_service_config(self, name): return {}
        with patch.object(d, 'ddu_get_sources', return_value=[SOURCE]), patch.object(d, 'read_source', side_effect=RuntimeError('challenge')), patch.object(d, '_save_cache_snapshot') as save:
            d.start_refresh(DB()); d._REFRESH_THREAD.join(5)
            save.assert_not_called()
            self.assertEqual(d.get_refresh_status()['error'], 'challenge')

if __name__ == '__main__': unittest.main()
