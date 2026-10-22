DISCORD_LIMIT = 2000


def _cut_point(text: str, limit: int) -> int:
    """Where to break text that is longer than limit, preferring a line break, then a space."""
    cut = text.rfind("\n", 0, limit + 1)
    if cut < limit // 2:
        cut = text.rfind(" ", 0, limit + 1)
    if cut < limit // 2:
        cut = limit
    return cut


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split text into Discord-sized chunks, preferring line boundaries."""
    if not text:
        return ["I didn't receive a response from the model."]

    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        cut = _cut_point(remaining, limit)
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def take_finished_paragraphs(text: str, limit: int = DISCORD_LIMIT) -> tuple[list[str], str]:
    """Split off the paragraphs of a reply that is still being written.

    A paragraph is finished once a blank line follows it. A code block is kept whole,
    even when it contains blank lines. A paragraph longer than Discord allows is
    released in pieces without waiting for its end.

    Returns the finished paragraphs and the unfinished text that follows them.
    """
    finished: list[str] = []
    start = 0
    search = 0
    while (index := text.find("\n\n", search)) != -1:
        paragraph = text[start:index]
        if paragraph.count("```") % 2 == 0:  # not inside a code block
            if paragraph.strip():
                finished.extend(split_message(paragraph, limit))
            start = index + 2
        search = index + 2
    remainder = text[start:]
    while len(remainder.strip()) > limit and remainder.count("```") % 2 == 0:
        remainder = remainder.lstrip()
        cut = _cut_point(remainder, limit)
        finished.append(remainder[:cut].rstrip())
        remainder = remainder[cut:].lstrip(" ")
    return finished, remainder
