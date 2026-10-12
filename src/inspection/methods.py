"""Fixed research candidates; no runtime/default model changes or test-time tuning."""

import cv2
import numpy as np
from zipfile import ZipFile
from scipy.ndimage import gaussian_filter
from scipy.spatial.distance import cdist

from src.inspection.padim import PaDiM

METHODS = ('raw_padim', 'aligned_padim', 'aligned_roi_padim', 'raw_patch_memory', 'aligned_patch_memory',
           'raw_shrinkage_padim', 'aligned_shrinkage_padim', 'aligned_shrinkage_roi_padim')
METHODS += ('raw_dense_patch_memory', 'aligned_dense_patch_memory', 'aligned_roi_dense_patch_memory')


class ShrinkagePaDiM(PaDiM):
    """Fixed 90% diagonal shrinkage for the small-normal-sample covariance regime.

    The mean and feature extraction are unchanged. Shrinkage is fixed before
    evaluation, not selected from defect labels, and the existing NPZ format applies.
    """
    def fit(self, embeddings):
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 4 or len(embeddings) < 10 or not np.isfinite(embeddings).all():
            raise ValueError('Shrinkage PaDiM requires at least ten finite normal embeddings')
        self.mean = embeddings.mean(axis=0)
        centered = embeddings-self.mean
        covariance = np.einsum('nhwd,nhwe->hwde', centered, centered, optimize=True)/(len(embeddings)-1)
        diagonal = np.eye(embeddings.shape[-1], dtype=np.float32)
        covariance = .1*covariance + .9*covariance*diagonal + .01*diagonal
        self.precision = np.linalg.inv(covariance)


