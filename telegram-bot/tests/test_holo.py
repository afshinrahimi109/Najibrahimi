import unittest

from holo import _SearchParser, clean_intent_text, format_search_results


class HoloUtilityTests(unittest.TestCase):
    def test_search_parser_extracts_result_fields(self):
        parser = _SearchParser()
        parser.feed(
            '<div class="result"><a class="result__a" href="https://example.com">A <b>title</b></a>'
            '<div class="result__snippet">A useful <b>summary</b>.</div></div>'
        )
        self.assertEqual(parser.results[0]["url"], "https://example.com")
        self.assertEqual(parser.results[0]["title"], "A title")
        self.assertEqual(parser.results[0]["snippet"], "A useful summary.")

    def test_format_search_results_keeps_source_url(self):
        rendered = format_search_results([{"title": "Example", "snippet": "Summary", "url": "https://example.com"}])
        self.assertIn("Example", rendered)
        self.assertIn("https://example.com", rendered)

    def test_intent_cleanup_removes_trigger_words(self):
        result = clean_intent_text("جستجو کن خبرهای امروز", ("جستجو کن", "جستجو"))
        self.assertEqual(result, "خبرهای امروز")


if __name__ == "__main__":
    unittest.main()
