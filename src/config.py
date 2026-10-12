"""Project-relative, validated runtime settings."""

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_settings() -> dict:
    with (ROOT / "config/system_config.yaml").open(encoding="utf-8") as stream:
        settings = yaml.safe_load(stream)
    if settings["safety"]["automatic_actuation"] or not settings["safety"]["human_review_only"]:
        raise ValueError("Automatic actuation is not supported")
    if not 10 <= settings["monitoring"]["window_size"] <= 1000:
        raise ValueError("Invalid monitoring window size")
    if not 10 <= settings["monitoring"]["baseline_samples"] <= 100:
        raise ValueError("Invalid baseline sample count")
    if not 0.2 <= settings["monitoring"]["refresh_seconds"] <= 10:
        raise ValueError("Invalid monitoring refresh interval")
    recovery_samples = settings["monitoring"]["alert_recovery_samples"]
    if type(recovery_samples) is not int or not 1 <= recovery_samples <= 100:
        raise ValueError("Invalid alert recovery sample count")
    database = (ROOT / settings["storage"]["database"]).resolve()
    if not database.is_relative_to(ROOT):
        raise ValueError("Database must be within this project")
    return settings
