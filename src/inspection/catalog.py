"""Owned immutable visual recipe assets and explicit, inactive-on-restart selections."""

import copy
import json
from pathlib import Path
import shutil
import threading
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.acquisition import write_json
from src.datasets import digest
from src.inspection.deployment_assets import checked_asset, asset_files, asset_method_digest

FILES = ('recipe.json', 'weights.pth', 'statistics.npz', 'reference.png')


def stamps(root, files=FILES):
    result = {}
    for name in files:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file(): return None
        stat = path.stat()
        result[name] = [stat.st_size, stat.st_mtime_ns]
    return result


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    timeout_seconds: float = Field(ge=.1, le=10)
    created: float


class Asset(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(pattern=r'^[a-f0-9]{64}$')
    name: str = Field(min_length=1, max_length=100)
    mode: Literal['raw', 'aligned']
    method: Literal['padim-resnet18-v1', 'frozen-padim-v1']
    method_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    created: float
    stamps: dict[str, list[int]]
    files: list[str] = Field(default_factory=lambda: list(FILES), max_length=32)
    repaired: float | None = None


class VisionCatalog:
    def __init__(self, database):
        self.root = database.with_name(database.name + '-vision-models').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'catalog.json'
        self.lock = threading.RLock()
        self.assets, self.selections, self.retired, self.error = {}, [], {}, ''
        if self.path.exists():
            try:
                if self.path.stat().st_size > 1024 ** 2: raise ValueError('视觉资产目录记录过大')
                data = json.loads(self.path.read_bytes())
                if data['schema_version'] not in (1, 2): raise ValueError('视觉资产目录版本不支持')
                assets = data['assets']
                if not isinstance(assets, dict) or len(assets) > 50: raise ValueError('视觉资产记录无效')
                for model_id, asset in assets.items():
                    if len(model_id) != 64 or any(c not in 'abcdef0123456789' for c in model_id):
                        raise ValueError('视觉资产身份无效')
                    assets[model_id] = Asset.model_validate(asset).model_dump()
                    if asset['id'] != model_id or set(asset['stamps']) != set(assets[model_id]['files']): raise ValueError('视觉资产格式无效')
                    for name in assets[model_id]['files']:
                        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name: raise ValueError('视觉资产文件路径无效')
                selections = [Selection.model_validate(item).model_dump() for item in data.get('selections', [])]
                if any(item['model_id'] not in assets for item in selections): raise ValueError('视觉配置引用未知资产')
                retired = data.get('retired', {})
                if not isinstance(retired, dict) or len(retired) > 500: raise ValueError('视觉回收区记录无效')
                for retirement_id, record in retired.items():
                    if len(retirement_id) != 32 or any(c not in 'abcdef0123456789' for c in retirement_id): raise ValueError('视觉回收身份无效')
                    record['asset'] = Asset.model_validate(record['asset']).model_dump()
                    if not isinstance(record['removed'], (int, float)): raise ValueError('视觉回收时间无效')
                self.assets, self.selections, self.retired = assets, selections[-20:], retired
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.error = f'视觉资产目录无法读取，原文件已保留：{exc}'

    def _save(self, assets, selections, retired=None):
        if self.error: raise RuntimeError(self.error)
        write_json(self.path, {'schema_version': 2, 'assets': assets, 'selections': selections, 'retired': self.retired if retired is None else retired})

    def register(self, source, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('视觉模型名称须为 1..100 字符')
        with self.lock:
            if self.error: raise RuntimeError(self.error)
            root, recipe = checked_asset(source)
            model_id = digest(recipe)
            if model_id in self.assets:
                checked_asset(self.root / model_id)
                return copy.deepcopy(self.assets[model_id])
            if len(self.assets) >= 50: raise ValueError('视觉模型目录最多登记 50 个版本')
            target = self.root / model_id
            temporary = self.root / ('.import-' + uuid.uuid4().hex)
            temporary.mkdir()
            published = False
            try:
                files = asset_files(recipe)
                for filename in files:
                    path = (root / filename).resolve()
                    if not path.is_relative_to(root): raise ValueError('视觉模型文件越界')
                    target_file = temporary / filename
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target_file)
                _, copied = checked_asset(temporary)
                if digest(copied) != model_id: raise ValueError('视觉模型导入期间发生变化')
                if target.exists():
                    _, existing = checked_asset(target)
                    if digest(existing) != model_id: raise ValueError('已有视觉资产身份冲突')
                else:
                    temporary.rename(target)
                    published = True
                asset = {'id': model_id, 'name': name.strip(), 'mode': recipe['mode'],
                         'method': recipe['method'], 'method_sha256': recipe['method_sha256'],
                         'created': time.time(), 'stamps': stamps(target, files), 'files': list(files), 'repaired': None}
                assets = {**self.assets, model_id: asset}
                self._save(assets, self.selections)
                self.assets = assets
                return copy.deepcopy(asset)
            except Exception:
                if published: shutil.rmtree(target)
                raise
            finally:
                shutil.rmtree(temporary, ignore_errors=True)

    def asset_path(self, model_id):
        with self.lock:
            if self.error: raise RuntimeError(self.error)
            if model_id not in self.assets: raise ValueError('视觉模型尚未登记')
            return self.root / model_id

    def repair(self, model_id, source):
        with self.lock:
            target = self.asset_path(model_id)
            root, recipe = checked_asset(source)
            if digest(recipe) != model_id: raise ValueError('修复来源与登记版本不同，不能改变阈值、文件或模型身份')
            temporary = self.root / ('.repair-' + uuid.uuid4().hex)
            backup = self.root / 'repair-backups' / uuid.uuid4().hex
            if backup.parent.is_symlink(): raise ValueError('修复备份目录不能是符号链接')
            temporary.mkdir(); backup.parent.mkdir(exist_ok=True)
            moved = False
            try:
                files = asset_files(recipe)
                for filename in files:
                    source_file = (root / filename).resolve()
                    if not source_file.is_relative_to(root): raise ValueError('修复来源文件越界')
                    destination = temporary / filename; destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_file, destination)
                _, copied = checked_asset(temporary)
                if digest(copied) != model_id: raise ValueError('修复来源在复制期间变化')
                if target.is_symlink(): raise ValueError('受管资产目录不能是符号链接')
                if target.exists(): target.rename(backup); moved = True
                temporary.rename(target)
                updated = {**self.assets[model_id], 'stamps': stamps(target, files), 'files': list(files), 'repaired': time.time()}
                assets = {**self.assets, model_id: updated}
                try: self._save(assets, self.selections)
                except Exception:
                    shutil.rmtree(target)
                    if moved: backup.rename(target)
                    raise
                self.assets = assets
                return {**updated, 'preserved_previous': str(backup) if moved else None}
            except Exception:
                if moved and backup.exists() and not target.exists(): backup.rename(target)
                raise
            finally: shutil.rmtree(temporary, ignore_errors=True)

    def removal_preview(self, model_id):
        with self.lock:
            asset = self.assets.get(model_id)
            if asset is None: raise ValueError('视觉模型尚未登记')
            current = stamps(self.asset_path(model_id), asset['files'])
            return {'model_id': model_id, 'name': asset['name'], 'bytes': sum(s[0] for s in (current or {}).values()),
                    'token': digest({'asset': asset, 'stamps': current, 'selections': self.selections}),
                    'scope': '从可选版本移除并移至本机回收区，历史证据和原导入目录保留；回收区仍占用磁盘'}

    def retire(self, model_id, token):
        with self.lock:
            if token != self.removal_preview(model_id)['token']: raise RuntimeError('资产或配置发生变化，请重新预览卸载')
            if len(self.retired) >= 500: raise ValueError('视觉回收区达到 500 个版本上限，请先在独立备份后维护回收目录')
            retirement_id = uuid.uuid4().hex
            target = self.asset_path(model_id)
            trash = self.root / 'retired' / retirement_id
            trash.parent.mkdir(exist_ok=True)
            if target.is_symlink() or trash.parent.is_symlink(): raise ValueError('受管资产目录不能是符号链接')
            moved = target.exists()
            if moved: target.rename(trash)
            assets = {key: value for key, value in self.assets.items() if key != model_id}
            selections = [record for record in self.selections if record['model_id'] != model_id]
            retired = {**self.retired, retirement_id: {'asset': self.assets[model_id], 'removed': time.time(), 'files_present': moved}}
            try: self._save(assets, selections, retired)
            except Exception:
                if moved: trash.rename(target)
                raise
            self.assets, self.selections, self.retired = assets, selections, retired
            return {'retirement_id': retirement_id, 'model_id': model_id, 'recoverable': moved}

    def restore(self, retirement_id):
        with self.lock:
            if self.error: raise RuntimeError(self.error)
            if retirement_id not in self.retired: raise ValueError('视觉回收版本不存在')
            asset = self.retired[retirement_id]['asset']
            if asset['id'] in self.assets: raise ValueError('同一视觉版本已登记，不能覆盖')
            if len(self.assets) >= 50: raise ValueError('视觉目录已达到 50 个版本上限')
            source = self.root / 'retired' / retirement_id
            if source.is_symlink() or source.parent.is_symlink(): raise ValueError('回收资产目录不能是符号链接')
            _, recipe = checked_asset(source)
            if digest(recipe) != asset['id']: raise ValueError('回收资产身份不匹配，原文件保留')
            target = self.root / asset['id']
            if target.exists(): raise ValueError('恢复目标已存在，原文件保留')
            source.rename(target)
            restored = {**asset, 'stamps': stamps(target, asset['files'])}
            assets = {**self.assets, asset['id']: restored}
            retired = {key: value for key, value in self.retired.items() if key != retirement_id}
            try: self._save(assets, self.selections, retired)
            except Exception: target.rename(source); raise
            self.assets, self.retired = assets, retired
            return copy.deepcopy(restored)

    def record_selection(self, model_id, timeout_seconds):
        selection = Selection.model_validate({'model_id': model_id, 'timeout_seconds': timeout_seconds, 'created': time.time()}).model_dump()
        with self.lock:
            self.asset_path(model_id)
            records = (self.selections + [selection])[-20:]
            self._save(self.assets, records)
            self.selections = records

    def snapshot(self):
        with self.lock:
            result = []
            for asset in self.assets.values():
                try:
                    current = stamps(self.root / asset['id'], asset.get('files', FILES))
                    status = 'missing' if current is None else 'changed' if current != asset['stamps'] else 'compatible' if asset_method_digest(asset['method']) == asset['method_sha256'] else 'incompatible'
                except OSError: status = 'missing'
                result.append({**asset, 'file_status': status})
            return {'assets': result, 'selections': copy.deepcopy(self.selections),
                    'retired': [{'retirement_id': key, **copy.deepcopy(value)} for key, value in self.retired.items()], 'error': self.error}
