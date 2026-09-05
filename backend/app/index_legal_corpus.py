"""Index the bundled legal corpus for a one-shot Cloud Run Job."""

from app.db import SessionLocal
from app.rag.corpus import LegalCorpusIndexer


def main() -> None:
    with SessionLocal() as db:
        result = LegalCorpusIndexer(db).index_all(force=False)
    print(result.model_dump_json())
    if result.documents_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
