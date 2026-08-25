from app.cli import _collect_citizen_profile


def test_cli_collects_citizen_profile_before_incident(monkeypatch):
    answers = iter(
        [
            "Ana Prueba",
            "1-2345-6789",
            "ana@example.com",
            "8888-9999",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    profile = _collect_citizen_profile()

    assert profile is not None
    assert profile.name == "Ana Prueba"
    assert profile.identification == "1-2345-6789"
    assert str(profile.email) == "ana@example.com"
    assert profile.phone == "8888-9999"


def test_cli_allows_optional_identification_and_contact(monkeypatch):
    answers = iter(["Ana Prueba", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    profile = _collect_citizen_profile()

    assert profile is not None
    assert profile.identification is None
    assert profile.email is None
    assert profile.phone is None
