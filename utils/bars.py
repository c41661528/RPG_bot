def make_bar(current: int | float, maximum: int | float, length: int = 10) -> str:
    """Return a Unicode block progress bar string."""
    if maximum <= 0:
        return "░" * length
    filled = max(0, min(length, round((current / maximum) * length)))
    return "█" * filled + "░" * (length - filled)


def hp_bar(current: int, maximum: int, length: int = 12) -> str:
    return f"❤️  `{make_bar(current, maximum, length)}`  **{current}** / {maximum}"


def energy_bar(current: int, maximum: int, length: int = 12) -> str:
    return f"⚡  `{make_bar(current, maximum, length)}`  **{current}** / {maximum}"


def exp_bar(current: int, maximum: int, length: int = 12) -> str:
    return f"📊  `{make_bar(current, maximum, length)}`  **{current}** / {maximum} EXP"
