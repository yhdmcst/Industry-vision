"""Pinned independent research model. The workstation remains restricted to official Spark."""
import json
from pathlib import Path

from .spark_client import SparkXClient

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT/'models/research-qwen3-4b.json').read_bytes())


class ResearchClient(SparkXClient):
    def expected_identity(self):
        if self.model_name != BASELINE['model_name']:
            raise ValueError('Only the pinned independent research baseline is supported')
        return BASELINE['family'], BASELINE['sha256']
