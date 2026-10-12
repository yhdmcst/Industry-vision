"""Descriptive replay evaluation against imported annotations, without inference or actuation."""

from collections import Counter
import hashlib
from pathlib import Path

from src.datasets import digest
from src.dataset_checks import partition_checks

CAUSES = ("none", "optical", "illumination", "mechanical", "product")
EVALUATION_SOURCE_SHA256 = digest({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in [Path(__file__), Path(__file__).with_name('dataset_checks.py')]})


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def cohort(sample: dict) -> str:
    if sample["origin"] == "synthetic":
        return "synthetic"
    return "real_unmodified" if sample["perturbation"] == "none" else "real_perturbed"


def summarize(rows: list[dict], external: bool) -> dict:
    processed = [r for r in rows if r["processed"]]
    labeled = [r for r in rows if r["defect_label"] != "unknown"]
    eligible = [r for r in labeled if r["processed"]]
    scored = [r for r in eligible if external and r["detection_status"] == "ok"]
    tp = sum(r["defect_label"] == "defect" and r["is_ng"] for r in scored)
    tn = sum(r["defect_label"] == "normal" and not r["is_ng"] for r in scored)
    fp = sum(r["defect_label"] == "normal" and r["is_ng"] for r in scored)
    fn = sum(r["defect_label"] == "defect" and not r["is_ng"] for r in scored)
    cause_labeled = [r for r in rows if r["cause_label"] in CAUSES]
    classified = [r for r in cause_labeled if r["rule_prediction"] in CAUSES]
    matrix = {label: {prediction: 0 for prediction in (*CAUSES, "unknown")} for label in CAUSES}
    for r in cause_labeled:
        if r["processed"]:
            matrix[r["cause_label"]][r["rule_prediction"]] += 1
    correct = sum(r["cause_label"] == r["rule_prediction"] for r in classified)
    counts = Counter(r["detection_status"] for r in processed)
    return {
        "total": len(rows), "processed": len(processed), "not_run": len(rows) - len(processed),
        "detection_counts": {s: counts[s] for s in ("ok", "missing", "error", "timeout")},
        "inspection": {
            "enabled": external, "labeled": len(labeled), "unlabeled": len(rows) - len(labeled),
            "labeled_processed": len(eligible), "assessed": len(scored),
            "unavailable_labeled": sum(r["detection_status"] != "ok" for r in eligible),
            "not_run_labeled": len(labeled) - len(eligible),
            "coverage": ratio(len(scored), len(labeled)) if external else None,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "label_agreement": ratio(tp + tn, len(scored)),
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "false_positive_rate": ratio(fp, fp + tn), "miss_rate": ratio(fn, fn + tp),
        },
        "rule": {
            "labeled": len(cause_labeled), "unlabeled": len(rows) - len(cause_labeled),
            "assessed": len(classified),
            "abstained": sum(r["processed"] and r["rule_prediction"] == "unknown" for r in cause_labeled),
            "not_run_labeled": sum(not r["processed"] for r in cause_labeled),
            "coverage": ratio(len(classified), len(cause_labeled)),
            "label_agreement": ratio(correct, len(classified)), "correct": correct, "matrix": matrix,
        },
    }


