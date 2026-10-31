"""The themed Markdown and JSON viewer for result files."""

from __future__ import annotations

import json
import unittest

from crew_chief import theme, viewer


class MarkdownTests(unittest.TestCase):
    def md(self, text):
        return viewer.markdown_to_html(text)

    def test_headings_emphasis_and_code(self):
        html = self.md("# Title\n\nSome **bold**, _italic_ and `a*b*c` here.")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<em>italic</em>", html)
        self.assertIn("<code>a*b*c</code>", html)

    def test_snake_case_is_not_italic(self):
        self.assertNotIn("<em>", self.md("use some_snake_case_name here"))

    def test_tables_keep_alignment(self):
        html = self.md("| name | n |\n|---|--:|\n| a | 1 |\n| b | 2 |")
        self.assertIn("<th>name</th>", html)
        self.assertIn('<th style="text-align:right">n</th>', html)
        self.assertEqual(html.count("<tr>"), 3)

    def test_lists_nest_and_numbers_become_ordered(self):
        html = self.md("- one\n  - two\n- three\n\n1. a\n2. b")
        self.assertEqual(html.count("<ul>"), 2)
        self.assertIn("<ol>", html)
        self.assertEqual(html.count("<li>"), 5)

    def test_code_fences_are_escaped_and_not_interpreted(self):
        html = self.md('```py\nx = "<b>" # **not bold**\n```')
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<strong>", html)

    def test_raw_html_and_script_are_escaped(self):
        html = self.md("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>")
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_unsafe_link_schemes_are_dropped(self):
        for url in ("javascript:alert", "data:text/html,x", "vbscript:x"):
            html = self.md(f"[click]({url})")
            self.assertNotIn("<a ", html, url)
            self.assertIn("click", html)

    def test_links_are_kept_and_sibling_result_files_open_in_the_viewer(self):
        html = self.md(
            "[site](https://example.com/a?b=1&c=2) [more](results/run-1.md) [data](x/run-2.json)"
        )
        self.assertIn('href="https://example.com/a?b=1&amp;c=2"', html)
        self.assertIn('href="/view/results/run-1.md"', html)
        self.assertIn('href="/view/results/run-2.json"', html)

    def test_attribute_breakout_in_a_link_is_escaped(self):
        html = self.md('[x](https://e.com/"onmouseover="alert(1))')
        self.assertNotIn('"onmouseover', html.replace("&quot;", ""))
        self.assertNotIn(" onmouseover=", html)

    def test_quotes_rules_and_paragraphs(self):
        html = self.md("> quoted\n\n---\n\nfirst line\nsecond line")
        self.assertIn("<blockquote><p>quoted</p></blockquote>", html)
        self.assertIn("<hr>", html)
        self.assertIn("<p>first line second line</p>", html)


class JsonTests(unittest.TestCase):
    def test_a_tree_is_built_from_embedded_data(self):
        page = viewer.render("r.json", json.dumps({"a": [1, 2], "b": "x"}), "/files/results/r.json")
        self.assertIn('id="tree"', page)
        self.assertIn('type="application/json"', page)
        self.assertIn("Expand all", page)

    def test_embedded_data_cannot_close_the_script_element(self):
        hostile = json.dumps({"k": "</script><script>alert(1)</script>"})
        page = viewer.render("r.json", hostile, "/files/results/r.json")
        data = page.split('id="data">')[1].split("</script>")[0]
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data)["k"], "</script><script>alert(1)</script>")

    def test_invalid_json_falls_back_to_escaped_text(self):
        page = viewer.render("bad.json", "{ <b>nope", "/files/results/bad.json")
        self.assertIn("Not valid JSON", page)
        self.assertIn("&lt;b&gt;nope", page)
        self.assertNotIn('id="tree"', page)

    def test_a_very_large_file_is_not_embedded(self):
        big = json.dumps({"x": "a" * (viewer.MAX_JSON_BYTES + 1)})
        page = viewer.render("big.json", big, "/files/results/big.json")
        self.assertIn("Too large", page)
        self.assertNotIn('id="data"', page)


class PageTests(unittest.TestCase):
    def test_the_page_is_themed_and_links_back_and_to_the_raw_file(self):
        page = viewer.render("notes.md", "# Hi", "/files/results/notes.md")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn(theme.JS, page)
        self.assertIn('href="/results/"', page)
        self.assertIn('href="/files/results/notes.md"', page)

    def test_other_kinds_have_no_viewer(self):
        self.assertIsNone(viewer.render("a.html", "<p>x</p>", "/files/results/a.html"))

    def test_the_title_is_escaped(self):
        self.assertIn("&lt;x&gt;", viewer.render("<x>.md", "t", "/f"))


if __name__ == "__main__":
    unittest.main()
