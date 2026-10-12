"""Same-origin REST API and production static host. Bind to loopback, one worker."""

from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import os
import sqlite3
import time
import json
import re
from typing import Literal
from urllib.parse import urlsplit

import cv2
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, model_validator, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.service import Workstation
from src.evaluation import evaluate_replay, compare_replays
from src.llm import SparkXClient
from src.datasets import Label, Text
from src.acquisition import acquisition_io
from src.composition import CompositionCommand, PublishCompositionCommand
from src.review_study import Ratings
from src.workspace import backup_workspace, retention_preview, archive_sessions, compact_store
from src.diagnostics import workstation_diagnostics

ROOT = Path(__file__).resolve().parents[2]


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    profile: Literal['resource','balanced','responsive','custom']
    keep_alive_minutes: int = Field(ge=0, le=60)
    timeout_seconds: int = Field(ge=30, le=600)
    autostart: bool
    auto_restart: bool


class RetentionCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    before: float = Field(gt=0)
    keep_latest: int = Field(default=5, ge=1, le=10000)
    token: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class ReleaseImportCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    protocol: str = Field(min_length=1, max_length=2000)
    weights: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=100)


class AssetRemovalCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


class ModelTarget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['spark-drift:1.7b-q4', 'spark-drift:4b-q4'] | None = None


class ReviewStudyImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=2000)
    ratings_path: str | None = Field(default=None, min_length=1, max_length=2000)


class CaptureCommand(BaseModel):
    action: Literal["sample", "start", "pause", "bookmark"]


class ScenarioCommand(BaseModel):
    scenario: Literal["none", "focus_change", "light_fade", "position_shift", "camera_dirty",
                      "angle_change", "ambient_change", "product_defect"]
    intensity: float = Field(default=0.8, ge=0, le=1)


class SourceCommand(BaseModel):
    mode: Literal["synthetic", "camera", "video"]
    device: int = Field(default=0, ge=0, le=16)
    video: str = Field(default="", max_length=4096)


class BaselineCommand(BaseModel):
    count: int = Field(default=20, ge=10, le=100)
    note: str = Field(default="", max_length=2000)


class AssessmentCommand(BaseModel):
    outcome: Literal["confirmed_change", "false_alarm", "insufficient_evidence"]
    note: str = Field(min_length=1, max_length=2000)


class ModelCommand(BaseModel):
    name: str = Field(default="spark-drift:1.7b-q4", max_length=100)
    endpoint: str = Field(default="http://127.0.0.1:11435", max_length=200)
    executable: str | None = Field(default=None, max_length=2000)


class ReviewCommand(BaseModel):
    context: str = Field(default="", max_length=2000)


class DatasetImportCommand(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class VisionCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str | None = Field(default=None, min_length=1, max_length=4096)
    model_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    timeout_seconds: float = Field(default=2., ge=.1, le=10, allow_inf_nan=False)

    @model_validator(mode='after')
    def single_target(self):
        if (self.path is None) == (self.model_id is None): raise ValueError('请选择一个已登记模型或提供一个模型目录')
        return self


class VisionImportCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=100)


class ReplayCommand(BaseModel):
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CaptureBatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    description: str = Field(default="", max_length=2000)


class CaptureAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    split: Literal["baseline", "evaluation"]
    conditions: dict[Text, Text] = Field(default_factory=dict, max_length=27)
    label: Label = Field(default_factory=Label)

    @model_validator(mode="after")
    def reserved_conditions(self):
        if {"capture_source", "capture_batch_id", "capture_session"}.intersection(self.conditions):
            raise ValueError("采集条件不能使用 capture_source、capture_batch_id 或 capture_session 系统字段")
        return self


class SavePreviewCommand(CaptureAnnotation):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    origin: Literal["real", "synthetic"]


