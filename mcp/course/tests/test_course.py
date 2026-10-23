from course_mcp.course import Chapter, Sentence, check, passages, review

PASSAGES = {"s1.p1": "Python 3.12 added the ‘type’ statement for aliases."}


def sentence(text, kind="fact", *cites):
    return Sentence(text=text, kind=kind, cites=[{"passage": p, "quote": q} for p, q in cites])


def test_passages_are_non_empty_lines():
    assert passages("Title\n\n  First line  \nSecond\n") == ["Title", "First line", "Second"]


def test_facts_need_exact_quotes_and_explanations_do_not():
    problems, _ = review(
        [[
            sentence("A fact with no source."),
            sentence("Made up.", "fact", ("s1.p1", "the type keyword was removed")),
            sentence("Unknown.", "fact", ("s9.p9", "anything at all")),
            sentence("Next, we look at aliases.", "explanation"),
        ]],
        PASSAGES.get,
    )
    assert problems == [
        "paragraph 1 sentence 1 is a fact with no citation.",
        "paragraph 1 sentence 2: the quote is not in s1.p1; copy its words exactly.",
        "paragraph 1 sentence 3: unknown passage s9.p9.",
    ]


def test_numbers_not_in_the_quotes_are_saved_with_a_warning():
    problems, written = review(
        [[
            # Straight quotes and different spacing still match the source's curly quotes.
            sentence("Python 3.12 added it.", "fact", ("s1.p1", "Python 3.12  added the 'type' statement")),
            sentence("It came in 3.11.", "fact", ("s1.p1", "added the 'type' statement")),
            sentence("We cover 2 examples.", "explanation"),
        ]],
        PASSAGES.get,
    )
    assert problems == []
    assert [s.warning for s in written[0]] == [
        None,
        "Not in the cited source: 3.11.",
        "Uncited number 2: a number is a fact; cite it.",
    ]


def test_check_reports_unwritten_sections_untaught_items_and_warnings():
    chapters = [Chapter(id="c1", title="Basics", sections=[
        {"id": "c1-s1", "title": "Aliases", "covers": ["alias"]},
        {"id": "c1-s2", "title": "Generics", "covers": ["generic"]},
    ])]
    sections = {"c1-s1": [[{"text": "x", "kind": "explanation", "cites": [], "warning": "Uncited number 2"}]]}
    assert check(chapters, sections, ["alias", "generic", "extra"]) == {
        "unwritten": ["c1-s2"],
        "untaught": ["generic", "extra"],
        "warnings": ["c1-s1 paragraph 1 sentence 1: Uncited number 2"],
    }
