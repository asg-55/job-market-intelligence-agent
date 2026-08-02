from __future__ import annotations


class SourceAPIError(Exception):
    def __init__(self, category: str, user_message: str) -> None:
        super().__init__(user_message)
        self.category = category
        self.user_message = user_message
