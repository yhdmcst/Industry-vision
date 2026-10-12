"""A shared, strict contract for model generation and validation."""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "drift_detected": {"type": "boolean"},
        "drift_type": {"type": "string", "enum": [
            "none", "optical", "mechanical", "illumination", "product", "unknown",
        ]},
        "root_cause": {"type": "string", "minLength": 6, "maxLength": 1000},
        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
        "recommendations": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
        "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "alternative_causes": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "verification_steps": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
        "requires_human_review": {"type": "boolean", "const": True},
    },
    "required": [
        "confidence_score", "drift_detected", "drift_type", "root_cause",
        "evidence", "recommendations", "urgency", "alternative_causes",
        "verification_steps", "requires_human_review",
    ],
    "additionalProperties": False,
}
