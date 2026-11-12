#!/usr/bin/env python3
"""docs-53: near/web/docs.html is the one source of "How it works", served at /web/docs.html and read by the arena's
How it works modal. The modal takes the <section>s inside <main> in order and keeps only a few tags, so this case
holds the page to that shape: every child of <main> is a <section id> that opens with an <h2>; inside, only the
tags the modal keeps; no <h1> in <main> (the modal keeps its own title); every link is an absolute path or a full
URL, so it works from both pages; and the page's own contents list names every section.

  python3 -I near/web/test_docs_page.py
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "docs.html"
KEPT = {"section", "h2", "h3", "p", "ul", "ol", "li", "a", "strong", "em", "code"}


class Shape(HTMLParser):
    """Reads <main> only: `inner` is the open-tag stack inside it (void tags never pushed)."""
    VOID = {"br", "hr", "img", "meta", "link", "input", "wbr"}

    def __init__(self):
        super().__init__()
        self.inner, self.in_main, self.sections, self.bad, self.links, self.nav = None, False, [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.in_main, self.inner = True, []
            return
        if not self.in_main:
            if tag == "a" and (a.get("href") or "").startswith("#"):
                self.nav.append(a["href"][1:])
            return
        if tag not in KEPT:
            self.bad.append(tag)
        if tag == "section":
            if self.inner:
                self.bad.append("nested section")
            self.sections.append({"id": a.get("id"), "first": None})
        elif not self.inner:
            self.bad.append("loose " + tag)
        elif self.sections and self.sections[-1]["first"] is None:
            self.sections[-1]["first"] = tag
        if tag == "a":
            self.links.append(a.get("href") or "")
        if tag not in self.VOID:
            self.inner.append(tag)

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        elif self.in_main:
            while self.inner:
                if self.inner.pop() == tag:
                    break


class DocsPage(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PAGE.is_file(), "near/web/docs.html is missing")
        self.shape = Shape()
        self.shape.feed(PAGE.read_text())

    def test_main_is_sections_that_open_with_an_h2_and_use_only_the_modals_tags(self):
        s = self.shape
        self.assertGreaterEqual(len(s.sections), 8)
        self.assertEqual(s.bad, [], "tags or layout the modal would drop")
        for sec in s.sections:
            self.assertTrue(sec["id"], "every section needs an id")
            self.assertEqual(sec["first"], "h2", f"section {sec['id']} must open with its h2")
        self.assertEqual(len({sec["id"] for sec in s.sections}), len(s.sections))

    def test_links_work_from_both_pages_and_the_contents_list_names_every_section(self):
        for href in self.shape.links:
            self.assertRegex(href, r"^(/|https://)", f"link {href!r} would break inside the arena page's modal")
        self.assertEqual(self.shape.nav, [sec["id"] for sec in self.shape.sections])

    def test_no_h1_inside_main(self):
        page = re.sub(r"<!--.*?-->", "", PAGE.read_text(), flags=re.S)
        main = re.search(r"<main>(.*)</main>", page, re.S).group(1)
        self.assertNotIn("<h1", main)


if __name__ == "__main__":
    unittest.main()
