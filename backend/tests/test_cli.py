from app.cli import _collect_citizen_profile, _print_recurrent_patterns
from app.schemas import ComplaintExtractedData, ComplaintSubmissionCreate
from app.services.incidents import IncidentService


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


def test_cli_prints_recurrent_patterns(db_session, capsys):
    for description in (
        "Fiesta con música alta frente a la escuela.",
        "Ruido fuerte de una fiesta cerca de la escuela.",
        "Música a alto volumen en las cercanías de la escuela.",
    ):
        IncidentService(db_session).create(
            ComplaintSubmissionCreate(
                ai_extracted_data=ComplaintExtractedData(
                    descripcion_detallada=description,
                    relacion_incidente="testigo",
                    categoria_preliminar="ruido",
                    distrito="Llorente",
                    direccion_exacta="100 metros norte de la escuela",
                    tipo_lugar="parque",
                    fecha_hora_aproximada="hoy",
                ),
                truth_confirmation=True,
                data_usage_consent=True,
            )
        )

    _print_recurrent_patterns(db_session)

    output = capsys.readouterr().out
    assert "Patrones recurrentes" in output
    assert "Incidentes relacionados: 3" in output
