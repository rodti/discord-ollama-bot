def split_message(text: str, limit: int = 2000) -> list[str]:
    """Split text into Discord-sized chunks, preferring line boundaries."""
    if not text:
        return ["I didn't receive a response from the model."]

    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
