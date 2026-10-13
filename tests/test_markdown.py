import pytest

from dayline.errors import DaylineError
from dayline.markdown import markdown_markup, toggle_checklist


def test_markdown_renders_study_notes_with_headings_checklists_and_named_links():
    notes = (
        "## Recognition drills — 90 minutes\n\n"
        "- [ ] **90 minutes · Core:** [E — Oscar](https://codeforces.com/gym/104090/problem/E)\n"
        "  Arithmetic progression modulo `m`.\n"
        "- [x] *Review* the construction\n"
        "1. Explain the proof\n"
        "+ Practice"
    )
    assert markdown_markup(notes) == (
        '<span size="large"><b>Recognition drills — 90 minutes</b></span>\n\n'
        '<span foreground="#b5b1a9" underline="none" size="x-large">☐</span> '
        '<b>90 minutes · Core:</b> <a href="https://codeforces.com/gym/104090/problem/E">'
        "E — Oscar</a>\n"
        "  Arithmetic progression modulo <tt>m</tt>.\n"
        '<span foreground="#91c59c" underline="none" size="x-large">☑</span> '
        "<i>Review</i> the construction\n"
        "1. Explain the proof\n"
        "• Practice"
    )


def test_inline_formatting_preserves_literal_code_escapes_and_word_underscores():
    assert markdown_markup(r"__Bold *inside*__ and _italic_; snake_case; \*literal\*") == (
        "<b>Bold <i>inside</i></b> and <i>italic</i>; snake_case; *literal*"
    )
    assert markdown_markup("`<b>**literal** https://example.test</b>`") == (
        "<tt>&lt;b&gt;**literal** https://example.test&lt;/b&gt;</tt>"
    )
    assert markdown_markup("```python\nif a < b:\n    # **literal**\n```\nAfter") == (
        "<tt>if a &lt; b:\n    # **literal**</tt>\nAfter"
    )
    assert markdown_markup("```\nUnclosed <code>") == "<tt>Unclosed &lt;code&gt;</tt>"


def test_links_escape_user_content_and_reject_non_web_destinations():
    assert markdown_markup("[**A & B**](https://example.test/a_(b)?x=1&y=2)") == (
        '<a href="https://example.test/a_(b)?x=1&amp;y=2"><b>A &amp; B</b></a>'
    )
    notes = (
        "<b>HTML</b> [run](javascript:alert(1)) [file](file:///tmp/notes) "
        "[tick](dayline-checklist:0)"
    )
    assert markdown_markup(notes) == (
        "&lt;b&gt;HTML&lt;/b&gt; [run](javascript:alert(1)) [file](file:///tmp/notes) "
        "[tick](dayline-checklist:0)"
    )
    assert markdown_markup("[https://example.test](https://other.test)") == (
        '<a href="https://other.test">https://example.test</a>'
    )


def test_plain_text_whitespace_and_incomplete_markup_remain_readable():
    notes = "  Plain notes\n\n**unfinished and [missing](\n#hashtag\n\n"
    assert markdown_markup(notes) == notes
    assert markdown_markup("See https://example.test?a=1&b=2.") == (
        'See <a href="https://example.test?a=1&amp;b=2">https://example.test?a=1&amp;b=2</a>.'
    )


def test_checklist_links_and_toggles_preserve_source_and_exclude_code():
    notes = "\n  - [ ] **First**  \r\n- [X] Second\n```\n- [ ] Code\n```\n"
    markup = markdown_markup(notes, checklists=True)
    assert '<a href="dayline-checklist:1"><span foreground="#b5b1a9"' in markup
    assert '<a href="dayline-checklist:2"><span foreground="#91c59c"' in markup
    assert 'href="dayline-checklist:4"' not in markup
    assert toggle_checklist(notes, 1) == notes.replace("[ ] **First**", "[x] **First**")
    assert toggle_checklist(toggle_checklist(notes, 1), 1) == notes
    assert toggle_checklist(notes, 2) == notes.replace("[X] Second", "[ ] Second")
    for line in (-1, 0, 4, 99):
        with pytest.raises(DaylineError, match="checklist changed"):
            toggle_checklist(notes, line)
