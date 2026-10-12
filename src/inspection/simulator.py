"""
漂移模拟器模块

模拟各种导致检测系统漂移的场景：
- 光学漂移：镜头污染、焦距变化、镜头老化
- 机械漂移：相机位置偏移、角度变化
- 光照漂移：光源老化、环境光变化
- 产品漂移：真实产品质量变化
"""

import cv2
import numpy as np
from typing import Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DriftScenario(Enum):
    """漂移场景类型"""
    CAMERA_DIRTY = "camera_dirty"  # 镜头污染
    FOCUS_CHANGE = "focus_change"  # 焦距变化
    POSITION_SHIFT = "position_shift"  # 位置偏移
    ANGLE_CHANGE = "angle_change"  # 角度变化
    LIGHT_FADE = "light_fade"  # 光源老化
    AMBIENT_CHANGE = "ambient_change"  # 环境光变化
    PRODUCT_DEFECT = "product_defect"  # 产品缺陷


class DriftSimulator:
    """漂移模拟器基类"""

    def __init__(self, name: str, intensity: float = 0.5):
        """
        Args:
            name: 模拟器名称
            intensity: 漂移强度 (0.0-1.0)
        """
        self.name = name
        self.intensity = np.clip(intensity, 0.0, 1.0)
        self._step = 0

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用漂移效果"""
        raise NotImplementedError

    def reset(self):
        """重置模拟器"""
        self._step = 0

    def step(self):
        """推进一步（用于渐变效果）"""
        self._step += 1


class CameraDirtySimulator(DriftSimulator):
    """镜头污染模拟器"""

    def __init__(self, intensity: float = 0.5, pattern: str = "spots"):
        """
        Args:
            intensity: 污染强度
            pattern: 污染模式 ('spots', 'fog', 'scratch')
        """
        super().__init__("CameraDirty", intensity)
        self.pattern = pattern

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用镜头污染效果"""
        result = image.copy()
        h, w = result.shape[:2]

        if self.pattern == "spots":
            # 污点效果
            num_spots = int(10 * self.intensity)
            for _ in range(num_spots):
                x = np.random.randint(0, w)
                y = np.random.randint(0, h)
                radius = np.random.randint(5, 20)
                cv2.circle(result, (x, y), radius, (200, 200, 200), -1)
                result = cv2.GaussianBlur(result, (0, 0), sigmaX=2)

        elif self.pattern == "fog":
            # 雾化效果（整体降低对比度）
            alpha = 1.0 - 0.7 * self.intensity
            fog = np.ones_like(result) * 200
            result = cv2.addWeighted(result, alpha, fog, 1 - alpha, 0)

        elif self.pattern == "scratch":
            # 划痕效果
            num_scratches = int(3 * self.intensity)
            for _ in range(num_scratches):
                x1, y1 = np.random.randint(0, w), np.random.randint(0, h)
                x2, y2 = np.random.randint(0, w), np.random.randint(0, h)
                cv2.line(result, (x1, y1), (x2, y2), (180, 180, 180), 2)

        return result


class FocusChangeSimulator(DriftSimulator):
    """焦距变化模拟器"""

    def __init__(self, intensity: float = 0.5):
        super().__init__("FocusChange", intensity)

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用失焦效果"""
        # 高斯模糊模拟失焦
        kernel_size = int(1 + 20 * self.intensity)
        if kernel_size % 2 == 0:
            kernel_size += 1

        result = cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)
        return result


class PositionShiftSimulator(DriftSimulator):
    """位置偏移模拟器"""

    def __init__(self, intensity: float = 0.5, direction: str = "random"):
        """
        Args:
            intensity: 偏移强度
            direction: 偏移方向 ('left', 'right', 'up', 'down', 'random')
        """
        super().__init__("PositionShift", intensity)
        self.direction = direction
        self._offset = self._calculate_offset()

    def _calculate_offset(self) -> Tuple[int, int]:
        """计算偏移量"""
        max_shift = 50  # 最大偏移像素
        shift = int(max_shift * self.intensity)
        if shift == 0:
            return (0, 0)

        if self.direction == "left":
            return (-shift, 0)
        elif self.direction == "right":
            return (shift, 0)
        elif self.direction == "up":
            return (0, -shift)
        elif self.direction == "down":
            return (0, shift)
        else:  # random
            return (np.random.randint(-shift, shift),
                    np.random.randint(-shift, shift))

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用位置偏移"""
        h, w = image.shape[:2]
        dx, dy = self._offset

        # 平移矩阵
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        result = cv2.warpAffine(image, M, (w, h), borderValue=(128, 128, 128))
        return result


class AngleChangeSimulator(DriftSimulator):
    """角度变化模拟器"""

    def __init__(self, intensity: float = 0.5):
        super().__init__("AngleChange", intensity)
        self.angle = 10 * self.intensity  # 最大旋转10度

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用角度变化"""
        h, w = image.shape[:2]
        center = (w // 2, h // 2)

        # 旋转矩阵
        M = cv2.getRotationMatrix2D(center, self.angle, 1.0)
        result = cv2.warpAffine(image, M, (w, h), borderValue=(128, 128, 128))
        return result


class LightFadeSimulator(DriftSimulator):
    """光源老化模拟器"""

    def __init__(self, intensity: float = 0.5):
        super().__init__("LightFade", intensity)

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用光源老化效果（降低亮度）"""
        # 降低亮度
        factor = 1.0 - 0.5 * self.intensity
        result = cv2.convertScaleAbs(image, alpha=factor, beta=0)
        return result


