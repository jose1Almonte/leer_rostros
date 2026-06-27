"""Domain exceptions raised by use cases.

Use cases raise these exceptions; endpoints catch them and map to HTTP status codes.
Each exception carries a `message` attribute used as the HTTPException detail.
"""


class PersonaValidationError(Exception):
    """Raised when form data fails business validation (HTTP 422)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RostroNoDetectadoError(Exception):
    """Raised when no face is detected in uploaded photo(s) (HTTP 422)."""

    def __init__(self, message: str = "No se detectó ningún rostro en la(s) foto(s)."):
        self.message = message
        super().__init__(message)


class PersonaNotFoundError(Exception):
    """Raised when a person_id does not exist in the database (HTTP 404)."""

    def __init__(self, message: str = "No existe esa persona"):
        self.message = message
        super().__init__(message)


class ModificacionInvalidaError(Exception):
    """Raised when an invalid moderation value is provided (HTTP 400)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
