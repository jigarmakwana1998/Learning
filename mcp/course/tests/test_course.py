from course_mcp.course import Chapter, Sentence, check, passages, review

PASSAGES = {
    "s1.p1": "Python 3.12 added the ‘type’ statement for aliases.",
    "s1.p2": r"\[\text{Attention}(Q,K,V)=\text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V\]",
}


def sentence(text, kind="fact", *cites):
    return Sentence(text=text, kind=kind, cites=[{"passage": p, "quote": q} for p, q in cites])


def warnings(*sentences):
    return [s.warning for s in review([list(sentences)], PASSAGES.get)[0]]


def test_passages_are_non_empty_lines():
    assert passages("Title\n\n  First line  \nSecond\n") == ["Title", "First line", "Second"]


def test_citation_problems_are_saved_as_warnings():
    assert warnings(
        sentence("A fact with no source."),
        sentence("Made up.", "fact", ("s1.p1", "the type keyword was removed")),
        sentence("Unknown.", "fact", ("s9.p9", "anything at all")),
        sentence("Next, we look at aliases.", "explanation"),
    ) == ["Fact with no citation.", "Quote not found in s1.p1.", "Unknown passage s9.p9.", None]


def test_quotes_match_despite_curly_quotes_spacing_and_double_escaped_backslashes():
    assert warnings(
        sentence("Python 3.12 added it.", "fact", ("s1.p1", "Python 3.12  added the 'type' statement")),
        sentence("Attention is a softmax.", "fact", ("s1.p2", r"\\text{Attention}(Q,K,V)=\\text{softmax}")),
    ) == [None, None]


def test_numbers_not_in_the_quotes_get_a_warning():
    assert warnings(
        sentence("It came in 3.11.", "fact", ("s1.p1", "added the 'type' statement")),
        sentence("We cover 2 examples.", "explanation"),
    ) == ["Not in the cited source: 3.11.", "Uncited number 2."]


def test_check_reports_unwritten_sections_untaught_items_and_warnings():
    chapters = [Chapter(id="c1", title="Basics", sections=[
        {"id": "c1-s1", "title": "Aliases", "covers": ["alias"]},
        {"id": "c1-s2", "title": "Generics", "covers": ["generic"]},
    ])]
    sections = {"c1-s1": [[{"text": "x", "kind": "explanation", "cites": [], "warning": "Uncited number 2."}]]}
    assert check(chapters, sections, ["alias", "generic", "extra"]) == {
        "unwritten": ["c1-s2"],
        "untaught": ["generic", "extra"],
        "warnings": ["c1-s1 paragraph 1 sentence 1: Uncited number 2."],
    }