class AmbientChangeSimulator(DriftSimulator):
    """环境光变化模拟器"""

    def __init__(self, intensity: float = 0.5, mode: str = "increase"):
        """
        Args:
            intensity: 变化强度
            mode: 变化模式 ('increase', 'decrease', 'uneven')
        """
        super().__init__("AmbientChange", intensity)
        self.mode = mode

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用环境光变化"""
        result = image.copy()

        if self.mode == "increase":
            # 整体增亮
            beta = 50 * self.intensity
            result = np.clip(result.astype(np.float32) + beta, 0, 255).astype(np.uint8)

        elif self.mode == "decrease":
            # 整体变暗
            beta = -50 * self.intensity
            result = np.clip(result.astype(np.float32) + beta, 0, 255).astype(np.uint8)

        elif self.mode == "uneven":
            # 不均匀光照（模拟侧光）
            h, w = result.shape[:2]
            gradient = np.linspace(0, 1, w) ** 2
            gradient = np.tile(gradient, (h, 1))
            gradient = (gradient * 100 * self.intensity).astype(np.uint8)
            gradient = np.repeat(gradient[:, :, np.newaxis], 3, axis=2)
            result = cv2.add(result, gradient)

        return result


class ProductDefectSimulator(DriftSimulator):
    """产品缺陷模拟器"""

    def __init__(self, intensity: float = 0.5, defect_type: str = "scratch"):
        """
        Args:
            intensity: 缺陷强度
            defect_type: 缺陷类型 ('scratch', 'dent', 'stain')
        """
        super().__init__("ProductDefect", intensity)
        self.defect_type = defect_type

    def apply(self, image: np.ndarray) -> np.ndarray:
        """应用产品缺陷"""
        result = image.copy()
        h, w = result.shape[:2]
        if self.intensity == 0:
            return result

        num_defects = int(1 + 5 * self.intensity)

        for _ in range(num_defects):
            if self.defect_type == "scratch":
                # 划痕
                x1, y1 = np.random.randint(w//4, 3*w//4), np.random.randint(h//4, 3*h//4)
                length = np.random.randint(20, 100)
                angle = np.random.rand() * 2 * np.pi
                x2 = int(x1 + length * np.cos(angle))
                y2 = int(y1 + length * np.sin(angle))
                cv2.line(result, (x1, y1), (x2, y2), (50, 50, 50), 2)

            elif self.defect_type == "dent":
                # 凹痕（暗斑）
                x = np.random.randint(w//4, 3*w//4)
                y = np.random.randint(h//4, 3*h//4)
                radius = np.random.randint(10, 30)
                cv2.circle(result, (x, y), radius, (80, 80, 80), -1)
                # 模糊边缘
                mask = np.zeros((h, w), dtype=np.uint8)
                cv2.circle(mask, (x, y), radius, 255, -1)
                result = cv2.GaussianBlur(result, (0, 0), sigmaX=3)

            elif self.defect_type == "stain":
                # 污渍
                x = np.random.randint(w//4, 3*w//4)
                y = np.random.randint(h//4, 3*h//4)
                size = np.random.randint(15, 40)
                # 不规则形状
                pts = []
                for _ in range(8):
                    angle = np.random.rand() * 2 * np.pi
                    r = np.random.randint(size//2, size)
                    px = int(x + r * np.cos(angle))
                    py = int(y + r * np.sin(angle))
                    pts.append([px, py])
                pts = np.array(pts, dtype=np.int32)
                cv2.fillPoly(result, [pts], (100, 100, 80))

        return result


def create_simulator(scenario: DriftScenario, intensity: float = 0.5,
                    **kwargs) -> DriftSimulator:
    """工厂函数：创建漂移模拟器"""
    simulator_map = {
        DriftScenario.CAMERA_DIRTY: CameraDirtySimulator,
        DriftScenario.FOCUS_CHANGE: FocusChangeSimulator,
        DriftScenario.POSITION_SHIFT: PositionShiftSimulator,
        DriftScenario.ANGLE_CHANGE: AngleChangeSimulator,
        DriftScenario.LIGHT_FADE: LightFadeSimulator,
        DriftScenario.AMBIENT_CHANGE: AmbientChangeSimulator,
        DriftScenario.PRODUCT_DEFECT: ProductDefectSimulator,
    }

    simulator_class = simulator_map.get(scenario)
    if simulator_class is None:
        raise ValueError(f"未知的漂移场景: {scenario}")

    return simulator_class(intensity=intensity, **kwargs)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    # 创建测试图像
    test_image = cv2.imread("test_frame.jpg")
    if test_image is None:
        # 如果没有测试图像，创建一个
        test_image = np.ones((480, 640, 3), dtype=np.uint8) * 200
        cv2.rectangle(test_image, (200, 150), (400, 300), (100, 100, 200), -1)
        cv2.putText(test_image, "TEST OBJECT", (220, 230),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    # 测试所有漂移场景
    scenarios = [
        (DriftScenario.CAMERA_DIRTY, {"pattern": "spots"}),
        (DriftScenario.FOCUS_CHANGE, {}),
        (DriftScenario.POSITION_SHIFT, {"direction": "right"}),
        (DriftScenario.ANGLE_CHANGE, {}),
        (DriftScenario.LIGHT_FADE, {}),
        (DriftScenario.AMBIENT_CHANGE, {"mode": "uneven"}),
        (DriftScenario.PRODUCT_DEFECT, {"defect_type": "scratch"}),
    ]

    for scenario, kwargs in scenarios:
        print(f"测试场景: {scenario.value}")
        simulator = create_simulator(scenario, intensity=0.7, **kwargs)
        result = simulator.apply(test_image)

        # 保存结果
        filename = f"test_drift_{scenario.value}.jpg"
        cv2.imwrite(filename, result)
        print(f"已保存: {filename}")

    print("\n所有漂移场景测试完成！")
