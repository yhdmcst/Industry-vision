"""Image-only similarity alignment. Rejection is explicit and never means a normal product."""

import math

import cv2
import numpy as np


class PoseAligner:
    policy = {'features': 2500, 'ratio_test': .75, 'min_inliers': 12, 'min_inlier_ratio': .35,
              'scale_range': [.85, 1.15], 'max_reprojection_px': 3., 'min_coverage': .80,
              'min_reference_span': .05, 'transform': 'similarity; no reflection or projective warp'}

    def __init__(self, reference):
        self.reference = reference.copy()
        self.orb = cv2.ORB_create(nfeatures=self.policy['features'])
        self.keypoints, self.descriptors = self.orb.detectAndCompute(self.gray(reference), None)
        if self.descriptors is None or len(self.keypoints) < self.policy['min_inliers']:
            raise ValueError('正常训练参考缺少足够的对齐特征')

    @staticmethod
    def gray(frame):
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('对齐输入必须为 BGR 图像')
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def align(self, frame):
        evidence = {'status': 'rejected', 'inliers': 0, 'error': ''}
        def reject(reason):
            return None, {**evidence, 'error': reason}
        if frame.shape != self.reference.shape:
            return reject('图像尺寸与正常训练参考不一致')
        keypoints, descriptors = self.orb.detectAndCompute(self.gray(frame), None)
        if descriptors is None:
            return reject('当前图像没有可匹配的对齐特征')
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(descriptors, self.descriptors, k=2)
        candidates = [a for pair in matches if len(pair) == 2
                      for a, b in [pair] if a.distance < self.policy['ratio_test'] * b.distance]
        # Each reference feature may support only one correspondence.
        unique = {}
        for match in sorted(candidates, key=lambda m: m.distance):
            unique.setdefault(match.trainIdx, match)
        good = list(unique.values())
        if len(good) < self.policy['min_inliers']:
            return reject('匹配数量不足，不能可靠对齐')
        source = np.float32([keypoints[m.queryIdx].pt for m in good])
        target = np.float32([self.keypoints[m.trainIdx].pt for m in good])
        cv2.setRNGSeed(0)
        matrix, mask = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                                  ransacReprojThreshold=3., maxIters=2000,
                                                  confidence=.99, refineIters=10)
        if matrix is None or not np.isfinite(matrix).all():
            return reject('无法估计有限的相似变换')
        inliers = mask.ravel().astype(bool)
        if not inliers.any():
            return reject('没有有效内点，不能对齐')
        scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
        error = float(np.median(np.linalg.norm(source[inliers] @ matrix[:, :2].T + matrix[:, 2] - target[inliers], axis=1)))
        h, w = frame.shape[:2]
        valid = cv2.warpAffine(np.ones((h, w), np.uint8), matrix, (w, h), flags=cv2.INTER_NEAREST)
        coverage = float(np.mean(valid > 0))
        evidence.update(angle_deg=math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])),
                        shift_x=float(matrix[0, 2]), shift_y=float(matrix[1, 2]), scale=scale,
                        inliers=int(inliers.sum()), inlier_ratio=float(inliers.mean()),
                        reprojection_error=error, coverage=coverage)
        reference_span = float(cv2.contourArea(cv2.convexHull(target[inliers])) / (h * w))
        if (inliers.sum() < self.policy['min_inliers'] or inliers.mean() < self.policy['min_inlier_ratio']
                or not .85 <= scale <= 1.15 or error > self.policy['max_reprojection_px']
                or coverage < self.policy['min_coverage'] or reference_span < self.policy['min_reference_span']):
            return reject('对齐未通过内点、尺度、覆盖或空间分布质量门')
        aligned = cv2.warpAffine(frame, matrix, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REFLECT_101)
        return aligned, {**evidence, 'status': 'passed'}