def normal_roi(frames):
    """Conservative rectangle from normal blue-PCB pixels only, with fixed 20px margin.

    This is a PCB-specific research hypothesis, not a universal object segmenter.
    """
    boxes = []
    for frame in frames:
        hsv = cv2.cvtColor(cv2.resize(frame, (224, 224)), cv2.COLOR_BGR2HSV)
        selected = cv2.inRange(hsv, np.array([70, 60, 40]), np.array([140, 255, 255]))
        components, _ = cv2.findContours(selected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not components:
            raise ValueError('Normal-only blue PCB ROI unavailable')
        component = max(components, key=cv2.contourArea)
        if cv2.contourArea(component) < 224*224*.03:
            raise ValueError('Normal-only blue PCB ROI has insufficient support')
        x, y, w, h = cv2.boundingRect(component)
        boxes.append((max(0, x-20), max(0, y-20), min(224, x+w+20), min(224, y+h+20)))
    mask = np.zeros((224, 224), bool)
    x0, y0 = np.min(np.asarray(boxes)[:, :2], axis=0)
    x1, y1 = np.max(np.asarray(boxes)[:, 2:], axis=0)
    mask[y0:y1, x0:x1] = True
    return mask


class PatchMemory:
    """Orientation-tolerant nearest normal patches, NOT a full PatchCore reproduction.

    Fixed 14x14 pooled grids and seed-0 random bank <=4096; no coreset or reweighting.
    """
    def fit(self, embeddings):
        if len(embeddings) < 10 or not np.isfinite(embeddings).all():
            raise ValueError('At least ten finite normal embeddings required')
        patches = np.concatenate([self.patches(e).reshape(-1, e.shape[-1]) for e in embeddings])
        selected = np.random.default_rng(0).choice(len(patches), min(4096, len(patches)), replace=False)
        self.bank = patches[selected].astype(np.float32)

    @staticmethod
    def patches(embedding):
        # OpenCV resize cannot handle arbitrary >4-channel arrays reliably across versions.
        return np.stack([cv2.resize(embedding[:, :, c], (14, 14), interpolation=cv2.INTER_AREA)
                         for c in range(embedding.shape[-1])], axis=-1)

    def predict(self, embedding):
        if not np.isfinite(embedding).all() or embedding.shape[-1] != self.bank.shape[-1]:
            raise ValueError('Patch memory feature mismatch')
        patches = self.patches(embedding)
        nearest = cdist(patches.reshape(-1, patches.shape[-1]), self.bank, 'euclidean').min(axis=1)
        heat = gaussian_filter(cv2.resize(nearest.reshape(14, 14), (224, 224)), sigma=4)
        return float(heat.max()), heat


class DensePatchMemory(PatchMemory):
    """28x28 normal-standardized patches; fixed random bank and bounded distance batches.

    This is a research nearest-neighbour model, not a full PatchCore reproduction.
    Channel scaling uses fit normals only; calibration and defects never enter the bank.
    """
    @staticmethod
    def patches(embedding):
        return np.stack([cv2.resize(embedding[:, :, c], (28, 28), interpolation=cv2.INTER_AREA)
                         for c in range(embedding.shape[-1])], axis=-1)

    def fit(self, embeddings):
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 4 or len(embeddings) < 10 or not np.isfinite(embeddings).all():
            raise ValueError('Dense memory requires at least ten finite normal embeddings')
        patches = np.concatenate([self.patches(e).reshape(-1, e.shape[-1]) for e in embeddings])
        self.center = patches.mean(axis=0)
        self.scale = np.maximum(patches.std(axis=0), .01)
        selected = np.random.default_rng(0).choice(len(patches), min(4096, len(patches)), replace=False)
        self.bank = ((patches[selected]-self.center)/self.scale).astype(np.float32)

    def predict(self, embedding):
        if embedding.ndim != 3 or not np.isfinite(embedding).all() or embedding.shape[-1] != self.bank.shape[-1]:
            raise ValueError('Dense memory feature mismatch')
        patches = (self.patches(embedding).reshape(-1, embedding.shape[-1])-self.center)/self.scale
        nearest = np.concatenate([cdist(patches[i:i+128], self.bank, 'euclidean').min(axis=1)
                                  for i in range(0, len(patches), 128)])
        heat = gaussian_filter(cv2.resize(nearest.reshape(28, 28), (224, 224)), sigma=2)
        return float(heat.max()), heat

    def save(self, path):
        np.savez_compressed(path, bank=self.bank, center=self.center, scale=self.scale)


def load_patch_memory(path, *, dense=False):
    required = {'bank.npy', 'center.npy', 'scale.npy'} if dense else {'bank.npy'}
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != len(required) or {e.filename for e in entries} != required
                or sum(e.file_size for e in entries) > 2*1024**2):
            raise ValueError('Patch bank expanded fields or resource limit')
    with np.load(path, allow_pickle=False) as archive:
        bank = archive['bank']
        model = DensePatchMemory() if dense else PatchMemory()
        if (bank.dtype != np.float32 or bank.ndim != 2 or not 1 <= len(bank) <= 4096
                or not 1 <= bank.shape[1] <= 100 or not np.isfinite(bank).all()):
            raise ValueError('Invalid frozen patch bank')
        model.bank = bank
        if dense:
            model.center, model.scale = archive['center'], archive['scale']
            if (model.center.shape != (bank.shape[1],) or model.scale.shape != model.center.shape
                    or not np.isfinite(model.center).all() or not np.isfinite(model.scale).all()
                    or (model.scale < .01).any()):
                raise ValueError('Invalid frozen normal feature scale')
    return model


def model_for(method):
    if method not in METHODS:
        raise ValueError('Unknown fixed research method')
    if 'patch_memory' in method: return DensePatchMemory() if 'dense' in method else PatchMemory()
    return ShrinkagePaDiM() if 'shrinkage' in method else PaDiM()


def score_map(heat, mask=None):
    if heat.shape != (224, 224) or not np.isfinite(heat).all():
        raise ValueError('Invalid research anomaly map')
    if mask is not None and (mask.shape != heat.shape or not mask.any()):
        raise ValueError('Invalid normal-derived ROI')
    return float(heat[mask].max() if mask is not None else heat.max())
