"""One image usability policy for acquisition preflight and reference publication."""

import numpy as np


def quality_reasons(quality: dict[str, float]) -> list[str]:
    reasons = []
    if not all(np.isfinite(value) for value in quality.values()):
        reasons.append("non_finite_metrics")
    if quality["brightness"] <= 10:
        reasons.append("underexposure")
    if quality["brightness"] >= 245:
        reasons.append("overexposure")
    if quality["contrast"] < 1:
        reasons.append("no_texture")
    return reasons
