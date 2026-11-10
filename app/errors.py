"""Domain errors raised by the service layer. `app.main` maps them to HTTP responses."""


class LibraryError(Exception):
    pass


class NotFoundError(LibraryError):
    pass


class ConflictError(LibraryError):
    pass


class BookNotFound(NotFoundError):
    def __init__(self, serial_number: str) -> None:
        super().__init__(f"Book {serial_number} not found.")


class SerialNumberTaken(ConflictError):
    def __init__(self, serial_number: str) -> None:
        super().__init__(f"A book with serial number {serial_number} already exists.")


class BookAlreadyCheckedOut(ConflictError):
    def __init__(self, serial_number: str) -> None:
        super().__init__(f"Book {serial_number} is already checked out.")


class BookNotCheckedOut(ConflictError):
    def __init__(self, serial_number: str) -> None:
        super().__init__(f"Book {serial_number} is not checked out.")


class BookCheckedOut(ConflictError):
    def __init__(self, serial_number: str) -> None:
        super().__init__(f"Book {serial_number} is checked out; return it before deleting.")
