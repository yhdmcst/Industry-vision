"""Reject malformed answers instead of inventing successful diagnoses."""

import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from .schema import ANALYSIS_SCHEMA


class ResponseParser:
    @staticmethod
    def parse_json_response(response: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(response)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            for index, char in enumerate(response):
                if char != "{":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(response[index:])
                    if isinstance(parsed, dict) and "drift_detected" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue
            return None

    @staticmethod
    def parse_drift_analysis(response: str) -> dict[str, Any]:
        parsed = ResponseParser.parse_json_response(response)
        if parsed is None:
            raise ValueError("Model answer does not contain a JSON object")
        errors = sorted(Draft202012Validator(ANALYSIS_SCHEMA).iter_errors(parsed), key=lambda e: str(e.path))
        if errors:
            raise ValueError("Invalid model answer: " + errors[0].message)
        if not math.isfinite(parsed["confidence_score"]):
            raise ValueError("confidence_score must be finite")
        return parsed

    @staticmethod
    def validate_response(parsed: dict[str, Any]) -> tuple[bool, str]:
        try:
            ResponseParser.parse_drift_analysis(json.dumps(parsed, allow_nan=False))
            return True, "Valid"
        except (TypeError, ValueError) as exc:
            return False, str(exc)
