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


SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="500" height="300" '
    'style="color:var(--text,#fff)">%s</svg>'
)


class SvgTests(unittest.TestCase):
    def clean(self, inner):
        return viewer.clean_svg(SVG % inner)

    def test_shapes_text_and_theme_tokens_are_kept(self):
        out = self.clean(
            '<rect width="5" height="5" style="fill:var(--surface,#000)"/>'
            '<text x="1" y="2">label</text><title>t</title><circle r="2"/>'
        )
        for kept in (
            "<rect",
            "<text",
            "label",
            "<title",
            "<circle",
            "var(--surface,#000)",
            "viewBox",
        ):
            self.assertIn(kept, out)

    def test_it_scales_to_the_page(self):
        out = self.clean("<rect/>")
        self.assertNotIn('width="500"', out)
        self.assertIn("max-width:100%", out)

    def test_scripts_foreign_content_images_and_style_elements_are_removed(self):
        out = self.clean(
            "<script>alert(1)</script><foreignObject><div>x</div></foreignObject>"
            '<image href="http://evil/x.png"/><style>svg{--surface:red}</style><rect id="ok"/>'
        )
        for gone in ("script", "foreignObject", "image", "<style", "evil"):
            self.assertNotIn(gone, out)
        self.assertIn('id="ok"', out)

    def test_event_handlers_and_external_links_are_removed_but_local_ones_stay(self):
        out = self.clean(
            '<rect onclick="alert(1)" onmouseover="x()"/>'
            '<a href="javascript:alert(1)"><rect/></a>'
            '<use href="#shape"/><use href="http://evil/x.svg#a"/>'
        )
        self.assertNotIn("onclick", out)
        self.assertNotIn("onmouseover", out)
        self.assertNotIn("javascript", out)
        self.assertNotIn("evil", out)
        self.assertIn('href="#shape"', out)

    def test_style_declarations_that_load_things_are_dropped(self):
        out = self.clean(
            '<rect style="fill:url(http://evil/p);stroke:var(--border,#000)"/>'
            '<rect style="fill:url(#grad)"/><rect style="background:expression(alert(1))"/>'
        )
        self.assertNotIn("evil", out)
        self.assertNotIn("expression", out)
        self.assertIn("stroke:var(--border,#000)", out)
        self.assertIn("url(#grad)", out)

    def test_anything_that_is_not_a_usable_svg_is_refused(self):
        self.assertIsNone(viewer.clean_svg("<html><body>x</body></html>"))
        self.assertIsNone(viewer.clean_svg("<svg><unclosed>"))
        self.assertIsNone(viewer.clean_svg("not xml"))
        big = SVG % ("<text>" + "a" * viewer.MAX_SVG_BYTES + "</text>")
        self.assertIsNone(viewer.clean_svg(big))

    def test_the_page_inlines_the_drawing_and_explains_a_bad_file(self):
        page = viewer.render("c.svg", SVG % "<rect/>", "/files/results/c.svg")
        self.assertIn("<svg", page)
        self.assertIn(theme.JS, page)
        bad = viewer.render("c.svg", "not xml", "/files/results/c.svg")
        self.assertIn("Not a usable SVG", bad)
        self.assertIn('href="/files/results/c.svg"', bad)


class FormatTabTests(unittest.TestCase):
    ITEMS = [
        ("html", "/files/results/r.html"),
        ("json", "/view/results/r.json"),
        ("md", "/view/results/r.md"),
    ]

    def test_nothing_to_switch_to_means_no_tabs(self):
        self.assertEqual(viewer.format_tabs([], "json"), "")
        self.assertEqual(viewer.format_tabs([("json", "/x")], "json"), "")

    def test_the_current_format_is_marked_and_the_others_are_links(self):
        tabs = viewer.format_tabs(self.ITEMS, "json")
        self.assertIn('<b aria-current="page">json</b>', tabs)
        self.assertIn('<a href="/files/results/r.html">html</a>', tabs)
        self.assertIn('<a href="/view/results/r.md">md</a>', tabs)
        self.assertNotIn('href="/view/results/r.json"', tabs)

    def test_inline_tabs_carry_their_own_styles_for_a_page_without_this_css(self):
        tabs = viewer.format_tabs(self.ITEMS, "html", inline=True)
        self.assertIn("style=", tabs)
        self.assertIn("var(--accent", tabs)

    def test_links_are_escaped(self):
        tabs = viewer.format_tabs([("a", '/x"y'), ("b", "/z")], "b")
        self.assertNotIn('"y', tabs.replace("&quot;", ""))

    def test_the_viewer_bar_shows_the_tabs_it_is_given(self):
        page = viewer.render(
            "r.md", "# t", "/files/results/r.md", viewer.format_tabs(self.ITEMS, "md")
        )
        self.assertIn('class="fmt"', page)
        self.assertIn("/files/results/r.html", page)


class CsvTests(unittest.TestCase):
    def test_a_csv_becomes_a_table_with_escaped_cells(self):
        page = viewer.render("t.csv", 'name,note\nfast,"a, b"\n<b>x</b>,1\n', "/t.csv?raw=1")
        self.assertIn("<th>name</th>", page)
        self.assertIn("<td>a, b</td>", page)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", page)
        self.assertNotIn("<b>x</b>", page)

    def test_a_long_csv_is_cut_with_a_pointer_to_the_raw_file(self):
        rows = "\n".join(f"{i},v" for i in range(viewer.MAX_CSV_ROWS + 5))
        page = viewer.render("t.csv", "n,v\n" + rows, "/t.csv?raw=1")
        self.assertIn("Showing the first", page)
        self.assertIn('href="/t.csv?raw=1"', page)

    def test_an_empty_csv_says_so(self):
        self.assertIn("Empty file", viewer.render("t.csv", "", "/t.csv?raw=1"))


class PageTests(unittest.TestCase):
    def test_the_page_is_themed_and_links_to_the_raw_file(self):
        page = viewer.render("notes.md", "# Hi", "/files/results/notes.md")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn(theme.JS, page)
        self.assertNotIn("All files", page)  # the strip under the top bar already has it
        self.assertIn('href="/files/results/notes.md"', page)

    def test_other_kinds_have_no_viewer(self):
        self.assertIsNone(viewer.render("a.html", "<p>x</p>", "/files/results/a.html"))

    def test_the_title_is_escaped(self):
        self.assertIn("&lt;x&gt;", viewer.render("<x>.md", "t", "/f"))


if __name__ == "__main__":
    unittest.main()
