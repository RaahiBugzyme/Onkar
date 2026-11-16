"""Safe natural-language preference interpretation with an injectable Gen AI client."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Optional

from .preferences import normalize_preferences

SUPPORTED_FIELDS = ("region", "religion", "profession")
_CLARIFICATION = "Do you want a region, religion, or profession, and what exact value should be used?"
_RESPONSE_SCHEMA = {
    "type": "object",
    "propertyOrdering": ["status", "question", "preferences"],
    "properties": {
        "status": {"type": "string", "enum": ["clarification_required", "confirmation_required"]},
        "question": {"type": "string"},
        "preferences": {
            "type": "object",
            "propertyOrdering": ["criteria", "hard_exclusions"],
            "properties": {
                "criteria": {
                    "type": "object",
                    "properties": {
                        field: {
                            "type": "object",
                            "propertyOrdering": ["values", "hard"],
                            "properties": {
                                "values": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                                "hard": {"type": "boolean"},
                            },
                            "required": ["values", "hard"],
                        }
                        for field in SUPPORTED_FIELDS
                    },
                },
                "hard_exclusions": {
                    "type": "object",
                    "properties": {
                        field: {
                            "type": "object",
                            "propertyOrdering": ["values"],
                            "properties": {"values": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                            "required": ["values"],
                        }
                        for field in SUPPORTED_FIELDS
                    },
                },
            },
        },
    },
    "required": ["status"],
}


def _local_interpret(request: str) -> Dict[str, Any]:
    text = request.strip().lower()
    if not text:
        return {"status": "clarification_required", "question": _CLARIFICATION}
    if "konkani" in text:
        return {
            "status": "clarification_required",
            "question": "Do you mean Konkani as a religion/language or a specific region? Please provide the exact field and value.",
        }

    field = next((f for f in SUPPORTED_FIELDS if f in text), None)
    exclusion = re.search(r"\b(?:exclude|avoid|not|don't want)\s+(?P<value>[a-z][a-z -]+?)(?:\s+(?:region|religion|profession))?(?:$|\.)", text)
    if exclusion and field:
        value = re.sub(r"\s+(region|religion|profession)$", "", exclusion.group("value")).strip()
        value = re.sub(r"^the\s+", "", value).strip()
        return {"status": "confirmation_required", "preferences": {"hard_exclusions": {field: {"values": [value]}}}}

    preference = re.search(r"\b(?:prefer|like|want)\s+(?:people|someone|a person)?\s*(?:from|who is|working as)?\s*(?P<value>[a-z][a-z -]+?)(?:\s+(?:region|religion|profession))?(?:$|\.)", text)
    if preference and field and preference.group("value").strip() not in {"my", "my region", "my religion"}:
        value = re.sub(r"\s+(region|religion|profession)$", "", preference.group("value")).strip()
        return {"status": "confirmation_required", "preferences": {"criteria": {field: {"values": [value], "hard": False}}}}
    return {"status": "clarification_required", "question": _CLARIFICATION}


class GeminiProviderUnavailable(RuntimeError):
    """Raised when Gemini cannot be configured or reached."""


class GeminiPreferenceClient:
    """Backend-only adapter for the official google-genai SDK."""

    def __init__(self, api_key: str, model: Optional[str] = None):
        try:
            from google import genai
        except ImportError as error:
            raise GeminiProviderUnavailable("google-genai is not installed") from error
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        try:
            self._client = genai.Client(api_key=api_key)
        except Exception as error:
            raise GeminiProviderUnavailable("Gemini client could not be initialized") from error

    def __call__(self, request: str) -> Any:
        prompt = (
            "Interpret this dating preference request. Return JSON only with exactly one of these shapes: "
            '{"status":"clarification_required","question":"..."} or '
            '{"status":"confirmation_required","preferences":{...}}. '
            "Only use region, religion, and profession. Put exclusions in hard_exclusions; "
            "put non-exclusive preferences in criteria with hard:false. Never infer a value or equate "
            "similarly named terms such as Konkani and Konkan; ask a clarification instead. "
            "Do not include markdown or extra keys. Request: " + request
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": _RESPONSE_SCHEMA,
                },
            )
            return _parse_json_response(getattr(response, "text", None))
        except (GeminiProviderUnavailable, ValueError):
            raise
        except Exception as error:
            raise GeminiProviderUnavailable("Gemini request failed") from error


def _parse_json_response(text: str) -> Dict[str, Any]:
    if not isinstance(text, str):
        raise ValueError("Gemini response must be JSON text")
    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini response is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Gemini response must be a JSON object")
    return value


def _validate_ai_shape(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Reject provider output that is outside the deliberately small contract."""
    if set(raw) - {"status", "question", "preferences"}:
        raise ValueError("AI response contains unsupported fields")
    if raw["status"] == "clarification_required":
        if set(raw) - {"status", "question"}:
            raise ValueError("clarification response contains unsupported fields")
        return raw
    preferences = raw.get("preferences")
    if not isinstance(preferences, dict) or set(preferences) - {"criteria", "hard_exclusions"}:
        raise ValueError("AI preferences must contain only criteria or hard_exclusions")
    cleaned_preferences: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for group, specs in preferences.items():
        if not isinstance(specs, dict):
            raise ValueError("AI preference groups must be objects")
        for field, spec in specs.items():
            if field not in SUPPORTED_FIELDS or not isinstance(spec, dict):
                raise ValueError("AI response contains an unsupported preference field")
            allowed = {"values", "hard"} if group == "criteria" else {"values"}
            if set(spec) - allowed or not isinstance(spec.get("values"), list):
                raise ValueError("AI response contains an unsupported preference operator")
            if group == "criteria" and not isinstance(spec.get("hard"), bool):
                raise ValueError("AI criteria must declare hard as a boolean")
            if any(not isinstance(value, str) or not value.strip() for value in spec["values"]):
                raise ValueError("AI response contains an invalid preference value")
            if not spec["values"]:
                continue
            cleaned_preferences.setdefault(group, {})[field] = dict(spec)
    return {**raw, "preferences": cleaned_preferences}


def _configured_client() -> Optional[Callable[[str], Any]]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        return GeminiPreferenceClient(api_key)
    except GeminiProviderUnavailable:
        return None


def interpret_preference_request(request: str, ai_client: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    if not isinstance(request, str):
        raise ValueError("request must be text")
    client = ai_client or _configured_client()
    if client is None:
        raw = _local_interpret(request)
    else:
        try:
            raw = client(request)
        except GeminiProviderUnavailable:
            raw = _local_interpret(request)
    if not isinstance(raw, dict) or raw.get("status") not in {"clarification_required", "confirmation_required"}:
        raise ValueError("AI response must be a structured clarification or interpretation")
    raw = _validate_ai_shape(raw)
    if raw["status"] == "clarification_required":
        if not isinstance(raw.get("question"), str) or not raw["question"].strip():
            raise ValueError("AI clarification must include a question")
        return {"status": raw["status"], "question": raw["question"]}
    normalized, warnings = normalize_preferences(raw.get("preferences"))
    if warnings or not (normalized["hard_exclusions"] or normalized["criteria"]):
        raise ValueError("AI response contains unsupported or invalid preferences")
    return {"status": "confirmation_required", "preferences": normalized, "confirmed": False}
