"""EliminarTestimonio use case: admin removes a testimonial and its file."""

from contextlib import suppress
from uuid import UUID

from app import storage
from app.shared._exceptions import TestimonioNotFoundError
from app.testimonios.repositories.testimonio import TestimonioRepository


class EliminarTestimonio:
    """Admin flow: delete a testimonial (row + storage file)."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(self, id: str) -> dict:
        id = (id or "").strip()
        if not id:
            raise TestimonioNotFoundError()
        try:
            tid = UUID(id)
        except (ValueError, AttributeError):
            raise TestimonioNotFoundError()

        result = self._repo.delete(tid)
        if result is None:
            raise TestimonioNotFoundError("No existe ese testimonio.")

        with suppress(Exception):
            storage.delete_file(result["archivo_key"])

        return {"id": id, "eliminado": True}
