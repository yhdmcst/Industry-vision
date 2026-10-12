"""
漂移检测器模块

整合图像质量分析和检测一致性跟踪，综合判断系统漂移
"""

import numpy as np
import cv2
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

from .image_analyzer import ImageQualityAnalyzer, ImageQualityMetrics
from .consistency_tracker import ConsistencyTracker, ConsistencyMetrics, DetectionRecord

logger = logging.getLogger(__name__)


class DriftType(Enum):
    """漂移类型"""
    NONE = "none"
    OPTICAL = "optical"  # 光学漂移（镜头污染、失焦等）
    MECHANICAL = "mechanical"  # 机械漂移（位置、角度变化）
    ILLUMINATION = "illumination"  # 光照漂移（光源老化、环境光变化）
    PRODUCT = "product"  # 产品变化（真实质量问题）
    UNKNOWN = "unknown"


@dataclass
class DriftReport:
    """漂移报告"""
    drift_detected: bool
    drift_type: DriftType
    confidence_score: float | None  # 不可用检测证据时不计算综合评分
    urgency: str  # low / medium / high / critical
    root_cause: str
    evidence: List[str]
    recommendations: List[str]
    metrics: Dict[str, Any]


class DriftDetector:
    """漂移检测器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.image_analyzer = ImageQualityAnalyzer()
        self.consistency_tracker = ConsistencyTracker(
            window_size=self.config.get('window_size', 100)
        )

        # 阈值配置
        self.thresholds = self.config.get('thresholds', {
            'image_quality': {
                'sharpness_drop': 0.3,
                'brightness_change': 0.2,
                'contrast_change': 0.3,
                'noise_increase': 2.0,
            },
            'consistency': {
                'confidence_drop': 0.2,
                'std_increase': 2.0,
                'ng_rate_increase': 0.5,
                'stability_drop': 0.3,
            }
        })

        # 评分权重
        self.scoring_weights = self.config.get('scoring_weights', {
            'image_quality': 0.4,
            'detection_consistency': 0.6,
        })
        self.baseline_gray: Optional[np.ndarray] = None

    def set_baseline(self, images: List[np.ndarray],
                    detection_records: List[DetectionRecord]):
        """设置基线"""
        logger.info("设置图像质量基线...")
        self.image_analyzer.set_baseline(images)

        logger.info("设置检测一致性基线...")
        self.consistency_tracker.set_baseline(detection_records)

        logger.info("基线设置完成")
        self.baseline_gray = cv2.cvtColor(images[0], cv2.COLOR_BGR2GRAY).astype(np.float32)
        self.consistency_tracker.records.clear()

    def add_detection_record(self, record: DetectionRecord):
        """添加检测记录"""
        self.consistency_tracker.add_record(record)

    def analyze(self, image: np.ndarray,
               detection_record: Optional[DetectionRecord] = None) -> DriftReport:
        """分析当前状态，生成漂移报告"""

        # 1. 图像质量分析
        img_metrics = self.image_analyzer.analyze(image)
        img_drift = self.image_analyzer.detect_drift(
            img_metrics,
            thresholds=self.thresholds['image_quality']
        )
        if self.baseline_gray is not None:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
            if gray.shape != self.baseline_gray.shape:
                raise ValueError("Frame dimensions differ from baseline; recalibrate")
            shift, response = cv2.phaseCorrelate(self.baseline_gray, gray)
            img_drift["registration"] = {"shift_x": float(shift[0]), "shift_y": float(shift[1]),
                                         "response": float(response)}
            if response > 0.25 and np.hypot(*shift) > 8:
                img_drift["issues"].append({
                    "type": "position_shift", "severity": "high", "change": float(np.hypot(*shift)),
                    "description": f"画面平移 {shift[0]:+.1f}px / {shift[1]:+.1f}px（待人工核验）",
                })
                img_drift["drift_detected"] = True

        # 2. 检测一致性分析
        if detection_record:
            self.consistency_tracker.add_record(detection_record)

        cons_metrics = self.consistency_tracker.calculate_metrics()
        cons_drift = self.consistency_tracker.detect_drift(
            current=cons_metrics,
            thresholds=self.thresholds['consistency']
        ) if cons_metrics else {'drift_detected': False, 'issues': []}

        # 3. 综合判断
        drift_detected = img_drift['drift_detected'] or cons_drift['drift_detected']

        # 4. 判断漂移类型
        drift_type = self._classify_drift_type(img_drift, cons_drift)

        # 5. 计算可信度评分
        confidence_score = self._calculate_confidence_score(img_metrics, cons_metrics)
        confidence_missing = ((detection_record is not None and detection_record.metadata.get('producer', {}).get('score_semantics') == 'anomaly_score')
                              or (cons_metrics is not None and cons_metrics.confidence_mean is None))
        if drift_detected:
            changes = img_drift.get("changes", {})
            severity = max(abs(changes.get("brightness_change", 0)),
                           max(0, -changes.get("sharpness_change", 0)),
                           abs(changes.get("contrast_change", 0)))
            confidence_score = min(confidence_score, max(25.0, 75.0 - severity * 40))
            if drift_type == DriftType.MECHANICAL:
                confidence_score = min(confidence_score, 60.0)

        # 6. 生成根因分析
        root_cause, evidence = self._analyze_root_cause(img_drift, cons_drift, drift_type)

        # 7. 生成建议
        recommendations = self._generate_recommendations(drift_type, img_drift, cons_drift)

        # 8. 评估紧急程度
        urgency = self._assess_urgency(confidence_score, drift_type, cons_drift)

        availability = self.consistency_tracker.availability()
        if confidence_missing:
            confidence_score = None
            evidence.append('上游提供未标定异常分数，未提供判定置信度；NG率可用，置信度与综合评分不计算')
        if availability["unavailable"]:
            confidence_score = None
            evidence.append(f"当前窗口检测结果不可用 {availability['unavailable']}/{availability['total']}，一致性统计暂停")
            if not drift_detected:
                drift_type = DriftType.UNKNOWN
                root_cause = "检测证据不足，不能判断检测结果是否稳定"
                recommendations = ["核对上游检测服务与结果文件，恢复完整结果后重新评估"]

        # 构建报告
        report = DriftReport(
            drift_detected=drift_detected,
            drift_type=drift_type,
            confidence_score=confidence_score,
            urgency=urgency,
            root_cause=root_cause,
            evidence=evidence,
            recommendations=recommendations,
            metrics={
                'image_quality': img_metrics.to_dict(),
                'consistency': cons_metrics.to_dict() if cons_metrics else {},
                'image_drift': img_drift,
                'consistency_drift': cons_drift,
                'detection_availability': availability,
            }
        )

        return report

    def _classify_drift_type(self, img_drift: Dict, cons_drift: Dict) -> DriftType:
        """分类漂移类型"""
        img_issues = {issue['type'] for issue in img_drift.get('issues', [])}
        cons_issues = {issue['type'] for issue in cons_drift.get('issues', [])}

        if 'position_shift' in img_issues:
            return DriftType.MECHANICAL

        # Darkening also suppresses Laplacian variance; inspect exposure first.
        if any(t in img_issues for t in ['brightness_change', 'overexposure', 'underexposure']):
            return DriftType.ILLUMINATION

        # 光学漂移：清晰度下降、噪声增加
        if 'sharpness_drop' in img_issues or 'noise_increase' in img_issues:
            return DriftType.OPTICAL

        # 光照漂移：亮度、对比度、曝光问题
        if any(t in img_issues for t in ['brightness_change', 'contrast_change',
                                          'overexposure', 'underexposure']):
            return DriftType.ILLUMINATION

        # 产品漂移：NG率突增但图像质量正常
        if 'ng_rate_increase' in cons_issues and not img_drift['drift_detected']:
            return DriftType.PRODUCT

        # 机械漂移：检测结果不稳定但图像质量正常
        if ('confidence_unstable' in cons_issues or 'stability_drop' in cons_issues) \
           and not img_drift['drift_detected']:
            return DriftType.MECHANICAL

        # 无漂移
        if not (img_drift['drift_detected'] or cons_drift['drift_detected']):
            return DriftType.NONE

        return DriftType.UNKNOWN

    def _calculate_confidence_score(self, img_metrics: Optional[ImageQualityMetrics],
                                   cons_metrics: Optional[ConsistencyMetrics]) -> float:
        """计算系统可信度评分（0-100）"""
        scores = []

        # 图像质量评分
        if img_metrics and self.image_analyzer.baseline:
            baseline = self.image_analyzer.baseline

            # 清晰度评分
            sharpness_ratio = (img_metrics.sharpness + 1.0) / (baseline.sharpness + 1.0)
            sharpness_score = min(sharpness_ratio * 100, 100)

            # 噪声评分（噪声越低越好）
            noise_ratio = (baseline.noise_level + 1.0) / (img_metrics.noise_level + 1.0)
            noise_score = min(noise_ratio * 100, 100)

            # 曝光评分
            exposure_penalty = (img_metrics.overexposure_ratio +
                              img_metrics.underexposure_ratio) * 100
            exposure_score = max(100 - exposure_penalty, 0)

            img_score = np.mean([sharpness_score, noise_score, exposure_score])
            scores.append(('image', img_score, self.scoring_weights['image_quality']))

        # 检测一致性评分
        if cons_metrics and cons_metrics.confidence_mean is not None:
            # 置信度评分
            conf_score = cons_metrics.confidence_mean * 100

            # 稳定性评分
            stability_score = cons_metrics.stability_score * 100

            # NG率评分（NG率越低越好）
            ng_penalty = cons_metrics.ng_rate * 100
            ng_score = max(100 - ng_penalty, 0)

            cons_score = np.mean([conf_score, stability_score, ng_score])
            scores.append(('consistency', cons_score, self.scoring_weights['detection_consistency']))

        # 加权平均
        if scores:
            total_weight = sum(w for _, _, w in scores)
            weighted_score = sum(s * w for _, s, w in scores) / total_weight
            return float(np.clip(weighted_score, 0, 100))

        return 50.0  # 默认中等评分

    def _analyze_root_cause(self, img_drift: Dict, cons_drift: Dict,
                           drift_type: DriftType) -> tuple:
        """分析根因"""
        evidence = []
        root_cause = "未检测到明显异常"

        # 收集证据
        for issue in img_drift.get('issues', []):
            evidence.append(issue['description'])

        for issue in cons_drift.get('issues', []):
            evidence.append(issue['description'])

        # 根据漂移类型生成根因描述
        if drift_type == DriftType.OPTICAL:
            root_cause = "光学系统出现问题（镜头污染、失焦或镜头老化）"
        elif drift_type == DriftType.ILLUMINATION:
            root_cause = "光照系统出现问题（光源老化、环境光变化或光源位置偏移）"
        elif drift_type == DriftType.MECHANICAL:
            root_cause = "机械系统出现问题（相机位置偏移或角度变化）"
        elif drift_type == DriftType.PRODUCT:
            root_cause = "产品质量可能真实下降（需人工复核确认）"
        elif drift_type == DriftType.UNKNOWN:
            root_cause = "检测到异常但原因不明（需综合排查）"

        return root_cause, evidence

    def _generate_recommendations(self, drift_type: DriftType,
                                 img_drift: Dict, cons_drift: Dict) -> List[str]:
        """生成建议措施"""
        recommendations = []

        if drift_type == DriftType.OPTICAL:
            recommendations.extend([
                "🔧 检查并清洁镜头",
                "🎯 重新对焦或调整焦距",
                "📷 检查相机是否需要维护或更换"
            ])

        elif drift_type == DriftType.ILLUMINATION:
            recommendations.extend([
                "💡 检查光源是否正常工作",
                "🔆 调整光源亮度或更换老化灯具",
                "🌓 检查环境光是否稳定（关闭窗户或使用遮光）"
            ])

        elif drift_type == DriftType.MECHANICAL:
            recommendations.extend([
                "📐 重新标定相机位置和角度",
                "🔩 检查固定螺丝是否松动",
                "⚙️ 检查机械振动是否过大"
            ])

        elif drift_type == DriftType.PRODUCT:
            recommendations.extend([
                "👤 人工抽检当前批次产品",
                "📊 检查上游工序是否有异常",
                "📝 记录并通知质量部门"
            ])

        elif drift_type == DriftType.UNKNOWN:
            recommendations.extend([
                "🔍 综合检查设备状态",
                "📸 对比基线图像和当前图像",
                "📞 联系设备供应商或技术支持"
            ])

        else:  # NONE
            recommendations.append("✅ 系统运行正常，继续监控")

        # 根据具体问题添加额外建议
        img_issues = {issue['type'] for issue in img_drift.get('issues', [])}

        if 'overexposure' in img_issues:
            recommendations.append("☀️ 降低光源亮度或调整相机曝光参数")

        if 'underexposure' in img_issues:
            recommendations.append("🌙 增加光源亮度或调整相机曝光参数")

        return recommendations

    def _assess_urgency(self, confidence_score: float, drift_type: DriftType,
                       cons_drift: Dict) -> str:
        """评估紧急程度"""
        # 根据可信度评分
        if confidence_score < 40:
            return "critical"
        elif confidence_score < 60:
            return "high"
        elif confidence_score < 75:
            return "medium"

        # 根据漂移类型
        if drift_type == DriftType.PRODUCT:
            return "critical"  # 产品问题最紧急

        # 根据NG率增长
        cons_issues = cons_drift.get('issues', [])
        for issue in cons_issues:
            if issue['type'] == 'ng_rate_increase' and issue['change'] > 1.0:
                return "critical"

        return "low"


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    detector = DriftDetector()

    # 创建测试图像
    test_image = np.ones((480, 640, 3), dtype=np.uint8) * 150
    import cv2
    cv2.rectangle(test_image, (200, 150), (400, 300), (180, 180, 180), -1)

    # 设置基线
    print("设置基线...")
    baseline_images = [test_image for _ in range(20)]
    baseline_records = [
        DetectionRecord(
            timestamp=i,
            detected=True,
            confidence=0.85 + np.random.randn() * 0.03,
            is_ng=np.random.rand() < 0.05
        ) for i in range(20)
    ]
    detector.set_baseline(baseline_images, baseline_records)

    # 模拟正常运行
    print("\n测试正常图像...")
    report = detector.analyze(test_image, baseline_records[0])
    print(f"漂移检测: {report.drift_detected}")
    print(f"可信度评分: {report.confidence_score:.1f}")
    print(f"漂移类型: {report.drift_type.value}")

    # 模拟光学漂移（失焦）
    print("\n测试失焦图像...")
    blurred = cv2.GaussianBlur(test_image, (21, 21), 0)
    drift_record = DetectionRecord(
        timestamp=100,
        detected=True,
        confidence=0.65,
        is_ng=False
    )
    report = detector.analyze(blurred, drift_record)
    print(f"漂移检测: {report.drift_detected}")
    print(f"可信度评分: {report.confidence_score:.1f}")
    print(f"漂移类型: {report.drift_type.value}")
    print(f"紧急程度: {report.urgency}")
    print(f"根因: {report.root_cause}")
    print("建议措施:")
    for rec in report.recommendations:
        print(f"  {rec}")
