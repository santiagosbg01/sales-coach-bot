"""
Knowledge base loader.
Maps question tags to official service documents.
The grader uses these to give OpenAI accurate reference material.
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent.parent / "data" / "knowledge_bases"

# Max chars injected into the grading prompt (keep costs down)
MAX_KB_CHARS = 6000


def load_for_question(tags: list[str]) -> Optional[str]:
    """
    Return the knowledge base text most relevant to a question's tags.
    Tries each tag in order, returns the first match found.
    Falls back to general.txt if nothing matches.
    """
    candidates = list(tags) + ["general"]
    for tag in candidates:
        path = KB_DIR / f"{tag}.txt"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
                if len(text) > MAX_KB_CHARS:
                    text = text[:MAX_KB_CHARS] + "\n[...documento truncado para brevedad...]"
                logger.debug(f"Loaded KB '{tag}' ({len(text)} chars)")
                return text
            except Exception as e:
                logger.warning(f"Could not read KB '{tag}': {e}")
    return None
