"""
图像质量分析模块

分析图像的质量指标，用于检测光学系统的漂移：
- 清晰度（拉普拉斯方差）
- 曝光度（亮度直方图）
- 噪声水平
- 对比度
- 颜色偏移
"""

import cv2
import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImageQualityMetrics:
    """图像质量指标"""
    sharpness: float  # 清晰度（拉普拉斯方差）
    brightness: float  # 平均亮度
    contrast: float  # 对比度
    noise_level: float  # 噪声水平
    overexposure_ratio: float  # 过曝比例
    underexposure_ratio: float  # 欠曝比例
    saturation: float  # 饱和度
    histogram_entropy: float  # 直方图熵

    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return asdict(self)

    def compare_with(self, baseline: 'ImageQualityMetrics') -> Dict[str, float]:
        """与基线对比，返回相对变化"""
        return {
            'sharpness_change': (self.sharpness - baseline.sharpness) / max(baseline.sharpness, 1.0),
            'brightness_change': (self.brightness - baseline.brightness) / max(baseline.brightness, 1.0),
            'contrast_change': (self.contrast - baseline.contrast) / max(baseline.contrast, 1.0),
            'noise_change': (self.noise_level - baseline.noise_level) / max(baseline.noise_level, 1.0),
        }


class ImageQualityAnalyzer:
    """图像质量分析器"""

    def __init__(self):
        self.baseline: Optional[ImageQualityMetrics] = None
        self._history = []

    def analyze(self, image: np.ndarray) -> ImageQualityMetrics:
        """分析图像质量"""
        if image is None or image.size == 0 or image.dtype != np.uint8:
            raise ValueError("Expected a non-empty uint8 image")
        # 转灰度
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 清晰度（拉普拉斯方差）
        sharpness = self._calculate_sharpness(gray)

        # 亮度
        brightness = self._calculate_brightness(gray)

        # 对比度
        contrast = self._calculate_contrast(gray)

        # 噪声水平
        noise_level = self._calculate_noise(gray)

        # 曝光分析
        overexp_ratio, underexp_ratio = self._analyze_exposure(gray)

        # 饱和度（如果是彩色图像）
        if len(image.shape) == 3:
            saturation = self._calculate_saturation(image)
        else:
            saturation = 0.0

        # 直方图熵
        hist_entropy = self._calculate_histogram_entropy(gray)

        metrics = ImageQualityMetrics(
            sharpness=float(sharpness),
            brightness=float(brightness),
            contrast=float(contrast),
            noise_level=float(noise_level),
            overexposure_ratio=float(overexp_ratio),
            underexposure_ratio=float(underexp_ratio),
            saturation=float(saturation),
            histogram_entropy=float(hist_entropy)
        )

        # 记录历史
        self._history.append(metrics)
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        return metrics

    def set_baseline(self, images: list) -> ImageQualityMetrics:
        """从多张图像计算基线"""
        if not images:
            raise ValueError("至少需要一张图像来设置基线")

        metrics_list = [self.analyze(img) for img in images]

        # 计算平均值
        avg_metrics = ImageQualityMetrics(
            sharpness=np.mean([m.sharpness for m in metrics_list]),
            brightness=np.mean([m.brightness for m in metrics_list]),
            contrast=np.mean([m.contrast for m in metrics_list]),
            noise_level=np.mean([m.noise_level for m in metrics_list]),
            overexposure_ratio=np.mean([m.overexposure_ratio for m in metrics_list]),
            underexposure_ratio=np.mean([m.underexposure_ratio for m in metrics_list]),
            saturation=np.mean([m.saturation for m in metrics_list]),
            histogram_entropy=np.mean([m.histogram_entropy for m in metrics_list])
        )

        self.baseline = avg_metrics
        logger.info(f"基线已设置: {avg_metrics}")
        return avg_metrics

    def _calculate_sharpness(self, gray: np.ndarray) -> float:
        """计算清晰度（拉普拉斯方差）"""
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = laplacian.var()
        return variance

    def _calculate_brightness(self, gray: np.ndarray) -> float:
        """计算平均亮度"""
        return np.mean(gray)

    def _calculate_contrast(self, gray: np.ndarray) -> float:
        """计算对比度（标准差）"""
        return np.std(gray)

    def _calculate_noise(self, gray: np.ndarray) -> float:
        """估算噪声水平（高频噪声）"""
        # 使用高斯模糊后的差异来估算噪声
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        noise = gray.astype(float) - blurred.astype(float)
        noise_level = np.std(noise)
        return noise_level

    def _analyze_exposure(self, gray: np.ndarray) -> Tuple[float, float]:
        """分析曝光（过曝和欠曝比例）"""
        total_pixels = gray.size

        # 过曝（接近255）
        overexposed = np.sum(gray > 250)
        overexp_ratio = overexposed / total_pixels

        # 欠曝（接近0）
        underexposed = np.sum(gray < 5)
        underexp_ratio = underexposed / total_pixels

        return overexp_ratio, underexp_ratio

    def _calculate_saturation(self, image: np.ndarray) -> float:
        """计算饱和度"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = np.mean(hsv[:, :, 1])
        return saturation

    def _calculate_histogram_entropy(self, gray: np.ndarray) -> float:
        """计算直方图熵（图像复杂度指标）"""
        hist, _ = np.histogram(gray, bins=256, range=(0, 256))
        hist = hist / hist.sum()  # 归一化

        # 计算熵
        hist = hist[hist > 0]  # 移除零值
        entropy = -np.sum(hist * np.log2(hist))
        return entropy

    def detect_drift(self, current: ImageQualityMetrics,
                    thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """检测是否发生漂移"""
        if self.baseline is None:
            return {
                'drift_detected': False,
                'reason': 'baseline_not_set',
                'issues': []
            }

        if thresholds is None:
            thresholds = {
                'sharpness_drop': 0.3,  # 清晰度下降30%
                'brightness_change': 0.2,  # 亮度变化20%
                'contrast_change': 0.3,  # 对比度变化30%
                'noise_increase': 2.0,  # 噪声增加1倍
            }

        changes = current.compare_with(self.baseline)
        issues = []

        # 检查清晰度下降
        if changes['sharpness_change'] < -thresholds['sharpness_drop']:
            issues.append({
                'type': 'sharpness_drop',
                'severity': 'high',
                'change': changes['sharpness_change'],
                'description': f"清晰度下降 {abs(changes['sharpness_change']):.1%}"
            })

        # 检查亮度变化
        if abs(changes['brightness_change']) > thresholds['brightness_change']:
            issues.append({
                'type': 'brightness_change',
                'severity': 'medium',
                'change': changes['brightness_change'],
                'description': f"亮度变化 {changes['brightness_change']:+.1%}"
            })

        # 检查对比度变化
        if abs(changes['contrast_change']) > thresholds['contrast_change']:
            issues.append({
                'type': 'contrast_change',
                'severity': 'medium',
                'change': changes['contrast_change'],
                'description': f"对比度变化 {changes['contrast_change']:+.1%}"
            })

        # 检查噪声增加
        if changes['noise_change'] > thresholds['noise_increase']:
            issues.append({
                'type': 'noise_increase',
                'severity': 'high',
                'change': changes['noise_change'],
                'description': f"噪声增加 {changes['noise_change']:.1%}"
            })

        # 检查过曝/欠曝
        if current.overexposure_ratio > max(0.1, self.baseline.overexposure_ratio + 0.05):
            issues.append({
                'type': 'overexposure',
                'severity': 'medium',
                'change': current.overexposure_ratio - self.baseline.overexposure_ratio,
                'description': f"过曝像素占比 {current.overexposure_ratio:.1%}"
            })

        if current.underexposure_ratio > max(0.1, self.baseline.underexposure_ratio + 0.05):
            issues.append({
                'type': 'underexposure',
                'severity': 'medium',
                'change': current.underexposure_ratio - self.baseline.underexposure_ratio,
                'description': f"欠曝像素占比 {current.underexposure_ratio:.1%}"
            })

        drift_detected = len(issues) > 0

        return {
            'drift_detected': drift_detected,
            'issues': issues,
            'changes': changes,
            'current_metrics': current.to_dict(),
            'baseline_metrics': self.baseline.to_dict() if self.baseline else None
        }

    def get_history(self, window_size: int = 100) -> list:
        """获取历史记录"""
        return self._history[-window_size:]


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    # 创建测试图像
    test_image = np.ones((480, 640, 3), dtype=np.uint8) * 128
    cv2.rectangle(test_image, (200, 150), (400, 300), (200, 200, 200), -1)

    analyzer = ImageQualityAnalyzer()

    # 分析原始图像
    print("分析原始图像...")
    metrics = analyzer.analyze(test_image)
    print(f"质量指标: {metrics}")

    # 设置基线
    print("\n设置基线...")
    baseline_images = [test_image for _ in range(10)]
    analyzer.set_baseline(baseline_images)

    # 模拟漂移
    print("\n模拟失焦漂移...")
    blurred = cv2.GaussianBlur(test_image, (15, 15), 0)
    drift_metrics = analyzer.analyze(blurred)
    drift_result = analyzer.detect_drift(drift_metrics)

    print(f"漂移检测结果: {drift_result['drift_detected']}")
    if drift_result['issues']:
        print("检测到的问题:")
        for issue in drift_result['issues']:
            print(f"  - {issue['description']} (严重性: {issue['severity']})")
