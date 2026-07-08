"""
Unified LLM grading system — all question types go through GPT-4o-mini.

• open_ended   — keyword pre-check as context, LLM scores 1-5
• multiple_choice / yes_no — LLM interprets intent, confirms correct answer,
                             always explains why the answer is right or wrong
"""
import re
import json
import logging
from typing import Dict, List, Optional

from openai import OpenAI
from config import Config
from models import PassState
from services.knowledge_base import load_for_question

logger = logging.getLogger(__name__)


class HybridGrader:
    """Grades answers using keyword context + OpenAI GPT-4o-mini as authoritative scorer."""

    def __init__(self):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)

    def grade_answer(
        self,
        question_prompt: str,
        answer_text: str,
        must_have_concepts: List,
        good_to_have_concepts: List,
        ideal_answer: Optional[str] = None,
        reference_snippet: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """
        Grade an answer. Returns:
            score_0_5, pass_state, result (GOOD/BAD),
            rubric_hits, missed_concepts, feedback,
            grader_trace, grading_method
        """
        keyword = self._keyword_score(answer_text, must_have_concepts, good_to_have_concepts)
        kb_text = load_for_question(tags or []) if tags else None

        llm = self._llm_score(
            question_prompt, answer_text,
            must_have_concepts, good_to_have_concepts,
            keyword, ideal_answer, reference_snippet, kb_text,
        )

        # LLM is authoritative; keyword hits can raise a low LLM score by at most +0.5
        llm_score = max(0.0, min(5.0, float(llm["score"])))
        if keyword["must_have_hits"] and llm_score < 3:
            llm_score = min(3.0, llm_score + 0.5)

        final_score = round(llm_score)
        pass_state  = self._pass_state(final_score, keyword["must_have_hits"])
        result      = "GOOD" if final_score >= 3 else "BAD"

        return {
            "score_0_5":       final_score,
            "result":          result,
            "pass_state":      pass_state,
            "rubric_hits":     {
                "must_have":    keyword["must_have_hits"],
                "good_to_have": keyword["good_to_have_hits"],
            },
            "missed_concepts": keyword["missed_concepts"],
            "feedback":        llm["feedback"],
            "grader_trace":    {
                "keyword_score":  keyword["score"],
                "llm_score":      llm["score"],
                "llm_reasoning":  llm["reasoning"],
                "kb_used":        llm.get("kb_used", False),
            },
            "grading_method":  "hybrid",
        }

    # ------------------------------------------------------------------
    # Keyword pre-check — handles both dict and plain-string formats
    # ------------------------------------------------------------------

    def _normalise_concepts(self, items: List) -> List[Dict]:
        """
        Accept items as either:
          • {"concept": "...", "synonyms": [...]}  — original format
          • "plain string"                          — new format from Excel rubrics
          • "a; b; c"                               — semicolon-separated list
        Returns a normalised list of {"concept": str, "synonyms": [str]}.
        """
        out = []
        for item in items:
            if isinstance(item, dict):
                out.append({
                    "concept":  item.get("concept", ""),
                    "synonyms": item.get("synonyms", []),
                })
            elif isinstance(item, str) and item.strip():
                # Split on ";" to handle "concept1; concept2; concept3"
                for part in item.split(";"):
                    part = part.strip()
                    if part:
                        out.append({"concept": part, "synonyms": []})
        return out

    def _keyword_score(self, answer: str, must_have: List, good_to_have: List) -> Dict:
        answer_lower = answer.lower()

        must_norm  = self._normalise_concepts(must_have)
        good_norm  = self._normalise_concepts(good_to_have)

        must_hits, must_misses = [], []
        for item in must_norm:
            terms = [item["concept"]] + item["synonyms"]
            if any(self._match(t, answer_lower) for t in terms if t):
                must_hits.append(item["concept"])
            else:
                must_misses.append(item["concept"])

        good_hits = []
        for item in good_norm:
            terms = [item["concept"]] + item["synonyms"]
            if any(self._match(t, answer_lower) for t in terms if t):
                good_hits.append(item["concept"])

        total_must = len(must_norm)
        total_good = len(good_norm)

        if total_must == 0:
            base = 3.0
        else:
            must_ratio = len(must_hits) / total_must
            good_ratio = len(good_hits) / total_good if total_good else 0
            base = (must_ratio * 3.5) + (good_ratio * 1.5)

        return {
            "score":             round(base, 1),
            "must_have_hits":    must_hits,
            "good_to_have_hits": good_hits,
            "missed_concepts":   must_misses,
        }

    def _match(self, term: str, text: str) -> bool:
        return bool(re.search(r"\b" + re.escape(term.lower()) + r"\b", text))

    # ------------------------------------------------------------------
    # OpenAI evaluation — authoritative 1-5 score
    # ------------------------------------------------------------------

    def _llm_score(
        self,
        question: str,
        answer: str,
        must_have: List,
        good_to_have: List,
        keyword: Dict,
        ideal_answer: Optional[str],
        reference: Optional[str],
        kb_text: Optional[str],
    ) -> Dict:
        try:
            must_norm = self._normalise_concepts(must_have)
            good_norm = self._normalise_concepts(good_to_have)

            must_list = ", ".join(c["concept"] for c in must_norm) or "—"
            good_list = ", ".join(c["concept"] for c in good_norm) or "—"
            hit_list  = ", ".join(keyword["must_have_hits"]) or "ninguno"
            miss_list = ", ".join(keyword["missed_concepts"]) or "ninguno"

            system_msg = (
                f"Eres un coach de ventas experto de {Config.COMPANY_NAME}. "
                "Evalúas respuestas de vendedores de forma justa, dando crédito "
                "por ideas correctas aunque no usen las palabras exactas. "
                "Responde SIEMPRE en español con JSON válido."
            )

            # Build the prompt — do NOT pass keyword scores since they are
            # based on long rubric strings and produce misleading signals.
            user_prompt = (
                f"PREGUNTA: {question}\n\n"
                f"RESPUESTA DEL VENDEDOR: {answer}\n\n"
            )

            if ideal_answer:
                user_prompt += f"RESPUESTA DE REFERENCIA: {ideal_answer}\n\n"
            elif must_list and must_list != "—":
                user_prompt += f"PUNTOS CLAVE ESPERADOS: {must_list}\n\n"

            if good_list and good_list != "—":
                user_prompt += f"PUNTOS ADICIONALES (bonus): {good_list}\n\n"

            if kb_text:
                user_prompt += f"BASE DE CONOCIMIENTO OFICIAL:\n{kb_text}\n\n"
            elif reference:
                user_prompt += f"REFERENCIA: {reference}\n\n"

            user_prompt += """Califica la respuesta del vendedor del 1 al 5:

5 = Excelente: captura el hecho/concepto clave + detalles relevantes
4 = Bien: captura el hecho principal + al menos un detalle adicional
3 = Suficiente: demuestra conocer el dato o concepto clave, aunque sin detalles
2 = Débil: toca el tema pero con información incorrecta o muy confusa
1 = Incorrecto: no demuestra conocimiento o el dato central es erróneo

REGLAS IMPORTANTES:
- Una respuesta corta y correcta (ej. "72 horas") merece un 3 o más si el dato es correcto
- Da crédito por paráfrasis y sinónimos — no exijas las palabras exactas
- Solo baja a 1-2 si hay errores factuales reales o desconocimiento genuino
- Los detalles secundarios (cargos adicionales, excepciones) son bonus, no requisito para pasar
- Si el vendedor tiene el dato principal correcto: mínimo 3

Responde ÚNICAMENTE con este JSON:
{
  "score": <entero del 1 al 5>,
  "reasoning": "<una oración explicando el puntaje>",
  "feedback": ["<punto 1, máx 20 palabras>", "<punto 2, máx 20 palabras>"]
}

- Si score >= 3: refuerza lo correcto y añade el detalle extra que completaría la respuesta
- Si score < 3: explica qué dato clave faltó o estaba incorrecto
- Siempre en español"""

            response = self.client.chat.completions.create(
                model=Config.OPENAI_GRADING_MODEL,
                max_tokens=400,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": user_prompt},
                ],
            )

            raw  = response.choices[0].message.content.strip()
            raw  = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
            data = json.loads(raw)

            score = max(1, min(5, int(data.get("score", 3))))
            feedback_bullets = "\n".join(
                f"• {t}" for t in data.get("feedback", []) if t
            )

            return {
                "score":      score,
                "reasoning":  data.get("reasoning", ""),
                "feedback":   feedback_bullets,
                "kb_used":    kb_text is not None,
            }

        except Exception as e:
            logger.error(f"[Grader] LLM call failed: {e}")
            return {
                "score":     round(keyword["score"]),
                "reasoning": "LLM no disponible — solo palabras clave.",
                "feedback":  self._fallback_feedback(keyword),
                "kb_used":   False,
            }

    def _fallback_feedback(self, keyword: Dict) -> str:
        lines = []
        if keyword["missed_concepts"]:
            lines.append(f"• Faltó mencionar: {', '.join(keyword['missed_concepts'][:3])}")
        if keyword["must_have_hits"]:
            lines.append(f"• Bien cubierto: {', '.join(keyword['must_have_hits'][:3])}")
        return "\n".join(lines) if lines else "• ¡Sigue practicando!"

    def _pass_state(self, score: int, must_hits: List[str]) -> PassState:
        if score >= 4:
            return PassState.PASS
        elif score >= 3:
            return PassState.BORDERLINE
        return PassState.FAIL

    # ------------------------------------------------------------------
    # LLM grading for multiple-choice and yes/no questions
    # ------------------------------------------------------------------

    def grade_closed_answer(
        self,
        question_prompt: str,
        answer_text: str,
        correct_answer: str,
        choices: Optional[List[Dict]] = None,
        question_type: str = "yes_no",
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """
        Grade a MC or yes/no answer.

        Pass/fail is determined by EXACT MATCH against the stored correct_answer
        — the question bank is the ground truth, the LLM cannot override it.
        The LLM is called only to generate a coaching explanation of why the
        correct answer is correct.
        """
        from handlers.conversations import _normalise_yesno

        expected = correct_answer.strip().lower()
        if question_type == "yes_no":
            expected = _normalise_yesno(expected)

        # ── Step 1: extract the user's intended answer via LLM ────────────
        # The LLM interprets natural language ("creo que la C", "sí señor") into
        # a canonical value (letter or si/no). It does NOT judge correctness.
        norm = self._extract_user_choice(answer_text, question_type, choices)

        is_correct = norm == expected

        # ── Step 2: build labels for display / LLM context ────────────────
        if question_type == "multiple_choice" and choices:
            choices_text = "\n".join(f"  {c['key']}) {c['text']}" for c in choices)
            correct_label = next(
                (f"{c['key']}) {c['text']}" for c in choices
                if c["key"].lower() == expected),
                correct_answer,
            )
            user_label = next(
                (f"{c['key']}) {c['text']}" for c in choices
                if c["key"].lower() == norm),
                answer_text,
            )
        else:
            choices_text  = ""
            correct_label = correct_answer
            user_label    = answer_text

        score      = 5 if is_correct else 0
        pass_state = PassState.PASS if is_correct else PassState.FAIL

        # ── Step 3: ask LLM only for the coaching explanation ─────────────
        feedback = self._explain_closed_answer(
            question_prompt, user_label, correct_label,
            choices_text, question_type, is_correct, tags,
        )

        return {
            "score_0_5":       score,
            "result":          "GOOD" if is_correct else "BAD",
            "pass_state":      pass_state,
            "rubric_hits":     {},
            "missed_concepts": [],
            "feedback":        feedback,
            "grader_trace":    {
                "method":         "exact_match + llm_explain",
                "user_chose":     norm,
                "correct_answer": expected,
            },
            "grading_method": "exact_match",
        }

    def _extract_user_choice(
        self,
        answer_text: str,
        question_type: str,
        choices: Optional[List[Dict]],
    ) -> str:
        """
        Use the LLM to extract what the user actually chose from their text.
        Returns a canonical value: a lowercase letter (a/b/c/d) for MC,
        or 'si'/'no' for yes/no.
        Falls back to regex if the LLM call fails.
        """
        try:
            if question_type == "multiple_choice":
                valid_letters = ", ".join(c["key"] for c in (choices or []))
                prompt = (
                    f"El vendedor respondió: \"{answer_text}\"\n\n"
                    f"Las opciones válidas son: {valid_letters}\n\n"
                    "¿Qué letra eligió el vendedor? Responde SOLO con la letra en minúscula "
                    "(una sola letra: a, b, c o d). Si no eligió ninguna letra válida, responde 'ninguna'.\n\n"
                    "JSON: {\"choice\": \"<letra>\"}"
                )
            else:  # yes_no
                prompt = (
                    f"El vendedor respondió: \"{answer_text}\"\n\n"
                    "¿Respondió Sí o No? Interpreta con juicio:\n"
                    "- 'sí', 'si', 'yes', 'claro', 'correcto', 'exacto', 'afirmativo' → 'si'\n"
                    "- 'no', 'nope', 'para nada', 'negativo', 'incorrecto' → 'no'\n\n"
                    "Responde SOLO con JSON: {\"choice\": \"si\"} o {\"choice\": \"no\"} o {\"choice\": \"ninguna\"}"
                )

            response = self.client.chat.completions.create(
                model=Config.OPENAI_GRADING_MODEL,
                max_tokens=20,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Extrae la respuesta del vendedor. Solo devuelve JSON."},
                    {"role": "user",   "content": prompt},
                ],
            )
            raw  = response.choices[0].message.content.strip()
            data = json.loads(raw)
            return data.get("choice", "ninguna").strip().lower()

        except Exception as e:
            logger.warning(f"[Grader] Choice extraction LLM failed, using regex: {e}")
            # Regex fallback
            from handlers.conversations import _normalise_yesno
            norm = answer_text.strip().lower()
            if question_type == "yes_no":
                return _normalise_yesno(norm)
            else:
                m = re.search(r"\b([a-dA-D])\b", answer_text)
                if not m:
                    m = re.match(r"^\s*([a-dA-D])", norm)
                return m.group(1).lower() if m else norm

    def _explain_closed_answer(
        self,
        question: str,
        user_label: str,
        correct_label: str,
        choices_text: str,
        question_type: str,
        is_correct: bool,
        tags: Optional[List[str]],
    ) -> str:
        """Ask the LLM for a coaching explanation only — it does NOT decide correctness."""
        kb_text = load_for_question(tags or []) if tags else None
        try:
            user_prompt = f"PREGUNTA: {question}\n\n"
            if choices_text:
                user_prompt += f"OPCIONES:\n{choices_text}\n\n"
            user_prompt += f"RESPUESTA CORRECTA: {correct_label}\n"
            user_prompt += f"RESPUESTA DEL VENDEDOR: {user_label}\n"
            user_prompt += f"¿ACERTÓ?: {'Sí' if is_correct else 'No'}\n\n"
            if kb_text:
                user_prompt += f"CONTEXTO OFICIAL:\n{kb_text}\n\n"

            user_prompt += """\
Genera 1-2 puntos de coaching en español explicando POR QUÉ la respuesta correcta es correcta.
NO decidas si el vendedor acertó — eso ya está determinado.

Responde ÚNICAMENTE con este JSON:
{
  "feedback": ["<punto 1, máx 25 palabras>", "<punto 2 opcional, máx 25 palabras>"]
}

- Si acertó: refuerza el concepto y añade un dato útil extra
- Si falló: explica qué hace correcta a la respuesta correcta, sin juzgar al vendedor
- Siempre en español, concreto y útil para un vendedor"""

            response = self.client.chat.completions.create(
                model=Config.OPENAI_GRADING_MODEL,
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": f"Eres un coach de ventas de {Config.COMPANY_NAME}. Responde en español con JSON válido."},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            raw  = response.choices[0].message.content.strip()
            raw  = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
            data = json.loads(raw)
            return "\n".join(f"• {t}" for t in data.get("feedback", []) if t)

        except Exception as e:
            logger.error(f"[Grader] LLM explanation failed: {e}")
            return ""  # No feedback is fine — correctness is already shown
