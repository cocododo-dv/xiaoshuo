from novel_system.services.manuscript_html import sanitize_manuscript_html


def test_sanitizer_removes_executable_and_remote_content() -> None:
    dirty = (
        '<p onclick="steal()">安全正文<img src=x onerror="steal()"></p>'
        '<script>steal()</script><iframe src="https://evil.invalid"></iframe>'
    )

    assert sanitize_manuscript_html(dirty) == "<p>安全正文</p>"


def test_sanitizer_keeps_editor_formatting_but_drops_attributes() -> None:
    dirty = '<blockquote class="x"><strong style="color:red">句子 &amp; 余音</strong><br></blockquote>'

    assert sanitize_manuscript_html(dirty) == "<blockquote><strong>句子 &amp; 余音</strong><br></blockquote>"


def test_sanitizer_leaves_plain_text_unchanged() -> None:
    assert sanitize_manuscript_html("没有 HTML 的正文 & 标点") == "没有 HTML 的正文 & 标点"
