"""初始化 inspection 模块"""

from .camera import Camera, CameraConfig, VideoFileCamera, DummyCamera, create_camera
from .detector import (
    BaseDetector,
    DetectorType,
    DetectionResult,
    TemplateMatchingDetector,
    EdgeDetector,
    ColorDetector,
    create_detector
)
from .simulator import (
    DriftSimulator,
    DriftScenario,
    CameraDirtySimulator,
    FocusChangeSimulator,
    PositionShiftSimulator,
    AngleChangeSimulator,
    LightFadeSimulator,
    AmbientChangeSimulator,
    ProductDefectSimulator,
    create_simulator
)

__all__ = [
    # Camera
    'Camera',
    'CameraConfig',
    'VideoFileCamera',
    'DummyCamera',
    'create_camera',

    # Detector
    'BaseDetector',
    'DetectorType',
    'DetectionResult',
    'TemplateMatchingDetector',
    'EdgeDetector',
    'ColorDetector',
    'create_detector',

    # Simulator
    'DriftSimulator',
    'DriftScenario',
    'CameraDirtySimulator',
    'FocusChangeSimulator',
    'PositionShiftSimulator',
    'AngleChangeSimulator',
    'LightFadeSimulator',
    'AmbientChangeSimulator',
    'ProductDefectSimulator',
    'create_simulator',
]
