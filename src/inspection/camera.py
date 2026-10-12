"""
摄像头接口封装模块

提供统一的摄像头访问接口，支持：
- USB 摄像头
- 笔记本内置摄像头
- IP 摄像头（RTSP 流）
- 视频文件回放
"""

import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """摄像头配置"""
    device_id: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    backend: str = "auto"
    auto_exposure: bool = True
    auto_white_balance: bool = True
    brightness: int = 0
    contrast: int = 0


class Camera:
    """摄像头类"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_opened = False
        self._frame_count = 0

    def open(self) -> bool:
        """打开摄像头"""
        try:
            # 选择后端
            backend = self._get_backend()

            # 打开设备
            if isinstance(self.config.device_id, int):
                self.cap = cv2.VideoCapture(self.config.device_id, backend)
            else:
                # 支持 RTSP 或视频文件
                self.cap = cv2.VideoCapture(str(self.config.device_id), backend)

            if not self.cap.isOpened():
                logger.error(f"无法打开摄像头: {self.config.device_id}")
                return False

            # 设置分辨率
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.config.fps)

            # 设置其他参数
            if self.config.auto_exposure:
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
            if self.config.brightness != 0:
                self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.config.brightness)
            if self.config.contrast != 0:
                self.cap.set(cv2.CAP_PROP_CONTRAST, self.config.contrast)

            self.is_opened = True
            logger.info(f"摄像头已打开: {self.config.device_id}, "
                       f"分辨率: {self.config.width}x{self.config.height}, "
                       f"FPS: {self.config.fps}")
            return True

        except Exception as e:
            logger.error(f"打开摄像头失败: {e}")
            return False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取一帧图像"""
        if not self.is_opened or self.cap is None:
            return False, None

        ret, frame = self.cap.read()
        if ret:
            self._frame_count += 1
        return ret, frame

    def close(self):
        """关闭摄像头"""
        if self.cap is not None:
            self.cap.release()
            self.is_opened = False
            logger.info(f"摄像头已关闭，共读取 {self._frame_count} 帧")

    def get_properties(self) -> Dict[str, Any]:
        """获取摄像头属性"""
        if not self.is_opened or self.cap is None:
            return {}

        return {
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": self.cap.get(cv2.CAP_PROP_FPS),
            "brightness": self.cap.get(cv2.CAP_PROP_BRIGHTNESS),
            "contrast": self.cap.get(cv2.CAP_PROP_CONTRAST),
            "exposure": self.cap.get(cv2.CAP_PROP_EXPOSURE),
            "frame_count": self._frame_count,
        }

    def _get_backend(self) -> int:
        """根据配置选择后端"""
        backend_map = {
            "auto": cv2.CAP_ANY,
            "v4l2": cv2.CAP_V4L2,
            "dshow": cv2.CAP_DSHOW,
            "avfoundation": cv2.CAP_AVFOUNDATION,
            "gstreamer": cv2.CAP_GSTREAMER,
        }
        return backend_map.get(self.config.backend, cv2.CAP_ANY)

    def __enter__(self):
        """上下文管理器入口"""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


class VideoFileCamera(Camera):
    """视频文件作为摄像头源"""

    def __init__(self, video_path: Path, loop: bool = True):
        config = CameraConfig(device_id=str(video_path))
        super().__init__(config)
        self.video_path = video_path
        self.loop = loop
        self.total_frames = 0

    def open(self) -> bool:
        success = super().open()
        if success and self.cap is not None:
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            logger.info(f"视频文件已加载: {self.video_path}, 总帧数: {self.total_frames}")
        return success

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        ret, frame = super().read()

        # 如果到达视频末尾且需要循环
        if not ret and self.loop and self.cap is not None:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = super().read()
            logger.debug("视频循环播放")

        return ret, frame


class DummyCamera(Camera):
    """虚拟摄像头（用于测试）"""

    def __init__(self, width: int = 640, height: int = 480):
        config = CameraConfig(device_id=-1, width=width, height=height)
        super().__init__(config)
        self._counter = 0

    def open(self) -> bool:
        self.is_opened = True
        logger.info("虚拟摄像头已打开（测试模式）")
        return True

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """生成测试图像"""
        if not self.is_opened:
            return False, None

        # Deterministic bitmap fixture, explicitly synthetic, with stationary texture.
        frame = np.full((480, 640, 3), (105, 110, 115), dtype=np.uint8)
        cv2.rectangle(frame, (120, 80), (525, 400), (47, 101, 64), -1)
        for x, y in [(140, 100), (505, 100), (140, 380), (505, 380)]:
            cv2.circle(frame, (x, y), 9, (175, 182, 188), -1)
            cv2.circle(frame, (x, y), 4, (70, 76, 78), -1)
        for y in range(125, 375, 20):
            cv2.line(frame, (160, y), (480, y), (77, 133, 86), 1)
        for x in range(165, 480, 25):
            cv2.line(frame, (x, 115), (x, 365), (83, 143, 93), 1)
        cv2.rectangle(frame, (270, 175), (380, 285), (37, 42, 44), -1)
        for i in range(10):
            offset = 182 + i * 10
            cv2.line(frame, (257, offset), (270, offset), (185, 190, 195), 3)
            cv2.line(frame, (380, offset), (393, offset), (185, 190, 195), 3)
            cv2.line(frame, (277 + i * 10, 162), (277 + i * 10, 175), (185, 190, 195), 3)
            cv2.line(frame, (277 + i * 10, 285), (277 + i * 10, 298), (185, 190, 195), 3)
        for x in [185, 220, 435, 470]:
            for y in [155, 225, 305]:
                cv2.rectangle(frame, (x - 10, y - 6), (x + 10, y + 6), (50, 55, 63), -1)
                cv2.rectangle(frame, (x - 12, y - 5), (x - 8, y + 5), (188, 194, 197), -1)
                cv2.rectangle(frame, (x + 8, y - 5), (x + 12, y + 5), (188, 194, 197), -1)
        cv2.putText(frame, "SPARK / PCB-042", (158, 351), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 227, 216), 1)
        cv2.putText(frame, "SYNTHETIC FIXTURE", (20, 455), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (210, 214, 217), 1)
        frame = cv2.resize(frame, (self.config.width, self.config.height))

        self._counter += 1
        self._frame_count += 1
        return True, frame

    def close(self):
        self.is_opened = False
        logger.info(f"虚拟摄像头已关闭，共生成 {self._frame_count} 帧")


def create_camera(config: Optional[CameraConfig] = None,
                  video_path: Optional[Path] = None,
                  dummy: bool = False) -> Camera:
    """工厂函数：创建摄像头实例"""
    if dummy:
        return DummyCamera()
    elif video_path is not None:
        return VideoFileCamera(video_path)
    else:
        if config is None:
            config = CameraConfig()
        return Camera(config)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    # 测试虚拟摄像头
    print("测试虚拟摄像头...")
    with create_camera(dummy=True) as cam:
        for i in range(5):
            ret, frame = cam.read()
            if ret:
                print(f"读取帧 {i}: {frame.shape}")

    # 测试真实摄像头（如果可用）
    print("\n测试真实摄像头...")
    cam = create_camera()
    if cam.open():
        print(f"摄像头属性: {cam.get_properties()}")
        ret, frame = cam.read()
        if ret:
            print(f"读取成功: {frame.shape}")
            cv2.imwrite("test_frame.jpg", frame)
            print("测试图像已保存为 test_frame.jpg")
        cam.close()
    else:
        print("无法打开摄像头（可能设备不可用）")
