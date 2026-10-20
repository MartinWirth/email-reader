from email.message import EmailMessage

from app.imap_client import _body, _html_body_with_lists


def test_unordered_html_list():
    text = _html_body_with_lists("<p>Items:</p><ul><li>Apple</li><li>Banana</li></ul>")
    assert "• Apple" in text
    assert "• Banana" in text


def test_ordered_html_list_with_start():
    text = _html_body_with_lists('<ol start="3"><li>Third</li><li>Fourth</li></ol>')
    assert "3. Third" in text
    assert "4. Fourth" in text


def test_html_list_preferred_over_plain_alternative():
    msg = EmailMessage()
    msg.set_content("Items: Apple Banana")
    msg.add_alternative("<ul><li>Apple</li><li>Banana</li></ul>", subtype="html")
    assert "• Apple" in _body(msg)


def test_plain_text_without_html_list_unchanged():
    msg = EmailMessage()
    msg.set_content("Hello\n- Apple\n- Banana")
    assert "- Apple" in _body(msg)


def test_script_not_included():
    text = _html_body_with_lists("<script>alert('x')</script><ul><li>Safe</li></ul>")
    assert "alert" not in text
    assert "• Safe" in text
