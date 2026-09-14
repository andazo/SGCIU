from app.evaluation.hybrid_runner import _database_url_for_local_proxy


def test_cloud_run_socket_url_is_rewritten_for_local_proxy():
    converted = _database_url_for_local_proxy(
        "postgresql+psycopg://app_user:secret@/app_db?host=%2Fcloudsql%2Fproject%3Aregion%3Ainstance"
    )

    assert converted == "postgresql+psycopg://app_user:secret@127.0.0.1:5432/app_db"
