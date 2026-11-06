"""Regex text helpers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor.textutil import body_classes, canonical_url, h1, json_text, json_unescape, meta_content, strip_tags, title  # noqa: E402


def test_strip_tags_removes_scripts_styles_comments_and_forms():
    html = ("<html><head><style>p{color:red}</style><script>var x = '<p>not text</p>';</script></head>"
            "<body><!-- hidden --><nav><a href='/'>Home</a></nav><p>Hello&nbsp;<b>world</b> &amp; dogs</p>"
            "<form><select><option>Affenpinscher</option></select></form><footer>foot</footer></body></html>")
    assert strip_tags(html) == "Hello world & dogs"


def test_strip_tags_block_tags_become_newlines_and_whitespace_collapses():
    html = "<h1>Title</h1>\n\n  <p>First   line</p><br><p>Second<br>third</p><ul><li>a</li><li>b</li></ul>"
    assert strip_tags(html) == "Title\nFirst line\nSecond\nthird\na\nb"


def test_title_and_h1_are_single_line_and_unescaped():
    html = "<title>\n  Pug Dog Breed &#8211; Information\n</title><h1 class='x'>Pug <span>Facts</span></h1>"
    assert title(html) == "Pug Dog Breed – Information"
    assert h1(html) == "Pug Facts"


def test_meta_content_both_attribute_orders_and_missing():
    html = ('<meta property="og:title" content="A &amp; B" />'
            "<meta content='2016-03-21T14:45:00+00:00' name='published' />")
    assert meta_content(html, "og:title") == "A & B"
    assert meta_content(html, "published") == "2016-03-21T14:45:00+00:00"
    assert meta_content(html, "missing") == ""


def test_json_unescape_and_json_text():
    assert json_unescape(r"a\/b \"q\" café\nx\\y") == 'a/b "q" café\nx\\y'
    assert json_text(r"<p>Hello <b>dog<\/b><\/p>\n<p>bye<\/p>") == "Hello dog\nbye"
    assert json_text("") == ""


def test_canonical_url_both_attribute_orders_and_missing():
    assert canonical_url('<link rel="canonical" href="https://www.akc.org/dog-breeds/st-bernard/" />') == \
        "https://www.akc.org/dog-breeds/st-bernard/"
    assert canonical_url("<link href='https://x.org/a/?p=1&amp;q=2' rel='canonical'>") == "https://x.org/a/?p=1&q=2"
    assert canonical_url('<link rel="stylesheet" href="/s.css"><link rel="alternate" href="/feed/">') == ""


def test_body_classes():
    assert body_classes('<body class="archive tax-characteristic term-50280">') == ["archive", "tax-characteristic", "term-50280"]
    assert body_classes("<body>") == []
    assert body_classes("<div class='body'>") == []