def create_app(database: Path | None = None, serve_frontend: bool = True) -> FastAPI:
    if database is None and os.environ.get('SPARK_DATABASE'):
        database = Path(os.environ['SPARK_DATABASE']).expanduser().resolve()
    @asynccontextmanager
    async def lifespan(app):
        station = Workstation(database)
        app.state.station = station
        station.start()
        try:
            yield
        finally:
            station.close()

    app = FastAPI(title="Spark Guard Local API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        # No cross-origin writes, including other local web apps. Vite proxies /api.
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin writes are not permitted"}, status_code=403)
        s = getattr(request.app.state, 'station', None)
        write = request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith('/api/')
        if write and s:
            with s.lock:
                if s.maintenance_busy: return JSONResponse({'detail': '存储维护进行中，请等待完成后再操作'}, status_code=409)
                s.write_requests += 1
        try:
            response = await call_next(request)
        finally:
            if write and s:
                with s.lock: s.write_requests -= 1
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def invalid_state(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(sqlite3.Error)
    async def unavailable_storage(request, exc):
        return JSONResponse({'detail': '本地存储暂不可用，请检查磁盘空间与权限；操作结果请以当前状态和证据记录为准。'}, status_code=503)

    def station(request: Request) -> Workstation:
        return request.app.state.station

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/api/state")
    def state(request: Request, history_token: str | None = Query(default=None, max_length=200)):
        s = station(request)
        with s.lock:
            return s.state(history_token)

    @app.get('/api/maintenance/storage')
    def storage_info(request: Request):
        return station(request).monitor.store.storage_info()

    @app.get('/api/local/paths')
    def local_paths(path: str = Query(default='', max_length=4096)):
        root = Path(path).expanduser().resolve() if path else ROOT
        if not root.is_dir(): raise HTTPException(400, '目录不存在，请输入可访问的本机目录')
        try:
            entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
            return {'path': str(root), 'parent': str(root.parent),
                    'entries': [{'name': item.name, 'path': str(item), 'directory': item.is_dir()}
                                for item in entries[:500] if not item.name.startswith('.')],
                    'truncated': len(entries) > 500}
        except OSError as exc:
            raise HTTPException(400, '目录无法读取，请检查权限或手动输入路径') from exc

    @app.post('/api/maintenance/backup')
    def backup(request: Request):
        temporary = tempfile.TemporaryDirectory(prefix='spark-evidence-backup-')
        try:
            target = Path(temporary.name) / 'spark-evidence.sqlite'
            station(request).monitor.store.backup(target)
            return FileResponse(target, media_type='application/octet-stream', filename='spark-evidence.sqlite',
                                background=BackgroundTask(temporary.cleanup))
        except Exception:
            temporary.cleanup()
            raise

    @app.post('/api/maintenance/workspace-backup')
    def workspace_backup(request: Request):
        s = station(request)
        s.begin_maintenance()
        temporary = tempfile.TemporaryDirectory(prefix='spark-workspace-backup-')
        try:
            target = Path(temporary.name) / 'spark-workspace.zip'
            backup_workspace(s.monitor.store, target)
            return FileResponse(target, media_type='application/zip', filename='spark-workspace.zip',
                                background=BackgroundTask(temporary.cleanup))
        except OSError as exc:
            temporary.cleanup()
            raise HTTPException(400, '工作空间备份无法完成，请检查磁盘空间和文件权限') from exc
        except Exception:
            temporary.cleanup()
            raise
        finally: s.end_maintenance()

    @app.post('/api/maintenance/retention-preview')
    def retention(command: RetentionCommand, request: Request):
        s = station(request)
        return retention_preview(s.monitor.store, s.monitor.session, command.before, command.keep_latest)

    @app.post('/api/maintenance/archive')
    def archive(command: RetentionCommand, request: Request):
        s = station(request)
        s.begin_maintenance()
        try:
            preview = retention_preview(s.monitor.store, s.monitor.session, command.before, command.keep_latest)
            if not command.token or command.token != preview['token']: raise RuntimeError('保留范围已变化，请重新预览后确认归档')
            return archive_sessions(s.monitor.store, preview)
        except OSError as exc:
            raise HTTPException(400, '归档未完成，请检查磁盘空间和权限；原证据或已验证归档仍保留') from exc
        finally: s.end_maintenance()

    @app.post('/api/maintenance/compact')
    def compact(request: Request):
        s = station(request)
        s.begin_maintenance()
        try: return compact_store(s.monitor.store)
        finally: s.end_maintenance()

    @app.get('/api/maintenance/archives')
    def archives(request: Request):
        root = station(request).monitor.store.path.parent / 'archives'
        items = []
        for path in sorted(root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            if re.fullmatch(r'[a-f0-9]{32}', path.stem):
                try:
                    info = json.loads(path.read_bytes())
                    items.append({'id': path.stem, 'created': info['created'], 'events': info['preview']['events'],
                                  'sessions': len(info['preview']['sessions']), 'bytes': path.with_suffix('.sqlite').stat().st_size})
                except (OSError, ValueError, KeyError):
                    items.append({'id': path.stem, 'error': '归档记录或文件不可用，原文件保留'})
        return items

    @app.get('/api/maintenance/archives/{archive_id}')
    def archive_download(archive_id: str, request: Request):
        if not re.fullmatch(r'[a-f0-9]{32}', archive_id): raise HTTPException(404, '归档不存在')
        root = station(request).monitor.store.path.parent / 'archives'
        target = root / (archive_id + '.sqlite')
        if target.is_symlink() or not target.is_file(): raise HTTPException(404, '归档文件不存在或不属于受管文件')
        from src.datasets import file_digest
        try: info = json.loads(target.with_suffix('.json').read_bytes())
        except (OSError, ValueError) as exc: raise HTTPException(400, '归档清单不可用') from exc
        if file_digest(target) != info['sha256']: raise HTTPException(400, '归档摘要不匹配，拒绝下载为有效备份')
        return FileResponse(target, media_type='application/octet-stream', filename=f'spark-archive-{archive_id}.sqlite')

    @app.post("/api/capture")
    def capture(command: CaptureCommand, request: Request):
        s = station(request)
        with s.lock:
            if command.action == "pause":
                s.running = False
            else:
                s.require_vision_idle()
                if s.monitor.baseline is None:
                    raise RuntimeError("请先采集正常基线")
                if command.action in ("start", "sample") and s.replay_state() and s.replay_state()["completed"]:
                    raise RuntimeError("回放已完成，请在样本管理中重新建立回放")
                if command.action == "start":
                    s.clear_preview()
                    s.running = True
                elif command.action == "sample":
                    if s.running:
                        raise RuntimeError("请暂停连续监测后再单帧采样")
                    s.sample()
                else:
                    return {"id": s.monitor.capture_incident()}
            return {"running": s.running}

    @app.post("/api/scenario")
    def scenario(command: ScenarioCommand, request: Request):
        s = station(request)
        with s.lock:
            s.require_vision_idle()
            if s.monitor.vision is not None:
                raise RuntimeError('实时视觉模式不允许叠加演示扰动；请使用显式标记的视频输入')
            if s.replay is not None:
                raise RuntimeError("固定回放不允许叠加软件扰动；请切换采集源后操作")
            s.scenario, s.intensity = command.scenario, command.intensity
        return {"ok": True}

    @app.post("/api/source")
    def source(command: SourceCommand, request: Request):
        s = station(request)
        with s.lock:
            path = Path(command.video).expanduser() if command.video else None
            if command.mode == "video" and (path is None or not path.is_file()):
                raise ValueError("请选择存在的本地视频文件")
            s.open_source(command.mode, command.device, path)
        return {"ok": True}

    @app.post("/api/baseline")
    def baseline(command: BaselineCommand, request: Request):
        s = station(request)
        with s.lock:
            s.require_vision_idle()
            if s.replay is not None:
                raise RuntimeError("回放基线由清单固定，请在样本管理中重新建立回放")
            s.running = False
            s.clear_preview()
            s.monitor.calibrate(command.count, command.note)
        return {"ok": True}

    @app.delete("/api/baseline")
    def reset(request: Request):
        s = station(request)
        with s.lock:
            s.require_vision_idle()
            if s.replay is not None:
                raise RuntimeError("回放基线由清单固定，请切换采集源后操作")
            s.running = False
            s.clear_preview()
            s.monitor.reset_baseline()
        return {"ok": True}

    @app.post("/api/acquisition/preview")
    def acquisition_preview(request: Request):
        s = station(request)
        with s.lock:
            return s.preview_capture()

    @app.get('/api/vision/models')
    def visual_assets(request: Request):
        return station(request).vision_catalog.snapshot()

    @app.post('/api/vision/models/import')
    def import_visual_asset(command: VisionImportCommand, request: Request):
        try:
            return station(request).vision_catalog.register(Path(command.path).expanduser(), command.name)
        except ValidationError as exc:
            raise ValueError('视觉配方格式不受支持或字段缺失，请选择导出的 PaDiM 部署配方目录。') from exc
        except OSError as exc:
            raise ValueError(f'视觉模型登记失败，请检查目录与读写权限：{exc}') from exc

    @app.post('/api/vision/models/import-release')
    def import_visual_release(command: ReleaseImportCommand, request: Request):
        from src.inspection.release_deployment import export_release
        s = station(request)
        s.begin_maintenance()
        try:
            with tempfile.TemporaryDirectory(prefix='spark-release-deploy-') as temporary:
                target = Path(temporary) / 'deployment'
                export_release(command.protocol, command.weights, target)
                return s.vision_catalog.register(target, command.name)
        except (OSError, KeyError, TypeError, ValidationError) as exc:
            raise ValueError('封存协议不完整或文件不可读，请选择含 frozen、分区与封存回执的研发协议目录') from exc
        finally: s.end_maintenance()

    def require_asset_inactive(s, model_id):
        with s.lock:
            if s.monitor.vision is not None and s.monitor.vision.id == model_id:
                raise RuntimeError('该视觉模型仍在使用，请先停用或切换后再修复／卸载')

    @app.post('/api/vision/models/{model_id}/repair')
    def repair_visual_asset(model_id: str, command: DatasetImportCommand, request: Request):
        s = station(request); s.begin_maintenance()
        try:
            require_asset_inactive(s, model_id)
            return s.vision_catalog.repair(model_id, Path(command.path).expanduser())
        except OSError as exc: raise ValueError('修复失败，请检查原配方路径与磁盘权限；原资产保留') from exc
        finally: s.end_maintenance()

    @app.get('/api/vision/models/{model_id}/removal-preview')
    def removal_preview(model_id: str, request: Request):
        s = station(request)
        require_asset_inactive(s, model_id)
        result = s.vision_catalog.removal_preview(model_id)
        with s.monitor.store.connect() as db:
            result['historical_events'] = db.execute("SELECT COUNT(*) FROM events WHERE json_extract(payload,'$.inspection_source.producer.version')=? OR json_extract(payload,'$.detection.metadata.producer.version')=?", (model_id, model_id)).fetchone()[0]
        return result

    @app.post('/api/vision/models/{model_id}/remove')
    def remove_visual_asset(model_id: str, command: AssetRemovalCommand, request: Request):
        s = station(request); s.begin_maintenance()
        try:
            require_asset_inactive(s, model_id)
            return s.vision_catalog.retire(model_id, command.token)
        except OSError as exc: raise ValueError('卸载未完成，原资产或回收副本保留；请检查磁盘权限') from exc
        finally: s.end_maintenance()

    @app.post('/api/vision/models/retired/{retirement_id}/restore')
    def restore_visual_asset(retirement_id: str, request: Request):
        s = station(request); s.begin_maintenance()
        try: return s.vision_catalog.restore(retirement_id)
        except OSError as exc: raise ValueError('恢复失败，回收文件保留；请检查目录与权限') from exc
        finally: s.end_maintenance()

    @app.get('/api/diagnostics')
    def diagnostics(request: Request):
        return JSONResponse(workstation_diagnostics(station(request)),
                            headers={'Content-Disposition': 'attachment; filename="spark-workstation-diagnostics.json"'})

    @app.post('/api/vision/connect')
    def connect_vision(command: VisionCommand, request: Request):
        from src.inspection.runtime import VisionRuntime
        s = station(request)
        root = s.vision_catalog.asset_path(command.model_id) if command.model_id else Path(command.path).expanduser()
        with s.lock:
            s.require_vision_idle()
            if s.running or s.replay is not None or s.monitor.pending is not None:
                raise RuntimeError('请暂停监测、结束模型复核并切回普通采集源')
            token = (s.monitor.session, s.monitor.baseline_generation, s.monitor.frame_count)
            s.vision_loading = True
            s.vision_management_error = ''
        candidate = None
        try:
            candidate = VisionRuntime(root, command.timeout_seconds)
            if command.model_id:
                if candidate.id != command.model_id: raise ValueError('已登记模型内容变化，请重新登记正确版本')
                s.vision_catalog.record_selection(command.model_id, command.timeout_seconds)
            with s.lock:
                if token != (s.monitor.session, s.monitor.baseline_generation, s.monitor.frame_count):
                    raise RuntimeError('工作站状态已变化，请重新连接视觉模型')
                s.vision_loading = False
                s.activate_vision(candidate)
                candidate = None
                return s.monitor.vision.state()
        except (OSError, EOFError, ValueError) as exc:
            with s.lock: s.vision_management_error = f'视觉模型连接失败：{exc}'
            raise ValueError(f'视觉模型连接失败：{exc}') from exc
        except Exception as exc:
            with s.lock: s.vision_management_error = str(exc)
            raise
        finally:
            if candidate is not None: candidate.close()
            with s.lock: s.vision_loading = False

    @app.delete('/api/vision')
    def disconnect_vision(request: Request):
        s = station(request)
        with s.lock:
            s.activate_vision(None)
            s.vision_management_error = ''
            return {'status': 'disabled'}

    @app.get("/api/acquisition/preview/image")
    def preview_image(request: Request, token: str = Query(pattern=r"^[a-f0-9]{32}$")):
        s = station(request)
        with s.lock:
            if s.preview is None or s.preview["token"] != token or s.preview_content is None:
                raise HTTPException(404, "预览已失效")
            return Response(s.preview_content, media_type="image/png")

    @app.get("/api/acquisition/batches")
    def capture_batches(request: Request):
        s = station(request)
        with s.lock:
            return s.acquisition.catalog()

    @app.post("/api/acquisition/batches")
    def create_capture_batch(command: CaptureBatchCommand, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            batch = s.acquisition.create(command.name, command.description)
            s.acquisition_revision += 1
            return batch

    @app.get("/api/acquisition/batches/{batch_id}")
    def capture_batch(batch_id: str, request: Request):
        s = station(request)
        with s.lock:
            return s.acquisition.load(batch_id)

    @app.post("/api/acquisition/batches/{batch_id}/samples")
    def save_capture(batch_id: str, command: SavePreviewCommand, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            return s.save_preview(batch_id, **command.model_dump())

    @app.patch("/api/acquisition/batches/{batch_id}/samples/{sample_id}")
    def annotate_capture(batch_id: str, sample_id: str, command: CaptureAnnotation, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            record = s.acquisition.annotate(batch_id, sample_id, **command.model_dump())
            s.acquisition_revision += 1
            return record

    @app.get("/api/acquisition/batches/{batch_id}/samples/{sample_id}/image")
    def capture_image(batch_id: str, sample_id: str, request: Request):
        s = station(request)
        with s.lock:
            return Response(s.acquisition.image_bytes(batch_id, sample_id), media_type="image/png")

    @app.post("/api/acquisition/batches/{batch_id}/publish")
    def publish_capture(batch_id: str, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            result = s.acquisition.publish(batch_id)
            s.acquisition_revision += 1
            return result

    @app.get("/api/datasets")
    def datasets(request: Request):
        return station(request).datasets.catalog()

    @app.post('/api/composition/preflight')
    def composition_preflight(command: CompositionCommand, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            return s.composition.preflight(command)

    @app.post('/api/composition/publish')
    def composition_publish(command: PublishCompositionCommand, request: Request):
        s = station(request)
        with s.lock, acquisition_io():
            result = s.composition.publish(command)
            s.acquisition_revision += 1
            return result

    @app.post("/api/datasets/import")
    def import_dataset(command: DatasetImportCommand, request: Request):
        # Import is isolated from capture; it never changes the active session.
        return station(request).datasets.import_manifest(Path(command.path))

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str, request: Request):
        return station(request).datasets.load(dataset_id)

    @app.get("/api/datasets/{dataset_id}/images/{index}")
    def dataset_image(dataset_id: str, index: int, request: Request):
        store = station(request).datasets
        manifest = store.load(dataset_id)
        if not 0 <= index < len(manifest["samples"]):
            raise HTTPException(404, "样本不存在")
        frame = store.image(dataset_id, manifest["samples"][index])
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("样本图像无法编码")
        return Response(encoded.tobytes(), media_type="image/png")

    @app.post("/api/replay")
    def replay(command: ReplayCommand, request: Request):
        s = station(request)
        with s.lock:
            s.prepare_replay(command.dataset_id, command.result_id)
            return s.replay_state()

    @app.post("/api/inspection-results/import")
    def import_results(command: DatasetImportCommand, request: Request):
        return station(request).results.import_file(Path(command.path))

    @app.get("/api/datasets/{dataset_id}/inspection-results")
    def result_catalog(dataset_id: str, request: Request):
        return station(request).results.catalog(dataset_id)

    @app.get("/api/inspection-results/{result_id}")
    def result_package(result_id: str, request: Request):
        return station(request).results.load(result_id)

    @app.get("/api/replay/export")
    def replay_export(request: Request):
        s = station(request)
        with s.lock:
            return JSONResponse(s.export_replay(), headers={
                "Content-Disposition": 'attachment; filename="spark-replay.json"'})

    @app.get("/api/replays")
    def replays(request: Request):
        s = station(request)
        with s.lock:
            return s.replay_history()

    @app.get("/api/sessions/{session}/replay")
    def past_replay(session: str, request: Request):
        s = station(request)
        with s.lock:
            return JSONResponse(s.export_replay(session), headers={
                "Content-Disposition": 'attachment; filename="spark-replay.json"'})

    @app.get("/api/sessions/{session}/evaluation")
    def evaluation(session: str, request: Request):
        s = station(request)
        with s.lock:
            return evaluate_replay(s.export_replay(session))

    @app.get('/api/review-studies')
    def review_studies(request: Request):
        with acquisition_io(): return station(request).review_studies.list()

    @app.post('/api/review-studies/import')
    def review_study_import(command: ReviewStudyImport, request: Request):
        with acquisition_io():
            return station(request).review_studies.import_study(command.path, command.ratings_path)

    @app.get('/api/review-studies/{report_id}')
    def review_study(report_id: str, request: Request):
        with acquisition_io(): return station(request).review_studies.load(report_id)

    @app.get('/api/review-studies/{report_id}/cards')
    def review_cards(report_id: str, request: Request):
        with acquisition_io(): return station(request).review_studies.cards(report_id)

    @app.post('/api/review-studies/{report_id}/ratings')
    def review_ratings(report_id: str, command: Ratings, request: Request):
        with acquisition_io():
            return station(request).review_studies.apply_ratings(report_id, command.model_dump())

    @app.get("/api/evaluation/compare")
    def evaluation_comparison(request: Request,
                              left: str = Query(min_length=1, max_length=64),
                              right: str = Query(min_length=1, max_length=64)):
        s = station(request)
        with s.lock:
            return compare_replays(s.export_replay(left), s.export_replay(right))

    @app.get("/api/baselines")
    def baselines(request: Request):
        s = station(request)
        with s.lock:
            return s.monitor.store.events(s.monitor.session, kind="baseline")

    @app.get("/api/images/{kind}")
    def image(kind: Literal["current", "baseline"], request: Request):
        s = station(request)
        with s.lock:
            frame = s.monitor.last_frame if kind == "current" else s.monitor.baseline_frame
            if frame is None:
                raise HTTPException(404, "暂无图像")
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError("Unable to encode frame")
            return Response(encoded.tobytes(), media_type="image/png")

    @app.get("/api/sessions")
    def sessions(request: Request, limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return station(request).monitor.store.sessions(limit, offset)

    @app.get("/api/sessions/{session}/incidents")
    def incidents(session: str, request: Request, limit: int = Query(default=200, ge=1, le=200),
                  before: int | None = Query(default=None, ge=1), status: Literal['all', 'pending', 'done'] = 'all',
                  search: str = Query(default='', max_length=100), page: bool = False,
                  frame: int | None = Query(default=None, ge=0), baseline_generation: int | None = Query(default=None, ge=1)):
        s = station(request)
        result = s.monitor.store.incident_page(session, limit=limit, before=before, status=status, search=search,
                                             frame=frame, baseline_generation=baseline_generation)
        for item in result['items']:
            lifecycle = lifecycle_events(s.monitor.store, session, item['id'])
            item['lifecycle'] = incident_lifecycle(s, session, {'id': item['id'], 'payload': item}, lifecycle)
        return result if page else result['items']

    def lifecycle_events(store, session: str, incident_id: int):
        events = [*store.all_events(session, kind="incident_recovered", incident_id=incident_id),
                  *store.all_events(session, kind="incident_closed", incident_id=incident_id)]
        return sorted(events, key=lambda e: e["id"])

    def incident_lifecycle(s: Workstation, session: str, event: dict, lifecycle: list):
        related = [e for e in lifecycle if e["payload"]["incident_id"] == event["id"]]
        if related:
            latest = related[-1]
            return {"state": "recovered" if latest["kind"] == "incident_recovered" else "closed",
                    "reason": latest["payload"]["reason"], "frame": latest["payload"]["frame"],
                    "created": latest["created"]}
        if event["payload"]["trigger"] == "operator_bookmark":
            return {"state": "bookmark"}
        with s.lock:
            alert = s.monitor.alerts.snapshot()
            active = (session == s.monitor.session and alert["active"] and
                      alert["episode"]["incident_id"] == event["id"])
        return {"state": "active" if active else "unresolved"}

    def bundle(s: Workstation, session: str, event_id: int):
        store = s.monitor.store
        try:
            event = store.event(session, event_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if event["kind"] != "incident":
            raise HTTPException(404, "Not an incident")
        related = {kind: store.all_events(session, kind=kind, incident_id=event_id)
                   for kind in ("incident_assessment", "model_review", "model_error", "incident_updated")}
        lifecycle = lifecycle_events(store, session, event_id)
        return {"event": event, "assessments": related["incident_assessment"],
                "reviews": related["model_review"], "errors": related["model_error"],
                "updates": related["incident_updated"],
                "lifecycle": incident_lifecycle(s, session, event, lifecycle),
                "lifecycle_events": [e for e in lifecycle if e["payload"]["incident_id"] == event_id]}

    @app.get("/api/sessions/{session}/incidents/{event_id}")
    def incident(session: str, event_id: int, request: Request):
        s = station(request)
        return bundle(s, session, event_id)

    @app.post("/api/sessions/{session}/incidents/{event_id}/assessment")
    def assessment(session: str, event_id: int, command: AssessmentCommand, request: Request):
        s = station(request)
        with s.lock:
            return {"id": s.monitor.record_incident_assessment(session, event_id, command.outcome, command.note)}

    @app.post("/api/model/connect")
    def connect(command: ModelCommand, request: Request):
        s = station(request)
        s.models.connect(command.name, command.endpoint, SparkXClient, command.executable)
        return {"ok": True}

    @app.post('/api/model/configure')
    def configure_model(command: ModelCommand, request: Request):
        station(request).models.configure(command.name, command.endpoint, command.executable)
        return {'ok': True}

    @app.post('/api/model/policy')
    def model_policy(command: ModelPolicy, request: Request):
        station(request).models.set_policy(command.model_dump())
        return {'ok':True}

    @app.post('/api/model/cancel')
    def cancel_model(request: Request):
        station(request).models.cancel_operation()
        return {'ok': True}

    @app.get('/api/model/diagnostics')
    def model_diagnostics(request: Request):
        return Response(json.dumps(station(request).models.diagnostics(), ensure_ascii=False),
                        media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="spark-model-diagnostics.json"'})

    @app.post('/api/model/{action}')
    def model_operation(action: Literal['check', 'start', 'stop', 'restart', 'prepare', 'validate', 'switch', 'rollback'], request: Request, command: ModelTarget | None = None):
        manager = station(request).models
        with manager.lock:
            manager.launch(action, command.name if command else None)
            return JSONResponse({'status': 'pending', 'operation': action, 'task_id': manager.task_id}, status_code=202)

    @app.get('/api/model/logs')
    def model_logs(request: Request):
        return station(request).models.log_tail()

    @app.post("/api/sessions/{session}/incidents/{event_id}/review")
    def review(session: str, event_id: int, command: ReviewCommand, request: Request):
        s = station(request)
        with s.lock:
            if session != s.monitor.session:
                raise ValueError("历史会话可人工复核，模型复核仅支持当前会话")
            model = s.models.snapshot()
            if model['operation'] is not None:
                raise RuntimeError('模型管理操作进行中，请等待完成')
            if not model['connected']:
                raise RuntimeError("请先在本地模型页启动服务或核验连接")
            s.monitor.request_review(command.context, model['name'], model['endpoint'], incident_id=event_id, deployment=model['validation'], policy=model['policy'])
        return {"status": "pending"}

    @app.get("/api/export")
    def export(request: Request):
        s = station(request)
        with s.lock:
            session, baseline = s.monitor.session, s.monitor.baseline
        return StreamingResponse(s.monitor.store.export_session(session, {'baseline': baseline, 'exported': time.time(),
            'disclaimer': 'Synthetic/injected records are not field validation. Scores are heuristic; no automatic actuation.'}),
            media_type="application/json", headers={"Content-Disposition": 'attachment; filename="spark-evidence.json"'})

    if serve_frontend and (ROOT / "frontend/dist").is_dir():
        app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="frontend")
    return app


app = create_app()
