"""Deploy sealed PaDiM statistics unchanged; never fit, select thresholds or evaluate final data."""

import hashlib
import json
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from src.acquisition import write_json
from src.datasets import digest, file_digest
from src.inspection.vision_model import ROOT, WEIGHTS_SHA256
from src.inspection.alignment import PoseAligner
from src.inspection.padim import PaDiM, ResNetFeatures
from src.inspection.methods import score_map

SUPPORTED = ('raw_padim', 'aligned_padim', 'aligned_roi_padim',
             'raw_shrinkage_padim', 'aligned_shrinkage_padim', 'aligned_shrinkage_roi_padim')
SOURCE_FILES = ('src/acceptance.py', 'src/inspection/methods.py', 'src/inspection/padim.py',
                'src/inspection/alignment.py', 'scripts/compare_visual_methods.py', 'scripts/validate_visual_release.py')


def deployment_digest():
    return digest({name: file_digest(ROOT / name) for name in
                   ('src/inspection/release_deployment.py', 'src/inspection/deployment_assets.py',
                    'src/inspection/methods.py', 'src/inspection/padim.py', 'src/inspection/alignment.py')})


def checked_file(root, relative, maximum=160 * 1024**2):
    name = PurePosixPath(relative)
    if name.is_absolute() or '..' in name.parts or '\\' in relative: raise ValueError('封存配方文件路径越界')
    path = (root / relative).resolve()
    if name.name == 'weights.pth': maximum = min(maximum, 64 * 1024**2)
    elif name.suffix in ('.png', '.json'): maximum = min(maximum, 4 * 1024**2)
    elif name.suffix == '.py': maximum = min(maximum, 2 * 1024**2)
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('封存配方文件缺失、越界或过大')
    return path


