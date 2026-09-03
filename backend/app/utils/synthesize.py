"""
Synthesizes a dynamic, input-aware placeholder answer for stub model paths
that have no real ML weights loaded (no GPU / weights not downloaded).

Replaces the old static "Model output not available" string, which was
identical for every request regardless of what was asked or uploaded. This
reads the actual query text and uploaded filename(s) so the demo response
at least reflects the real input, instead of a fixed placeholder.
"""

from pathlib import Path


def synthesize_answer(query: str, image_paths: list[str], task_hint: str = "vqa", target: str = "") -> str:
    """
    Args:
        query: The user's natural language question.
        image_paths: Paths to the uploaded image(s), if any.
        task_hint: One of "vqa", "caption", "grounding", "change", "fusion".
        target: For grounding, the extracted target phrase (e.g. "the water body").
    """
    filenames = [Path(p).name for p in image_paths]

    if not filenames:
        return (
            f'Responding to your question: "{query}" — no imagery is attached to this '
            "message, so this is a conversational reply rather than an image analysis. "
            "Attach a satellite image for a location-grounded answer."
        )

    if len(filenames) == 1:
        file_desc = f"the uploaded file `{filenames[0]}`"
    else:
        file_desc = f"the uploaded files `{filenames[0]}` and `{filenames[1]}`"

    if task_hint == "grounding":
        located = target or "the requested feature"
        body = (
            f"Analyzing {file_desc} for the query: \"{query}\". "
            f"I attempted to locate {located} and would normally highlight the matching "
            "region(s) directly on the image."
        )
    elif task_hint == "caption":
        body = f"Analyzing {file_desc} to generate a description for: \"{query}\"."
    elif task_hint == "change":
        body = (
            f"Comparing {file_desc} across the two capture dates for the query: \"{query}\". "
            "I have highlighted the structural changes in red on the change map."
        )
    elif task_hint == "fusion":
        body = (
            f"Fusing optical and SAR signal from {file_desc} to answer: \"{query}\"."
        )
    else:
        body = f"Analyzing {file_desc} for the query: \"{query}\"."

    return (
        f"{body} This stub environment has no live vision-language model loaded — "
        "connect real model weights to replace this synthesized placeholder with a "
        "grounded answer."
    )
