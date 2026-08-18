from novel_system.services.writing_stats import count_words, visible_manuscript_text


def test_html_entities_count_like_browser_visible_text() -> None:
    html = "<p>A&nbsp;B &amp; C</p>"

    assert visible_manuscript_text(html) == "A\xa0B & C"
    assert count_words(html) == 4


def test_nested_markup_and_line_breaks_do_not_add_words() -> None:
    assert count_words("<p>潮声 <strong>回来</strong></p><p>了。</p>") == 6


def test_hidden_content_is_not_counted() -> None:
    assert count_words("<p>正文</p><script>steal token</script><style>body{}</style>") == 2


def test_plain_text_with_angle_bracket_is_not_destroyed() -> None:
    text = "他说 1 < 2，然后离开。"

    assert visible_manuscript_text(text) == text
    assert count_words(text) == len(text.replace(" ", ""))
