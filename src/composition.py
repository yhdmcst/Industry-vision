"""Compose immutable source datasets and capture drafts without rewriting source evidence."""

import hashlib
from pathlib import Path
import tempfile
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.acquisition import AcquisitionStore, write_json
from src.dataset_checks import partition_checks
from src.datasets import DatasetStore, Manifest, MAX_SAMPLES, Sample, Text, digest
from src.inspection.quality_gate import quality_reasons
from src.monitoring.image_analyzer import ImageQualityAnalyzer


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['capture', 'dataset']
    source_id: str = Field(pattern=r'^[a-f0-9]{32}([a-f0-9]{32})?$')
    sample_id: Text
    split: Literal['baseline', 'evaluation']

    @model_validator(mode='after')
    def source_length(self):
        if len(self.source_id) != (32 if self.kind == 'capture' else 64):
            raise ValueError('来源标识长度不匹配')
        return self


class CompositionCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Text
    description: str = Field(default='', max_length=2000)
    selections: list[Selection] = Field(min_length=11, max_length=MAX_SAMPLES)


class PublishCompositionCommand(CompositionCommand):
    checked_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Composition:
    def __init__(self, datasets: DatasetStore, acquisition: AcquisitionStore):
        self.datasets = datasets
        self.acquisition = acquisition

    def resolve(self, command: CompositionCommand) -> tuple[list[dict], list[bytes], dict]:
        records, images, seen = [], [], set()
        batches, manifests = {}, {}
        for selection in command.selections:
            key = (selection.kind, selection.source_id, selection.sample_id)
            if key in seen:
                raise ValueError('同一来源样本不能重复选择或同时用作参考和评估')
            seen.add(key)
            if selection.kind == 'capture':
                if selection.source_id not in batches:
                    batches[selection.source_id] = self.acquisition.load(selection.source_id)
                source = next((s for s in batches[selection.source_id]['samples'] if s['id'] == selection.sample_id), None)
                if source is None:
                    raise ValueError('选中的采集样本不存在')
                content = self.acquisition._verified_image(self.acquisition.directory(selection.source_id), source)
                conditions = {**source['conditions'], 'capture_source': source['source'],
                              'capture_batch_id': selection.source_id, 'capture_session': source['source_session']}
            else:
                if selection.source_id not in manifests:
                    manifests[selection.source_id] = self.datasets.load(selection.source_id)
                source = next((s for s in manifests[selection.source_id]['samples'] if s['id'] == selection.sample_id), None)
                if source is None:
                    raise ValueError('选中的数据集样本不存在')
                self.datasets.image(selection.source_id, source)
                content = (self.datasets.directory(selection.source_id) / source['asset']).read_bytes()
                if hashlib.sha256(content).hexdigest() != source['sha256']:
                    raise RuntimeError('来源图像在编排读取期间发生变化')
                conditions = source['conditions']
            sample_id = 'composed-' + digest({'source': key})
            sample = {k: source[k] for k in Sample.model_fields}
            sample.update(id=sample_id, path=f'{sample_id}.png', frame_index=None, split=selection.split,
                          conditions=conditions)
            # Original evidence is retained in a versioned lineage file, never injected into model input.
            lineage = source.get('lineage') or {'kind': 'capture' if conditions.get('capture_batch_id') else selection.kind,
                                               'source_id': conditions.get('capture_batch_id') or selection.source_id,
                                               'sample_id': selection.sample_id, 'batch_key': self._batch_key(source, selection)}
            frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            if frame is None or frame.shape != (480, 640, 3):
                raise ValueError('选中的样本图像格式无效')
            if selection.split == 'baseline' and quality_reasons(ImageQualityAnalyzer().analyze(frame).to_dict()):
                raise ValueError('选中的参考样本未通过取景质量门')
            records.append({**sample, 'sha256': hashlib.sha256(content).hexdigest(), 'lineage': lineage})
            images.append(content)
        Manifest.model_validate({'schema_version': 1, 'name': command.name, 'description': command.description,
                                 'samples': [{k: s[k] for k in Sample.model_fields} for s in records]})
        checks = partition_checks(records)
        original_keys = [digest(r['lineage']) for r in records]
        if len(set(original_keys)) != len(original_keys):
            raise ValueError('不同来源版本引用了同一原始样本，不能重复选择')
        return records, images, checks

    @staticmethod
    def _batch_key(source, selection):
        from src.dataset_checks import batch_key
        return batch_key(source) if selection.kind == 'dataset' else 'capture:' + selection.source_id

    def preflight(self, command: CompositionCommand) -> dict:
        records, _, checks = self.resolve(command)
        checked = digest({'command': command.model_dump(), 'samples': records})
        return {'checked_sha256': checked, 'baseline_count': sum(r['split'] == 'baseline' for r in records),
                'evaluation_count': sum(r['split'] == 'evaluation' for r in records), 'checks': checks,
                'warnings': self.warnings(checks), 'samples': records}

    @staticmethod
    def warnings(checks):
        messages = ['批次分离与摘要检查不证明统计独立或已通过盲测；公开数据的 train/test 也不是现场采集批次。']
        for key, message in [('shared_batch_keys', '参考与评估存在同一来源批次'),
                             ('baseline_duplicate_ids', '评估像素与参考重复'),
                             ('evaluation_duplicate_ids', '评估内部存在重复像素'),
                             ('unlabeled_evaluation_ids', '评估样本缺少独立缺陷标签'),
                             ('synthetic_ids', '选择包含合成图像'),
                             ('perturbed_ids', '选择包含软件扰动'),
                             ('declared_batch_ids', '部分批次只有导入者名称声明')]:
            if checks[key]: messages.append(f'{message}：{len(checks[key])} 项')
        return messages

    def publish(self, command: PublishCompositionCommand) -> dict:
        specification = CompositionCommand.model_validate(command.model_dump(exclude={'checked_sha256'}))
        records, images, _ = self.resolve(specification)
        if digest({'command': specification.model_dump(), 'samples': records}) != command.checked_sha256:
            raise RuntimeError('来源样本或编排已变化，请重新执行发布前检查')
        # The usual import owns atomic image publication and immutability.
        with tempfile.TemporaryDirectory(prefix='.compose-', dir=self.datasets.root) as temporary:
            root = Path(temporary)
            for record, content in zip(records, images):
                (root / record['path']).write_bytes(content)
            manifest = root / 'manifest.json'
            write_json(manifest, {'schema_version': 1, 'name': command.name, 'description': command.description,
                                  'samples': [{k: s[k] for k in Sample.model_fields} for s in records]})
            return self.datasets.import_manifest(manifest, lineage={r['id']: r['lineage'] for r in records})
