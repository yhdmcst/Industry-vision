"""PaDiM normal-only spatial Gaussian model; optional torchvision feature extraction.

Paper algorithm independently implemented, with ResNet18, 100 fixed random channels,
full per-location covariance, Mahalanobis distance and Gaussian-smoothed image max.
"""

import hashlib
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter


class ResNetFeatures:
    def __init__(self, weights: Path, expected_sha256: str):
        if hashlib.sha256(weights.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError('ResNet18 权重 SHA-256 不匹配')
        try:
            import torch
            from torchvision.models import resnet18
        except ImportError as exc:
            raise RuntimeError('请先安装 requirements-vision.txt 中的可选视觉依赖') from exc
        self.torch = torch
        torch.set_num_threads(4)
        torch.manual_seed(0)
        self.model = resnet18(weights=None).eval()
        self.model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True))
        self.channels = np.random.default_rng(0).choice(448, 100, replace=False)

    def __call__(self, frames):
        torch = self.torch
        rgb = np.stack([cv2.cvtColor(cv2.resize(f, (224, 224), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                        for f in frames]).astype(np.float32) / 255
        rgb = (rgb - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
        tensor = torch.from_numpy(rgb.transpose(0, 3, 1, 2))
        with torch.inference_mode():
            model = self.model
            tensor = model.maxpool(model.relu(model.bn1(model.conv1(tensor))))
            one = model.layer1(tensor)
            two = model.layer2(one)
            three = model.layer3(two)
            # Layer2/3 feature grids map to layer1 positions, as in PaDiM.
            embedding = torch.cat([one, torch.nn.functional.interpolate(two, size=one.shape[-2:], mode='nearest'),
                                   torch.nn.functional.interpolate(three, size=one.shape[-2:], mode='nearest')], dim=1)
        return embedding[:, self.channels].numpy().transpose(0, 2, 3, 1)


class PaDiM:
    def fit(self, embeddings):
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 4 or len(embeddings) < 10 or not np.isfinite(embeddings).all():
            raise ValueError('PaDiM 需要至少十张正常图像的有限空间特征')
        self.mean = embeddings.mean(axis=0)
        centered = embeddings - self.mean
        covariance = np.einsum('nhwd,nhwe->hwde', centered, centered, optimize=True) / (len(embeddings) - 1)
        covariance += .01 * np.eye(embeddings.shape[-1], dtype=np.float32)
        self.precision = np.linalg.inv(covariance)

    def predict(self, embedding):
        if embedding.shape != self.mean.shape or not np.isfinite(embedding).all():
            raise ValueError('PaDiM 评估特征尺寸不匹配或非有限')
        difference = embedding - self.mean
        distance = np.sqrt(np.maximum(0, np.einsum('hwd,hwde,hwe->hw', difference, self.precision, difference, optimize=True)))
        anomaly_map = gaussian_filter(cv2.resize(distance, (224, 224), interpolation=cv2.INTER_LINEAR), sigma=4)
        return float(anomaly_map.max()), anomaly_map

    def save(self, path):
        np.savez_compressed(path, mean=self.mean, precision=self.precision)

    @classmethod
    def load(cls, path):
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) != 2 or {entry.filename for entry in entries} != {'mean.npy', 'precision.npy'}
                    or sum(entry.file_size for entry in entries) > 140 * 1024**2):
                raise ValueError('PaDiM 模型统计归档字段或展开大小无效')
        with np.load(path, allow_pickle=False) as document:
            if set(document.files) != {'mean', 'precision'}:
                raise ValueError('PaDiM 模型统计字段无效')
            mean, precision = document['mean'], document['precision']
        if (mean.ndim != 3 or precision.shape != (*mean.shape, mean.shape[-1])
                or not 1 <= mean.shape[-1] <= 100 or mean.size > 56 * 56 * 100
                or not np.isfinite(mean).all() or not np.isfinite(precision).all()
                or not np.allclose(precision, precision.swapaxes(-1, -2), rtol=1e-4, atol=1e-4)):
            raise ValueError('PaDiM 模型统计尺寸、有限值或对称性无效')
        np.linalg.cholesky(precision)
        model = cls()
        model.mean, model.precision = mean, precision
        return model
