"""Flag contradictions against measured evidence, without rewriting model output."""

from typing import Any


def evidence_warnings(snapshot: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    metrics = snapshot["current_metrics"]
    changes = metrics["relative_changes"]
    registration = metrics.get("registration", {})
    sharpness_drop = changes.get("sharpness_change", 0) < -0.3
    brightness_shift = abs(changes.get("brightness_change", 0)) > 0.2
    position_shift = (
        registration.get("response", 0) > 0.25
        and (registration.get("shift_x", 0) ** 2 + registration.get("shift_y", 0) ** 2) ** 0.5 > 8
    )
    warnings = []
    if (analysis["drift_detected"] and analysis["drift_type"] == "none") or (
            not analysis["drift_detected"] and analysis["drift_type"] not in ('none', 'unknown')):
        warnings.append("模型漂移标记与原因分类相互矛盾；保留原始回答，需人工核查。")
    quality = metrics["image_quality"]
    if quality.get("contrast", 0) < 1 or not 10 < quality.get("brightness", 0) < 245:
        warnings.append("当前图像过暗、过曝或纹理不足，不能据此确认设备或产品根因。")
    if analysis["drift_type"] == "mechanical" and registration.get("response", 0) <= 0.25:
        warnings.append("配准响应不足，位移估计不可靠；不能据此确认机械漂移。")
    if analysis["drift_type"] == "mechanical" and sharpness_drop and not position_shift:
        warnings.append("清晰度已显著下降而未测到可靠位置变化；机械解释尚未排除失焦或污染。")
    if (sharpness_drop or brightness_shift or position_shift) and (
            not analysis["drift_detected"] or analysis["drift_type"] == "none"):
        warnings.append("测量指标已越过观测阈值，模型却报告未见漂移；需核查漏报。")
    if analysis["drift_type"] == "optical" and brightness_shift and not position_shift:
        warnings.append("亮度显著变化同时会影响清晰度；单一光学解释未排除光照或曝光因素。")
    if position_shift and analysis["drift_type"] not in ("mechanical", "unknown"):
        warnings.append("可靠配准显示明显位移，模型解释未优先覆盖位置或工装变化。")
    if analysis["drift_type"] == "optical" and not sharpness_drop and changes.get("noise_change", 0) <= 2:
        warnings.append("未测到显著清晰度下降或噪声代理增加，单一光学解释缺少观测支持。")
    consistency = metrics.get("consistency", {})
    if snapshot.get("detection_availability", {}).get("unavailable", 0):
        warnings.append("当前窗口存在缺失、失败或超时的检测结果；NG 与置信度统计不可用，不能据此确认正常或产品变化。")
    ng_rate = consistency.get("ng_rate")
    explanation = " ".join([
        analysis["root_cause"], *analysis["evidence"],
    ])
    if ng_rate == 0 and any(phrase in explanation for phrase in ("NG上升", "NG率上升", "NG增加", "NG率增加")):
        warnings.append("当前窗口 NG 比例为零，模型输出却声称 NG 上升；证据引用不一致。")
    return warnings
