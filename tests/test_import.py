def test_imports():
    from app.main import app
    assert app.title == "Email Reader"
