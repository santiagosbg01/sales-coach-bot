"""Adaptive probing using only rubric templates stored in the database."""
from typing import List, Dict, Optional
from config import Config


class AdaptiveProber:
    """
    Generates follow-up probes exclusively from the rubric's
    followup_templates stored in the database — no LLM generation.
    """

    def should_probe(self, missed_concepts: List[str], probe_count: int = 0) -> bool:
        return bool(missed_concepts) and probe_count < Config.MAX_PROBES_PER_QUESTION

    def generate_probe_question(
        self,
        original_question: str,
        original_answer: str,
        missed_concepts: List[str],
        followup_templates: Optional[List[str]] = None,
        probe_number: int = 1,
    ) -> str:
        """
        Return the next probe question from the DB's followup_templates.
        Falls back to a simple generic prompt if templates are exhausted.
        """
        concepts_str = " and ".join(missed_concepts[:2])

        # Use stored templates first (0-indexed, probe_number is 1-based)
        if followup_templates:
            idx = probe_number - 1
            if idx < len(followup_templates):
                template = followup_templates[idx]
                return (template
                        .replace("{concept}", concepts_str)
                        .replace("{concepts}", concepts_str))

        # Generic fallback — no LLM call
        return f"Can you elaborate on {concepts_str}?"

    def generate_summary_tip(
        self,
        original_question: str,
        all_attempts: List[Dict],
        final_missed_concepts: List[str],
    ) -> str:
        """Plain-text tip after probing ends — no LLM call."""
        if not final_missed_concepts:
            return "Great job — you covered all the key concepts!"

        concepts_str = ", ".join(final_missed_concepts)
        return (
            f"Keep working on: {concepts_str}. "
            "Review your training materials and try to use these ideas naturally in your answers."
        )
