"""
检测一致性跟踪模块

跟踪检测系统的一致性指标：
- 检测置信度的时序分布
- NG率的趋势分析
- 检测结果的稳定性
"""

import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from collections import deque
import logging
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyMetrics:
    """一致性指标"""
    confidence_mean: float | None
    confidence_std: float | None
    confidence_min: float | None
    confidence_max: float | None
    ng_rate: float
    detection_rate: float
    stability_score: float | None  # No confidence statistics for uncalibrated anomaly scores.

    def to_dict(self) -> Dict[str, float | None]:
        return {
            'confidence_mean': self.confidence_mean,
            'confidence_std': self.confidence_std,
            'confidence_min': self.confidence_min,
            'confidence_max': self.confidence_max,
            'ng_rate': self.ng_rate,
            'detection_rate': self.detection_rate,
            'stability_score': self.stability_score,
        }


@dataclass
class DetectionRecord:
    """单次检测记录"""
    timestamp: float
    detected: bool | None
    confidence: float | None
    is_ng: bool | None = False  # 是否判定为NG；不可用结果为 None
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"


class ConsistencyTracker:
    """检测一致性跟踪器"""

    def __init__(self, window_size: int = 100):
        """
        Args:
            window_size: 滑动窗口大小
        """
        self.window_size = window_size
        if window_size < 10:
            raise ValueError("window_size must be at least 10")
        self.records: deque = deque(maxlen=window_size)
        self.baseline: Optional[ConsistencyMetrics] = None
        self._total_count = 0

    def add_record(self, record: DetectionRecord):
        """添加检测记录"""
        if record.status not in ("ok", "missing", "error", "timeout"):
            raise ValueError("Unknown detection status")
        if record.status != "ok":
            if any(value is not None for value in (record.confidence, record.detected, record.is_ng)):
                raise ValueError("Unavailable detections must not contain a verdict")
        elif record.confidence is None and record.metadata.get('producer', {}).get('score_semantics') != 'anomaly_score':
            raise ValueError("Missing confidence without declared anomaly-score semantics")
        elif record.confidence is not None and (not np.isfinite(record.confidence) or not 0 <= record.confidence <= 1):
            raise ValueError("confidence must be finite and between 0 and 1")
        elif record.detected is None or record.is_ng is None:
            raise ValueError("Successful detections must contain a verdict")
        self.records.append(record)
        self._total_count += 1

    def availability(self) -> Dict[str, Any]:
        counts = {status: sum(r.status == status for r in self.records)
                  for status in ("ok", "missing", "error", "timeout")}
        return {"total": len(self.records), "valid": counts["ok"],
                "unavailable": len(self.records) - counts["ok"], "counts": counts,
                "ready": len(self.records) >= 10 and counts["ok"] == len(self.records)}

    def calculate_metrics(self) -> Optional[ConsistencyMetrics]:
        """计算当前窗口的一致性指标"""
        if not self.availability()["ready"]:
            logger.debug("检测窗口未就绪：数量不足或存在不可用结果")
            return None

        confidences = [r.confidence for r in self.records]
        detected_count = sum(1 for r in self.records if r.detected)
        ng_count = sum(1 for r in self.records if r.is_ng)

        # 置信度统计
        has_confidence = all(value is not None for value in confidences)
        confidence_mean = float(np.mean(confidences)) if has_confidence else None
        confidence_std = float(np.std(confidences)) if has_confidence else None
        confidence_min = float(np.min(confidences)) if has_confidence else None
        confidence_max = float(np.max(confidences)) if has_confidence else None

        # NG率和检测率
        ng_rate = ng_count / len(self.records)
        detection_rate = detected_count / len(self.records)

        # 稳定性评分（基于置信度的变异系数）
        cv = confidence_std / confidence_mean if has_confidence and confidence_mean > 0 else 1.0
        stability_score = 1.0 / (1.0 + cv) if has_confidence else None

        return ConsistencyMetrics(
            confidence_mean=confidence_mean,
            confidence_std=confidence_std,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            ng_rate=ng_rate,
            detection_rate=detection_rate,
            stability_score=stability_score
        )

    def set_baseline(self, records: List[DetectionRecord]) -> ConsistencyMetrics:
        """从历史记录设置基线"""
        if len(records) < 10:
            raise ValueError(f"基线记录数量不足 ({len(records)} < 10)")

        if any(record.status != "ok" for record in records):
            raise ValueError("基线检测结果必须完整且成功")
        # Reference statistics use every baseline sample, not only the current window's tail.
        temp_records, total_count = self.records, self._total_count
        self.records = deque()
        try:
            for record in records:
                self.add_record(record)
            baseline = self.calculate_metrics()
            if baseline is None:
                raise ValueError("无法计算基线指标")
        finally:
            self.records, self._total_count = temp_records, total_count

        self.baseline = baseline
        logger.info("基线已设置: NG率=%s, 置信度=%s", baseline.ng_rate, baseline.confidence_mean)

        return baseline

    def detect_drift(self, current: Optional[ConsistencyMetrics] = None,
                    thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """检测一致性漂移"""
        if current is None:
            current = self.calculate_metrics()

        if current is None:
            return {
                'drift_detected': False,
                'reason': 'insufficient_data',
                'issues': []
            }

        if self.baseline is None:
            return {
                'drift_detected': False,
                'reason': 'baseline_not_set',
                'issues': []
            }

        if thresholds is None:
            thresholds = {
                'confidence_drop': 0.2,  # 置信度均值下降20%
                'std_increase': 2.0,  # 标准差增加1倍
                'ng_rate_increase': 0.5,  # NG率增加50%
                'stability_drop': 0.3,  # 稳定性下降30%
            }

        issues = []

        # 检查置信度均值下降
        confidence_change = ((current.confidence_mean - self.baseline.confidence_mean) / max(self.baseline.confidence_mean, 0.01)
                             if current.confidence_mean is not None and self.baseline.confidence_mean is not None else 0)
        if confidence_change < -thresholds['confidence_drop']:
            issues.append({
                'type': 'confidence_drop',
                'severity': 'high',
                'change': confidence_change,
                'description': f"平均置信度下降 {abs(confidence_change):.1%}"
            })

        # 检查标准差增加（波动变大）
        std_change = ((current.confidence_std - self.baseline.confidence_std) / max(self.baseline.confidence_std, 0.02)
                      if current.confidence_std is not None and self.baseline.confidence_std is not None else 0)
        if std_change > thresholds['std_increase']:
            issues.append({
                'type': 'confidence_unstable',
                'severity': 'medium',
                'change': std_change,
                'description': f"置信度波动增加 {std_change:.1%}"
            })

        # 检查NG率突增
        ng_rate_delta = current.ng_rate - self.baseline.ng_rate
        ng_rate_change = ng_rate_delta / max(self.baseline.ng_rate, 0.05)
        if ng_rate_change > thresholds['ng_rate_increase'] and ng_rate_delta > 0.1:
            issues.append({
                'type': 'ng_rate_increase',
                'severity': 'critical',
                'change': ng_rate_change,
                'description': f"NG率增加 {ng_rate_change:.1%} "
                             f"({self.baseline.ng_rate:.1%} → {current.ng_rate:.1%})"
            })

        # 检查稳定性下降
        stability_change = ((current.stability_score - self.baseline.stability_score) / max(self.baseline.stability_score, 0.01)
                            if current.stability_score is not None and self.baseline.stability_score is not None else 0)
        if stability_change < -thresholds['stability_drop']:
            issues.append({
                'type': 'stability_drop',
                'severity': 'medium',
                'change': stability_change,
                'description': f"系统稳定性下降 {abs(stability_change):.1%}"
            })

        drift_detected = len(issues) > 0

        return {
            'drift_detected': drift_detected,
            'issues': issues,
            'current_metrics': current.to_dict(),
            'baseline_metrics': self.baseline.to_dict() if self.baseline else None
        }

    def analyze_trend(self, metric_name: str = 'confidence') -> Dict[str, Any]:
        """分析趋势（线性回归）"""
        if len(self.records) < 20 or not self.availability()["ready"]:
            return {'trend': 'unknown', 'reason': 'insufficient_data'}

        # 提取时间序列
        if metric_name == 'confidence':
            if any(r.confidence is None for r in self.records):
                return {'trend': 'unknown', 'reason': 'confidence_not_provided'}
            values = [r.confidence for r in self.records]
        elif metric_name == 'ng_rate':
            # 计算滑动NG率
            window = 10
            values = []
            records_list = list(self.records)
            for i in range(window, len(records_list)):
                ng_count = sum(1 for r in records_list[i-window:i] if r.is_ng)
                values.append(ng_count / window)
        else:
            return {'trend': 'unknown', 'reason': 'unknown_metric'}

        # 线性回归
        x = np.arange(len(values))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, values)

        # 判断趋势
        if p_value > 0.05:
            trend = 'stable'
        elif slope > 0.001:
            trend = 'increasing'
        elif slope < -0.001:
            trend = 'decreasing'
        else:
            trend = 'stable'

        return {
            'trend': trend,
            'slope': float(slope),
            'r_squared': float(r_value ** 2),
            'p_value': float(p_value),
            'values': values
        }

    def get_summary(self) -> Dict[str, Any]:
        """获取摘要信息"""
        current = self.calculate_metrics()

        summary = {
            'total_count': self._total_count,
            'window_size': self.window_size,
            'records_count': len(self.records),
            'baseline_set': self.baseline is not None,
        }

        if current:
            summary['current_metrics'] = current.to_dict()

        if self.baseline:
            summary['baseline_metrics'] = self.baseline.to_dict()

        return summary


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    tracker = ConsistencyTracker(window_size=50)

    # 模拟正常检测（基线）
    print("生成基线数据...")
    baseline_records = []
    for i in range(50):
        record = DetectionRecord(
            timestamp=i,
            detected=True,
            confidence=0.85 + np.random.randn() * 0.05,
            is_ng=np.random.rand() < 0.05  # 5% NG率
        )
        baseline_records.append(record)

    tracker.set_baseline(baseline_records)

    # 模拟漂移（置信度下降，NG率上升）
    print("\n模拟漂移...")
    for i in range(50, 100):
        record = DetectionRecord(
            timestamp=i,
            detected=True,
            confidence=0.65 + np.random.randn() * 0.1,  # 置信度下降且波动增大
            is_ng=np.random.rand() < 0.15  # NG率上升到15%
        )
        tracker.add_record(record)

    # 检测漂移
    current = tracker.calculate_metrics()
    drift_result = tracker.detect_drift(current)

    print(f"\n漂移检测结果: {drift_result['drift_detected']}")
    if drift_result['issues']:
        print("检测到的问题:")
        for issue in drift_result['issues']:
            print(f"  - {issue['description']} (严重性: {issue['severity']})")

    # 趋势分析
    print("\n趋势分析:")
    confidence_trend = tracker.analyze_trend('confidence')
    print(f"  置信度趋势: {confidence_trend['trend']}, "
          f"斜率: {confidence_trend['slope']:.4f}, "
          f"R²: {confidence_trend['r_squared']:.3f}")