class FrozenRecipe(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: Literal[1]
    method: str
    threshold: float = Field(ge=0)
    method_source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    split_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    validation_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    weights_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    policy: dict
    files: dict[str, str]
    software: dict[str, str]


def check_seal(root, sealed):
    FrozenRecipe.model_validate(sealed)
    if (sealed.get('schema_version') != 1 or sealed.get('method') not in SUPPORTED or
            not isinstance(sealed.get('threshold'), (int, float)) or not np.isfinite(sealed['threshold']) or sealed['threshold'] < 0):
        raise ValueError('仅支持已封存的 PaDiM／ROI PaDiM，配方方法或阈值无效')
    from scripts.validate_visual_release import code_digest
    from src.acceptance import POLICY
    if sealed['method_source_sha256'] != code_digest() or sealed['policy'] != POLICY or sealed['weights_sha256'] != WEIGHTS_SHA256:
        raise ValueError('研发方法、政策或权重版本不匹配；拒绝修改旧封存包来加载')
    required = {'statistics.npz', 'reference.png', *('method-source/' + p for p in SOURCE_FILES)}
    if 'roi' in sealed['method']: required.add('roi.png')
    if set(sealed['files']) != required: raise ValueError('封存文件清单不完整或包含未知文件')
    for relative, checksum in sealed['files'].items():
        path = checked_file(root, relative)
        if file_digest(path) != checksum: raise ValueError('封存文件摘要不匹配')
        if relative.startswith('method-source/') and file_digest(ROOT / relative.removeprefix('method-source/')) != checksum:
            raise ValueError('封存实现与当前实现不匹配')
    if set(sealed['software']) != {'numpy', 'scipy', 'opencv-python-headless', 'torch', 'torchvision'}:
        raise ValueError('封存依赖清单不完整')


def check_dependencies(sealed):
    for package, expected in sealed['software'].items():
        try: actual = version(package)
        except PackageNotFoundError as exc: raise RuntimeError('缺少视觉依赖，请按诊断页的安装指引准备环境') from exc
        if actual != expected: raise ValueError(f'封存依赖版本不匹配：{package} 需要 {expected}，当前 {actual}')


class DeploymentRecipe(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: Literal[2]
    method: Literal['frozen-padim-v1']
    method_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    mode: Literal['raw', 'aligned']
    decision_threshold: float = Field(ge=0, strict=True)
    frozen_recipe_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    research_method: str
    files: dict[str, str]


def validated_deployment(root):
    root = Path(root).expanduser().resolve()
    recipe = DeploymentRecipe.model_validate_json(checked_file(root, 'recipe.json', 128 * 1024).read_bytes()).model_dump()
    if recipe['method_sha256'] != deployment_digest(): raise ValueError('研发部署适配器版本不匹配，请重新从完整封存协议导出')
    if len(recipe['files']) > 30: raise ValueError('部署文件数量无效')
    for relative, checksum in recipe['files'].items():
        if file_digest(checked_file(root, relative)) != checksum: raise ValueError('部署文件摘要不匹配')
    sealed_path = checked_file(root, 'sealed-recipe.json', 128 * 1024)
    sealed = json.loads(sealed_path.read_bytes())
    check_seal(root, sealed)
    expected = {*sealed['files'], 'weights.pth', 'sealed-recipe.json', 'freeze-receipt.json', 'split.json', 'validation-selection.json'}
    if set(recipe['files']) != expected: raise ValueError('部署文件与封存证据清单不一致')
    if (file_digest(sealed_path) != recipe['frozen_recipe_sha256'] or sealed['threshold'] != recipe['decision_threshold'] or
            sealed['method'] != recipe['research_method'] or recipe['mode'] != ('aligned' if sealed['method'].startswith('aligned') else 'raw')):
        raise ValueError('部署阈值、方法或封存身份被修改')
    receipt = json.loads(checked_file(root, 'freeze-receipt.json', 4096).read_bytes())
    split_path = checked_file(root, 'split.json', 4 * 1024**2)
    selection_path = checked_file(root, 'validation-selection.json', 4 * 1024**2)
    split, selection = json.loads(split_path.read_bytes()), json.loads(selection_path.read_bytes())
    if (receipt.get('recipe_sha256') != recipe['frozen_recipe_sha256'] or file_digest(split_path) != sealed['split_sha256'] or
            file_digest(selection_path) != sealed['validation_sha256'] or split.get('source_sha256') != sealed['source_sha256'] or
            selection.get('split_sha256') != sealed['split_sha256'] or selection.get('method_source_sha256') != sealed['method_source_sha256']):
        raise ValueError('封存回执、分区或验证选择身份不一致')
    candidate = selection.get('candidates', {}).get(sealed['method'], {})
    selected = candidate.get('selected') or {}
    if (candidate.get('status') != 'passed' or not isinstance(selected, dict) or selected.get('threshold') != sealed['threshold'] or
            candidate.get('statistics_sha256') != sealed['files']['statistics.npz']):
        raise ValueError('部署版本未通过封存前验证选择或统计不一致')
    if file_digest(root / 'weights.pth') != WEIGHTS_SHA256: raise ValueError('官方视觉权重身份不匹配')
    return root, recipe


def export_release(protocol, weights, destination):
    protocol, weights, destination = Path(protocol).expanduser().resolve(), Path(weights).expanduser().resolve(), Path(destination).expanduser().resolve()
    if destination.exists(): raise ValueError('导出目标已存在，保留原版本；请选择新目录')
    root = protocol / 'frozen'
    sealed_path = checked_file(root, 'recipe.json', 128 * 1024)
    sealed = json.loads(sealed_path.read_bytes())
    check_seal(root, sealed)
    if not weights.is_file() or file_digest(weights) != WEIGHTS_SHA256: raise ValueError('官方视觉权重身份不匹配')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-deploy-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'model'; staged.mkdir()
        for relative in sealed['files']:
            target = staged / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked_file(root, relative), target)
        shutil.copyfile(sealed_path, staged / 'sealed-recipe.json')
        for name in ('freeze-receipt.json', 'split.json', 'validation-selection.json'):
            shutil.copyfile(checked_file(protocol, name, 4 * 1024**2), staged / name)
        shutil.copyfile(weights, staged / 'weights.pth')
        recipe = {'schema_version': 2, 'method': 'frozen-padim-v1', 'method_sha256': deployment_digest(),
                  'mode': 'aligned' if sealed['method'].startswith('aligned') else 'raw', 'decision_threshold': float(sealed['threshold']),
                  'frozen_recipe_sha256': file_digest(sealed_path), 'research_method': sealed['method'],
                  'files': {p.relative_to(staged).as_posix(): file_digest(p) for p in staged.rglob('*') if p.is_file()}}
        write_json(staged / 'recipe.json', recipe)
        validated_deployment(staged)
        if destination.exists(): raise ValueError('导出目标在处理期间出现，原文件保留')
        staged.rename(destination)
    return recipe


class FrozenVisionModel:
    def __init__(self, root, features=None):
        root, self.recipe = validated_deployment(root)
        sealed = json.loads((root / 'sealed-recipe.json').read_bytes())
        if features is None: check_dependencies(sealed)
        self.model = PaDiM.load(root / 'statistics.npz')
        if features is None and self.model.mean.shape != (56, 56, 100): raise ValueError('封存 ResNet18 空间统计无效')
        reference = cv2.imread(str(root / 'reference.png'))
        if reference is None or reference.shape != (480, 640, 3): raise ValueError('封存参考图像无效')
        self.aligner = PoseAligner(reference) if self.recipe['mode'] == 'aligned' else None
        self.mask = None
        if 'roi' in sealed['method']:
            mask = cv2.imread(str(root / 'roi.png'), cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.shape != (224, 224) or not mask.any(): raise ValueError('封存 ROI 无效')
            self.mask = mask > 0
        self.features = features or ResNetFeatures(root / 'weights.pth', WEIGHTS_SHA256)
        self.id = digest(self.recipe)
        self.producer = {'name': 'PaDiM ResNet18 (sealed research)', 'version': self.id, 'provenance': 'upstream',
                         'score_semantics': 'anomaly_score', 'decision_threshold': self.recipe['decision_threshold']}

    def predict(self, frame):
        if frame is None or frame.dtype != np.uint8 or frame.shape != (480, 640, 3): raise ValueError('视觉输入必须为 640×480 uint8 BGR')
        aligned, evidence = self.aligner.align(frame) if self.aligner else (frame, {'status': 'disabled', 'inliers': 0, 'error': ''})
        if aligned is None: return {'status': 'error', 'error': evidence['error'], 'alignment': evidence}
        _, heat = self.model.predict(self.features([aligned])[0])
        score = score_map(heat, self.mask)
        if not np.isfinite(score) or score < 0: raise ValueError('封存异常分数无效')
        return {'status': 'ok', 'detected': True, 'confidence': None, 'anomaly_score': score,
                'is_ng': score > self.recipe['decision_threshold'], 'defect_types': [], 'error': '', 'alignment': evidence}
