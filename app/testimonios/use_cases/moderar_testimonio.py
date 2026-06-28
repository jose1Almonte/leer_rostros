"""ModerarTestimonio use case: admin approves or rejects a testimonial."""

from uuid import UUID

from app.shared._exceptions import ModificacionInvalidaError, TestimonioNotFoundError
from app.testimonios.repositories.testimonio import TestimonioRepository

_VALORES = {"aprobada", "rechazada", "pendiente"}


class ModerarTestimonio:
    """Admin flow: set a testimonial's estado (aprobada / rechazada / pendiente)."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(self, id: str, valor: str) -> dict:
        id = (id or "").strip()
        if not id:
            raise TestimonioNotFoundError()
        try:
            tid = UUID(id)
        except (ValueError, AttributeError):
            raise TestimonioNotFoundError()

        valor = (valor or "").strip().lower()
        if valor not in _VALORES:
            raise ModificacionInvalidaError(
                f"Valor inválido: '{valor}'. Usá 'aprobada', 'rechazada' o 'pendiente'."
            )

        n = self._repo.set_estado(tid, valor)
        if n == 0:
            raise TestimonioNotFoundError("No existe ese testimonio.")

        return {"id": id, "estado": valor}
