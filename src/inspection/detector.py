"""
简单检测器模块

实现基于 OpenCV 的基础检测功能：
- 模板匹配
- 边缘检测
- 颜色检测
- 轮廓检测
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DetectorType(Enum):
    """检测器类型"""
    TEMPLATE_MATCHING = "template_matching"
    EDGE_DETECTION = "edge_detection"
    COLOR_DETECTION = "color_detection"
    CONTOUR_DETECTION = "contour_detection"


@dataclass
class DetectionResult:
    """检测结果"""
    detected: bool
    confidence: float
    bounding_box: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    center: Optional[Tuple[int, int]] = None
    area: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseDetector:
    """检测器基类"""

    def __init__(self, name: str = "BaseDetector"):
        self.name = name
        self._detection_count = 0

    def detect(self, image: np.ndarray) -> DetectionResult:
        """检测接口"""
        raise NotImplementedError

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """图像预处理"""
        return image

    def visualize(self, image: np.ndarray, result: DetectionResult) -> np.ndarray:
        """可视化检测结果"""
        vis = image.copy()

        if result.detected and result.bounding_box is not None:
            x, y, w, h = result.bounding_box
            color = (0, 255, 0) if result.confidence > 0.7 else (0, 165, 255)
            cv2.rectangle(vis, (x, y), (x + w, y + h), color, 2)

            # 绘制置信度
            text = f"{result.confidence:.2f}"
            cv2.putText(vis, text, (x, y - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # 绘制中心点
            if result.center is not None:
                cv2.circle(vis, result.center, 5, (0, 0, 255), -1)

        return vis


class TemplateMatchingDetector(BaseDetector):
    """模板匹配检测器"""

    def __init__(self, template: np.ndarray, threshold: float = 0.7,
                 method: int = cv2.TM_CCOEFF_NORMED):
        super().__init__("TemplateMatching")
        self.template = template
        self.threshold = threshold
        self.method = method
        self.template_h, self.template_w = template.shape[:2]

    def detect(self, image: np.ndarray) -> DetectionResult:
        """模板匹配检测"""
        # 转灰度
        img_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(self.template, cv2.COLOR_BGR2GRAY)

        # 模板匹配
        result = cv2.matchTemplate(img_gray, template_gray, self.method)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        # 根据方法选择位置
        if self.method in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]:
            confidence = 1 - min_val
            top_left = min_loc
        else:
            confidence = max_val
            top_left = max_loc

        detected = confidence >= self.threshold

        if detected:
            x, y = top_left
            w, h = self.template_w, self.template_h
            center = (x + w // 2, y + h // 2)
            bbox = (x, y, w, h)
        else:
            center = None
            bbox = None

        self._detection_count += 1

        return DetectionResult(
            detected=detected,
            confidence=float(confidence),
            bounding_box=bbox,
            center=center,
            area=float(self.template_w * self.template_h),
            metadata={
                "method": str(self.method),
                "detection_count": self._detection_count
            }
        )


class EdgeDetector(BaseDetector):
    """边缘检测器"""

    def __init__(self, low_threshold: int = 50, high_threshold: int = 150,
                 min_area: float = 100.0):
        super().__init__("EdgeDetection")
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.min_area = min_area

    def detect(self, image: np.ndarray) -> DetectionResult:
        """基于边缘的检测"""
        # 转灰度
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 高斯模糊
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Canny 边缘检测
        edges = cv2.Canny(blurred, self.low_threshold, self.high_threshold)

        # 查找轮廓
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return DetectionResult(detected=False, confidence=0.0)

        # 找到最大轮廓
        largest_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_contour)

        if area < self.min_area:
            return DetectionResult(detected=False, confidence=0.0)

        # 计算边界框
        x, y, w, h = cv2.boundingRect(largest_contour)

        # 计算置信度（基于边缘强度）
        roi = edges[y:y+h, x:x+w]
        edge_density = np.sum(roi > 0) / (w * h) if w * h > 0 else 0
        confidence = min(edge_density * 2, 1.0)

        center = (x + w // 2, y + h // 2)

        self._detection_count += 1

        return DetectionResult(
            detected=True,
            confidence=float(confidence),
            bounding_box=(x, y, w, h),
            center=center,
            area=float(area),
            metadata={
                "edge_density": float(edge_density),
                "contour_count": len(contours),
                "detection_count": self._detection_count
            }
        )


class ColorDetector(BaseDetector):
    """颜色检测器"""

    def __init__(self, lower_color: Tuple[int, int, int],
                 upper_color: Tuple[int, int, int],
                 min_area: float = 100.0):
        super().__init__("ColorDetection")
        self.lower_color = np.array(lower_color)
        self.upper_color = np.array(upper_color)
        self.min_area = min_area

    def detect(self, image: np.ndarray) -> DetectionResult:
        """基于颜色的检测"""
        # 转 HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # 颜色掩码
        mask = cv2.inRange(hsv, self.lower_color, self.upper_color)

        # 形态学操作
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return DetectionResult(detected=False, confidence=0.0)

        # 找到最大轮廓
        largest_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_contour)

        if area < self.min_area:
            return DetectionResult(detected=False, confidence=0.0)

        # 计算边界框
        x, y, w, h = cv2.boundingRect(largest_contour)

        # 计算置信度（基于颜色匹配度）
        roi_mask = mask[y:y+h, x:x+w]
        match_ratio = np.sum(roi_mask > 0) / (w * h) if w * h > 0 else 0
        confidence = float(match_ratio)

        center = (x + w // 2, y + h // 2)

        self._detection_count += 1

        return DetectionResult(
            detected=True,
            confidence=confidence,
            bounding_box=(x, y, w, h),
            center=center,
            area=float(area),
            metadata={
                "match_ratio": float(match_ratio),
                "contour_count": len(contours),
                "detection_count": self._detection_count
            }
        )


def create_detector(detector_type: DetectorType, **kwargs) -> BaseDetector:
    """工厂函数：创建检测器"""
    if detector_type == DetectorType.TEMPLATE_MATCHING:
        return TemplateMatchingDetector(**kwargs)
    elif detector_type == DetectorType.EDGE_DETECTION:
        return EdgeDetector(**kwargs)
    elif detector_type == DetectorType.COLOR_DETECTION:
        return ColorDetector(**kwargs)
    else:
        raise ValueError(f"未知的检测器类型: {detector_type}")


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    # 创建测试图像
    test_image = np.ones((480, 640, 3), dtype=np.uint8) * 255
    cv2.rectangle(test_image, (200, 150), (400, 300), (0, 0, 255), -1)

    # 测试边缘检测
    print("测试边缘检测器...")
    edge_detector = EdgeDetector()
    result = edge_detector.detect(test_image)
    print(f"检测结果: {result}")

    vis = edge_detector.visualize(test_image, result)
    cv2.imwrite("test_edge_detection.jpg", vis)
    print("可视化结果已保存")
