"""Validated, immutable offline detector recipes shared by condition studies and live inference."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from src.datasets import digest
from src.inspection.alignment import PoseAligner
from src.inspection.padim import PaDiM, ResNetFeatures

WEIGHTS_SHA256 = 'f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec'
METHOD_FILES = ('src/inspection/padim.py', 'src/inspection/alignment.py', 'src/inspection/vision_model.py')
ROOT = Path(__file__).resolve().parents[2]


def method_digest():
    return digest({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in METHOD_FILES})


class Recipe(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: Literal[1]
    method: Literal['padim-resnet18-v1']
    method_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    weights_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    statistics_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reference_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    experiment_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    mode: Literal['raw', 'aligned']
    decision_threshold: float = Field(ge=0, strict=True)
    dataset_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    fit_ids: list[str] = Field(min_length=10, max_length=100)
    calibration_ids: list[str] = Field(min_length=20, max_length=20)


def validated_files(root):
    root = Path(root).expanduser().resolve()
    recipe_path = root / 'recipe.json'
    if recipe_path.stat().st_size > 128 * 1024:
        raise ValueError('视觉模型配方过大')
    recipe = Recipe.model_validate_json(recipe_path.read_bytes()).model_dump()
    if recipe['method_sha256'] != method_digest() or recipe['weights_sha256'] != WEIGHTS_SHA256:
        raise ValueError('视觉方法版本或官方权重身份不匹配，请重新导出配方')
    if set(recipe['fit_ids']).intersection(recipe['calibration_ids']):
        raise ValueError('视觉拟合与标定身份不能交叉')
    if any(len(set(recipe[key])) != len(recipe[key]) for key in ('fit_ids', 'calibration_ids')):
        raise ValueError('视觉拟合／标定身份不能重复')
    for name, key, maximum in [('weights.pth', 'weights_sha256', 64 * 1024**2),
                              ('statistics.npz', 'statistics_sha256', 160 * 1024**2),
                              ('reference.png', 'reference_sha256', 4 * 1024**2)]:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > maximum:
            raise ValueError('视觉模型文件越界、缺失或过大')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != recipe[key]:
                raise ValueError('视觉模型文件摘要不匹配')
    return root, recipe


class VisionModel:
    def __init__(self, root, features=None):
        root, self.recipe = validated_files(root)
        self.model = PaDiM.load(root / 'statistics.npz')
        if self.model.mean.shape != (56, 56, 100) and features is None:
            raise ValueError('ResNet18 配方必须包含 56×56×100 空间统计')
        reference = cv2.imread(str(root / 'reference.png'))
        if reference is None or reference.shape != (480, 640, 3):
            raise ValueError('视觉参考图像无效')
        self.aligner = PoseAligner(reference) if self.recipe['mode'] == 'aligned' else None
        self.features = features or ResNetFeatures(root / 'weights.pth', WEIGHTS_SHA256)
        self.id = digest(self.recipe)
        self.producer = {'name': 'PaDiM ResNet18', 'version': self.id, 'provenance': 'upstream',
                         'score_semantics': 'anomaly_score', 'decision_threshold': self.recipe['decision_threshold']}

    def predict(self, frame):
        if frame is None or frame.dtype != np.uint8 or frame.shape != (480, 640, 3):
            raise ValueError('视觉检测输入必须为 640×480 uint8 BGR')
        aligned, evidence = self.aligner.align(frame) if self.aligner else (frame, {'status': 'disabled', 'inliers': 0, 'error': ''})
        if aligned is None:
            return {'status': 'error', 'error': evidence['error'], 'alignment': evidence}
        score, _ = self.model.predict(self.features([aligned])[0])
        if not np.isfinite(score) or score < 0:
            raise ValueError('视觉异常分数无效')
        return {'status': 'ok', 'detected': True, 'confidence': None, 'anomaly_score': score,
                'is_ng': score > self.recipe['decision_threshold'], 'defect_types': [], 'error': '', 'alignment': evidence}
