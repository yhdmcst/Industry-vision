"""Replay fixed prompts with thinking enabled; retain successes and failures."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import ResponseParser, SparkXClient
from src.llm.evidence_guard import evidence_warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="artifacts/benchmark.json")
    parser.add_argument("--model", default="spark-drift:4b-q4")
    parser.add_argument("--scenarios", nargs="+", default=["focus_change", "light_fade"])
    parser.add_argument("--output", default="artifacts/thinking-comparison.json")
    parser.add_argument("--max-tokens", type=int, default=3072)
    args = parser.parse_args()
    source = ROOT / args.input
    data = json.loads(source.read_text(encoding="utf-8"))
    results = []
    for case in data["cases"]:
        if case["scenario_ground_truth"] not in args.scenarios:
            continue
        client = SparkXClient(args.model)
        result = {
            "scenario": case["scenario_ground_truth"],
            "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
            "fast_result": {"model": case["inference"]["model"], "analysis": case["analysis"],
                            "inference": case["inference"]},
        }
        try:
            raw = client.generate(case["prompt"], max_tokens=args.max_tokens, temperature=0.2, thinking=True)
            analysis = ResponseParser.parse_drift_analysis(raw)
            result.update({"status": "completed", "analysis": analysis,
                           "evidence_warnings": evidence_warnings(case["snapshot"], analysis)})
        except (RuntimeError, ValueError) as exc:
            result.update({"status": "error", "error": str(exc)})
        result["raw_response"] = client.last_response
        result["inference"] = client.last_metrics
        result["thinking_characters"] = len(client.last_thinking)
        results.append(result)
        print(json.dumps({
            "scenario": result["scenario"], "status": result["status"],
            "type": result.get("analysis", {}).get("drift_type"),
            "elapsed_ms": result["inference"].get("elapsed_ms"),
            "thinking_characters": result["thinking_characters"],
        }, ensure_ascii=True), flush=True)
    target = ROOT / args.output
    target.write_text(json.dumps({
        "observed": time.time(), "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model": args.model, "results": results,
        "limitations": ["Debugging cases, not a held-out evaluation.",
                        "Different model comparisons confound size and thinking; use the same model for a mode ablation."],
    }, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return int(any(result["status"] == "error" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
