from html import escape


def h(value: object | None) -> str:
    return escape("" if value is None else str(value), quote=False)


def short(value: str | None, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"
