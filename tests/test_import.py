from email.message import EmailMessage


def test_imports():
    from app.main import app
    assert app.title == "Email Reader"


def test_utf8_umlauts_are_decoded_correctly():
    from app.imap_client import _decode

    assert _decode("ä ö ü") == "ä ö ü"
    assert _decode("Ä Ö Ü") == "Ä Ö Ü"


def test_utf8_message_body_is_decoded_correctly():
    from app.imap_client import _body

    msg = EmailMessage()
    msg.set_content("Grüezi – schöne Grüße: ä ö ü")

    assert _body(msg) == "Grüezi – schöne Grüße: ä ö ü"
