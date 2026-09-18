"""Small SQL helpers for user-supplied text predicates."""


def escape_like(value: str) -> str:
    """Treat LIKE metacharacters as literal user input."""
    return str(value).replace("!", "!!").replace("%", "!%").replace("_", "!_")


def like_contains(value: str) -> str:
    return f"%{escape_like(value)}%"


def like_prefix(value: str) -> str:
    return f"{escape_like(value)}%"
