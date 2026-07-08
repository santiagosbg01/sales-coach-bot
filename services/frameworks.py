"""SPIN and Challenger framework evaluation using Claude Haiku."""
import re
import json
from typing import Dict
from anthropic import Anthropic
from config import Config


class FrameworkEvaluator:
    """Evaluates answers using SPIN and Challenger frameworks (Haiku)."""

    def __init__(self):
        self.client = Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    def evaluate(
        self,
        question_prompt: str,
        answer_text: str,
        enable_spin: bool = True,
        enable_challenger: bool = True,
    ) -> Dict:
        result = {}

        if enable_spin:
            spin = self._spin(question_prompt, answer_text)
            result.update(spin_score=spin["score"], spin_breakdown=spin["breakdown"],
                          spin_tips=spin["tips"])

        if enable_challenger:
            ch = self._challenger(question_prompt, answer_text)
            result.update(challenger_score=ch["score"], challenger_breakdown=ch["breakdown"],
                          challenger_tips=ch["tips"])

        result["bonus_score"] = (result.get("spin_score") or 0) + (result.get("challenger_score") or 0)
        return result

    # ------------------------------------------------------------------
    def _spin(self, question: str, answer: str) -> Dict:
        prompt = f"""Eres un experto en metodología de ventas. Evalúa en español.

PREGUNTA: {question}
RESPUESTA: {answer}

Puntúa cada componente SPIN como 0 (ausente) o 1 (presente):
- situation: se exploran hechos / situación actual
- problem: se abordan puntos de dolor / desafíos
- implication: se exploran las consecuencias del problema
- need_payoff: se articula el valor de resolver el problema

Responde ÚNICAMENTE con JSON válido y el consejo en español:
{{"situation":0,"problem":0,"implication":0,"need_payoff":0,"tips":"<un consejo de coaching en español>"}}"""

        return self._call(prompt, "spin", ["situation", "problem", "implication", "need_payoff"])

    def _challenger(self, question: str, answer: str) -> Dict:
        prompt = f"""Eres un experto en metodología de ventas. Evalúa en español.

PREGUNTA: {question}
RESPUESTA: {answer}

Puntúa cada componente Challenger como 0 (ausente) o 1 (presente):
- teach: ofrece una perspectiva única o desafía el pensamiento del prospecto
- tailor: personalizado al contexto / industria del cliente
- take_control: asertivo, conduce la conversación hacia adelante

Responde ÚNICAMENTE con JSON válido y el consejo en español:
{{"teach":0,"tailor":0,"take_control":0,"tips":"<un consejo de coaching en español con ejemplo de frase>"}}"""

        return self._call(prompt, "challenger", ["teach", "tailor", "take_control"])

    def _call(self, prompt: str, framework: str, keys: list) -> Dict:
        try:
            msg = self.client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=200,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
            data = json.loads(raw)
            breakdown = {k: int(data.get(k, 0)) for k in keys}
            return {"score": sum(breakdown.values()), "breakdown": breakdown,
                    "tips": data.get("tips", "")}
        except Exception as e:
            print(f"[FrameworkEvaluator] {framework} failed: {e}")
            breakdown = {k: 0 for k in keys}
            return {"score": 0, "breakdown": breakdown, "tips": "Evaluation unavailable."}