def evaluate_replay(replay: dict) -> dict:
    """Use only frozen exported evidence. Label values never enter the monitoring path."""
    manifest, config = replay["dataset"], replay["config"]
    samples = [s for s in manifest["samples"] if s["split"] == "evaluation"]
    if [s["id"] for s in samples] != config["evaluation_ids"]:
        raise ValueError("评估顺序与固定回放配置不匹配")
    results = replay["results"]
    if len(results) > len(samples):
        raise ValueError("回放结果超过评估样本数量")
    for sample, result in zip(samples, results):
        if result["sample_id"] != sample["id"] or result["image_sha256"] != sample["sha256"]:
            raise ValueError("评估结果与样本或图像摘要不匹配")
    source = config.get("inspection_source", {"kind": "reference_residual_demo", "provenance": "synthetic_fixture"})
    external = source["kind"] == "external_results"
    rows = []
    image_indexes = {s["id"]: i for i, s in enumerate(manifest["samples"])}
    for index, sample in enumerate(samples):
        result = results[index] if index < len(results) else None
        detection = result["detection"] if result else None
        prediction = result["rule_report"]["drift_type"] if result else None
        # A normal-looking image before consistency readiness cannot establish a stable system.
        if result and (prediction == "unknown" or (prediction == "none" and result["warmup"])):
            prediction = "unknown"
        rows.append({
            "sample_id": sample["id"], "image_sha256": sample["sha256"],
            "image_index": image_indexes[sample["id"]], "batch": sample["batch"],
            "cohort": cohort(sample), "perturbation": sample["perturbation"],
            "defect_label": sample["label"]["defect"], "cause_label": sample["label"]["cause"],
            "processed": result is not None, "detection_status": detection.get("status", "ok") if detection else None,
            "is_ng": detection["is_ng"] if detection else None,
            "confidence": detection["confidence"] if detection else None, "rule_prediction": prediction,
            "anomaly_score": detection.get('metadata', {}).get('result', {}).get('anomaly_score') if detection else None,
            "alignment": detection.get('metadata', {}).get('result', {}).get('alignment') if detection else None,
            "inspection_mismatch": bool(external and detection and detection.get("status", "ok") == "ok"
                                        and sample["label"]["defect"] != "unknown"
                                        and detection["is_ng"] != (sample["label"]["defect"] == "defect")),
            "rule_mismatch": bool(prediction in CAUSES and sample["label"]["cause"] in CAUSES
                                  and prediction != sample["label"]["cause"]),
        })
    checks = partition_checks(manifest['samples'])
    duplicates = checks['baseline_duplicate_ids']
    repeated = checks['evaluation_duplicate_ids']
    shared_batches = checks['shared_batches']
    warnings = ["标签为导入者声明，匹配率只描述当前样本；相邻帧和重复图像不构成独立试验。"]
    if not replay["replay"]["completed"]:
        warnings.append("回放未完成；报告包含未运行样本，不能作为完整评估结论。")
    if duplicates:
        warnings.append(f"{len(duplicates)} 个评估样本与基线图像摘要重复；不能据此宣称盲测效果。")
    if repeated:
        warnings.append(f"{len(repeated)} 个评估样本存在重复图像，样本数量不等于独立观测数量。")
    if checks['shared_batch_keys']:
        warnings.append("基线与评估样本存在共同批次，尚未证明按采集批次隔离。")
    if not external:
        warnings.append("参考残差为演示代理，不计算独立缺陷标签的分类指标。")
    elif source["provenance"] == "synthetic_fixture":
        warnings.append("检测结果为合成夹具；指标仅用于验证流程。")
    report = {
        "schema_version": 1, "session": replay["session"], "dataset_id": config["dataset_id"],
        "dataset_name": manifest["name"], "completed": replay["replay"]["completed"],
        "fingerprint": replay["replay"]["fingerprint"], "results_sha256": replay["results_sha256"],
        "inspection_source": source, "label_provenance": replay["label_provenance"],
        "scope": "Descriptive annotation agreement; no held-out accuracy, model evaluation or independent field validation claim.",
        "evaluation_source_sha256": EVALUATION_SOURCE_SHA256,
        "summary": summarize(rows, external),
        "groups": [{"batch": batch, "cohort": group, "summary": summarize(subset, external)}
                   for batch, group in sorted({(r["batch"], r["cohort"]) for r in rows})
                   if (subset := [r for r in rows if r["batch"] == batch and r["cohort"] == group])],
        "leakage": {"baseline_duplicate_ids": duplicates, "evaluation_duplicate_ids": repeated,
                    "shared_batches": shared_batches,
                    "shared_batch_keys": checks['shared_batch_keys'],
                    "unique_evaluation_images": checks['unique_evaluation_images']},
        "warnings": warnings, "samples": rows,
    }
    return {**report, "report_sha256": digest(report)}


def compare_replays(left: dict, right: dict) -> dict:
    """Compare only like-for-like input/config; detector/result version may change."""
    reports = [evaluate_replay(run) for run in (left, right)]
    reasons = []
    if left["session"] == right["session"]:
        reasons.append("请选择两个不同的回放会话")
    keys = sorted(set(left["config"]) | set(right["config"]))
    for key in keys:
        if key not in ("detector", "inspection_source") and left["config"].get(key) != right["config"].get(key):
            reasons.append(f"配置不一致：{key}")
    # Old exports without a source digest cannot establish comparable software.
    if not left["config"].get("measurement_source_sha256") or not right["config"].get("measurement_source_sha256"):
        reasons.append("缺少测量源码摘要，不能确认实现一致")
    if ([(r["sample_id"], r["image_sha256"]) for r in reports[0]["samples"]]
            != [(r["sample_id"], r["image_sha256"]) for r in reports[1]["samples"]]):
        reasons.append("样本或图像摘要不一致")
    details = []
    binary_enabled = all(r["inspection_source"]["kind"] == "external_results" for r in reports)
    if not reasons:
        for a, b in zip(reports[0]["samples"], reports[1]["samples"]):
            if not a["processed"] or not b["processed"]:
                continue
            both_ok = binary_enabled and a["detection_status"] == b["detection_status"] == "ok"
            details.append({
                "sample_id": a["sample_id"], "image_index": a["image_index"], "batch": a["batch"],
                "cohort": a["cohort"], "defect_label": a["defect_label"], "cause_label": a["cause_label"],
                "left_status": a["detection_status"], "right_status": b["detection_status"],
                "left_ng": a["is_ng"], "right_ng": b["is_ng"],
                "left_rule": a["rule_prediction"], "right_rule": b["rule_prediction"],
                "status_changed": a["detection_status"] != b["detection_status"],
                "verdict_changed": a["is_ng"] != b["is_ng"] if both_ok else None,
                "rule_changed": a["rule_prediction"] != b["rule_prediction"],
            })
    paired_ids = {d["sample_id"] for d in details}
    report = {
        "schema_version": 1, "comparable": not reasons, "reasons": reasons,
        "left": reports[0], "right": reports[1], "paired": len(details),
        "left_only": reports[0]["summary"]["processed"] - len(details),
        "right_only": reports[1]["summary"]["processed"] - len(details),
        "both_completed": all(r["completed"] for r in reports),
        "binary_enabled": binary_enabled,
        "both_ok": sum(d["verdict_changed"] is not None for d in details),
        "verdict_changes": sum(d["verdict_changed"] is True for d in details),
        "status_changes": sum(d["status_changed"] for d in details),
        "rule_changes": sum(d["rule_changed"] for d in details), "samples": details,
        "paired_summaries": [summarize([r for r in evaluation["samples"]
                                         if r["sample_id"] in paired_ids],
                                        evaluation["inspection_source"]["kind"] == "external_results")
                             for evaluation in reports] if not reasons else None,
        "scope": "Paired descriptive differences only; no significance, causal benefit or score-calibration claim.",
    }
    return {**report, "report_sha256": digest(report)}
