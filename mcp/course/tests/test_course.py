from course_mcp.course import Chapter, Sentence, WrittenSentence, check, paragraphs, passages


def test_passages_are_non_empty_lines():
    assert passages("Title\n\n  First line  \nSecond\n") == ["Title", "First line", "Second"]


def test_content_has_no_length_kind_or_citation_requirements():
    sentence = WrittenSentence(text="2", kind="lesson", cites=[{"passage": "unknown"}])
    assert sentence.warning is None
    assert sentence.cites[0].quote == ""
    assert WrittenSentence(text="").cites == []


def test_paragraphs_keep_sentence_order_and_group_by_paragraph_number():
    sentences = [
        Sentence(text="First", paragraph=2),
        Sentence(text="Intro", paragraph=1),
        Sentence(text="Last", paragraph=2),
    ]
    assert [[s.text for s in p] for p in paragraphs(sentences)] == [["Intro"], ["First", "Last"]]


def test_check_reports_unwritten_sections_untaught_items_and_warnings():
    chapters = [
        Chapter(
            id="c1",
            title="Basics",
            sections=[
                {"id": "c1-s1", "title": "Aliases", "covers": ["alias"]},
                {"id": "c1-s2", "title": "Generics", "covers": ["generic"]},
            ],
        )
    ]
    sections = {"c1-s1": [[{"text": "x", "kind": "explanation", "cites": [], "warning": "Uncited number 2."}]]}
    assert check(chapters, sections, ["alias", "generic", "extra"]) == {
        "unwritten": ["c1-s2"],
        "untaught": ["generic", "extra"],
        "warnings": ["c1-s1 paragraph 1 sentence 1: Uncited number 2."],
    }
