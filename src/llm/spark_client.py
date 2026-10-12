"""Genuine Ollama inference restricted to local Spark architectures."""

import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .schema import ANALYSIS_SCHEMA
from .policy import DEFAULT_POLICY, validate_policy

logger = logging.getLogger(__name__)

OFFICIAL_WEIGHT_DIGESTS = {
    "spark-drift:1.7b-q4": "902bde2522394954ac17821b3e5fd0df02defbc6944f122253f2580acf0503f4",
    "spark-drift:4b-q4": "adfcfa19a4ed6a5985da8bf565fe15f8e1a7e131d79bae2d19d48d1c40109428",
}


class SparkXClient:
    def __init__(self, model_path: str = "spark-drift:1.7b-q4", device: str = "auto",
                 base_url: str = "http://127.0.0.1:11435", policy: dict | None = None):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Only loopback model endpoints are permitted")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("Model endpoint must be a plain loopback origin")
        self.policy = validate_policy(DEFAULT_POLICY if policy is None else policy)
        self.base_url = base_url.rstrip("/")
        self.model_name = model_path
        self.device = device
        self._initialized = False
        self.last_error = ""
        self.last_response = ""
        self.last_thinking = ""
        self.details: dict[str, Any] = {}
        self.last_metrics: dict[str, Any] = {}

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        with httpx.Client(timeout=kwargs.pop("timeout", self.policy["timeout_seconds"]), trust_env=False) as client:
            response = client.request(method, self.base_url + path, **kwargs)
            response.raise_for_status()
            return response.json()

    def initialize(self) -> bool:
        self._initialized = False
        try:
            data = self._request("POST", "/api/show", timeout=5, json={"model": self.model_name})
            self.details = data.get("details", {})
            family = self.details.get("family", "").lower()
            expected_family, expected_digest = self.expected_identity()
            if family != expected_family and not (expected_family == 'spark' and 'spark' in family):
                raise ValueError(f"Expected {expected_family} architecture, got {family!r}")
            from_lines = [line.strip() for line in data.get("modelfile", "").splitlines()
                          if line.strip().startswith("FROM ")]
            if not from_lines or not from_lines[0].endswith("sha256-" + expected_digest):
                raise ValueError("Loaded model does not reference the verified official weight blob")
            self.details["weight_sha256"] = expected_digest
            self.details["runtime_version"] = self._request("GET", "/api/version", timeout=5).get("version")
            self._initialized = True
            self.last_error = ""
            return True
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self.last_error = str(exc)
            logger.warning("Local Spark unavailable: %s", exc)
            return False

    def expected_identity(self):
        expected_digest = OFFICIAL_WEIGHT_DIGESTS.get(self.model_name)
        if expected_digest is None:
            raise ValueError("Only the two verified official project imports are supported")
        return 'spark', expected_digest

    def generate(self, prompt: str, max_tokens: int = 1024,
                 temperature: float = 0.2, thinking: bool = False, **kwargs) -> str:
        self.last_response = ""
        self.last_thinking = ""
        self.last_metrics = {}
        self.last_error = ""
        if not self._initialized and not self.initialize():
            raise RuntimeError(f"Official model unavailable: {self.last_error}")
        start = time.perf_counter()
        try:
            data = self._request("POST", "/api/chat", json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False, "think": thinking, "format": ANALYSIS_SCHEMA,
                "keep_alive": f"{self.policy['keep_alive_minutes']}m",
                "options": {"num_predict": max_tokens, "num_ctx": 4096,
                            "temperature": temperature, "top_p": 0.95, "seed": 42},
            })
            text = data.get("message", {}).get("content", "")
            self.last_response = text
            self.last_thinking = data.get("message", {}).get("thinking", "")
            eval_duration = data.get("eval_duration", 0) / 1e9
            self.last_metrics = {
                "backend": "ollama", "model": data.get("model", self.model_name),
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "tokens_per_second": round(data.get("eval_count", 0) / eval_duration, 2) if eval_duration else None,
                "load_ms": data.get("load_duration", 0) / 1e6,
                "finish_reason": data.get("done_reason"), "runtime": self.details,
                "request_settings": {"thinking": thinking, "max_tokens": max_tokens, "context_length": 4096,
                                     "temperature": temperature, "top_p": 0.95, "seed": 42,
                                     "timeout_seconds": self.policy["timeout_seconds"],
                                     "keep_alive_minutes": self.policy["keep_alive_minutes"]},
            }
            if not text.strip():
                raise RuntimeError("Model returned an empty answer")
            if data.get("done_reason") == "length":
                raise RuntimeError("Model answer reached its token limit; no valid conclusion accepted")
            return text
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
            self.last_metrics.update(elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
                                     runtime=dict(self.details), error=self.last_error)
            raise RuntimeError(f"Local inference failed: {exc}") from exc

    def close(self) -> None:
        self._initialized = False


class SparkXClientFactory:
    _instance: SparkXClient | None = None

    @classmethod
    def get_client(cls, model_path: str = "spark-drift:1.7b-q4", device: str = "auto") -> SparkXClient:
        if cls._instance is None or cls._instance.model_name != model_path:
            cls._instance = SparkXClient(model_path, device)
            cls._instance.initialize()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        if cls._instance:
            cls._instance.close()
        cls._instance = None
