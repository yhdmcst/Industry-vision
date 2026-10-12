"""Generate explicitly synthetic inspection predictions for an imported dataset."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.datasets import digest


def create_results(dataset: dict, output: Path) -> Path:
    records = []
    evaluation = 0
    for sample in dataset["samples"]:
        base = {"sample_id": sample["id"], "image_sha256": sample["sha256"]}
        if sample["split"] == "baseline":
            records.append({**base, "status": "ok", "detected": True, "confidence": 0.97,
                            "is_ng": False, "defect_types": []})
            continue
        evaluation += 1
        if evaluation == 1:
            continue  # Explicitly exercise missing records.
        if evaluation in (2, 3):
            records.append({**base, "status": "timeout" if evaluation == 2 else "error",
                            "error": "合成测试：上游超时" if evaluation == 2 else "合成测试：推理失败"})
        else:
            records.append({**base, "status": "ok", "detected": True, "confidence": 0.93,
                            "is_ng": True, "defect_types": ["demo_scratch"]})
    package = {"schema_version": 1, "dataset_id": digest(dataset),
               "producer": {"name": "Synthetic inspection fixture", "version": "1.0",
                            "provenance": "synthetic_fixture", "score_semantics": "decision_confidence"},
               "results": records}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Imported dataset's manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new path")
    print(create_results(json.loads(args.manifest.read_text(encoding="utf-8")), args.output).resolve())
