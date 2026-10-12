"""Local, content-addressed image datasets. Labels are evidence, never model input."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Annotated, Literal

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
MAX_SAMPLES = 500
MAX_MEDIA_BYTES = 256 * 1024 * 1024
MAX_PIXELS = 16_000_000


def digest(value: dict | list) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defect: Literal["unknown", "normal", "defect"] = "unknown"
    cause: Literal["unknown", "none", "optical", "illumination", "mechanical", "product"] = "unknown"
    note: str = Field(default="", max_length=2000)


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    batch: Text
    split: Literal["baseline", "evaluation"]
    path: str = Field(min_length=1, max_length=1024)
    frame_index: int | None = Field(default=None, ge=0, le=100000, strict=True)
    origin: Literal["real", "synthetic"]
    perturbation: Text = "none"
    captured_at: str = Field(default="", max_length=100)
    conditions: dict[Text, Text] = Field(default_factory=dict, max_length=30)
    label: Label = Field(default_factory=Label)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    name: Text
    description: str = Field(default="", max_length=2000)
    samples: list[Sample] = Field(min_length=11, max_length=MAX_SAMPLES)

    @model_validator(mode="after")
    def validate_samples(self):
        if len({s.id for s in self.samples}) != len(self.samples):
            raise ValueError("样本 ID 不能重复")
        references = [s for s in self.samples if s.split == "baseline"]
        if not 10 <= len(references) <= 100 or len(references) == len(self.samples):
            raise ValueError("需要 10–100 个基线样本和至少 1 个评估样本")
        if any(s.perturbation != "none" or s.label.defect == "defect"
               or s.label.cause not in ("none", "unknown") for s in references):
            raise ValueError("基线不能包含已标注的缺陷、异常原因或软件扰动")
        locations = [(s.path, s.frame_index) for s in self.samples]
        if len(set(locations)) != len(locations):
            raise ValueError("同一文件或视频帧不能重复登记")
        return self


class DatasetStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, dataset_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", dataset_id):
            raise ValueError("无效的数据集标识")
        return self.root / dataset_id

    def load(self, dataset_id: str) -> dict:
        directory = self.directory(dataset_id)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if digest(manifest) != dataset_id:
                raise ValueError("数据集清单摘要不匹配，请检查本地存储")
            return manifest
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("数据集不存在或清单损坏") from exc

    def catalog(self) -> list[dict]:
        datasets = []
        for directory in sorted(self.root.iterdir()):
            if re.fullmatch(r"[a-f0-9]{64}", directory.name):
                try:
                    manifest = self.load(directory.name)
                    datasets.append(self.summary(directory.name, manifest))
                except ValueError:
                    datasets.append({"id": directory.name, "name": "清单损坏", "error": "请检查本地存储"})
        return datasets

    @staticmethod
    def summary(dataset_id: str, manifest: dict) -> dict:
        samples = manifest["samples"]
        return {"id": dataset_id, "name": manifest["name"], "description": manifest["description"],
                "baseline_count": sum(s["split"] == "baseline" for s in samples),
                "evaluation_count": sum(s["split"] == "evaluation" for s in samples),
                "batches": sorted({s["batch"] for s in samples}),
                "origins": sorted({s["origin"] for s in samples}),
                "labeled_count": sum(s["label"]["defect"] != "unknown" for s in samples),
                "perturbed_count": sum(s["perturbation"] != "none" for s in samples)}

    def image(self, dataset_id: str, sample: dict) -> np.ndarray:
        path = self.directory(dataset_id) / sample["asset"]
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RuntimeError("数据集图像缺失，请检查本地存储") from exc
        if hashlib.sha256(content).hexdigest() != sample["sha256"]:
            raise RuntimeError("数据集图像摘要不匹配，已停止回放")
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (480, 640, 3):
            raise RuntimeError("数据集图像格式无效")
        return frame

    def import_manifest(self, path: Path, *, lineage: dict | None = None) -> dict:
        try:
            return self._import(path.expanduser().resolve(), lineage=lineage)
        except (OSError, cv2.error, Image.DecompressionBombError) as exc:
            raise ValueError(f"导入失败：无法读取或保存数据集（{type(exc).__name__}）") from exc

    @staticmethod
    def _frames(root: Path, samples: list[Sample]):
        groups = {}
        for index, sample in enumerate(samples):
            groups.setdefault((root / sample.path).resolve(), []).append((index, sample))
        for source, entries in groups.items():
            if any(s.frame_index is None for _, s in entries):
                if len(entries) != 1:
                    raise ValueError("同一媒体不能同时按图像和视频登记")
                index, sample = entries[0]
                with Image.open(source) as image:
                    if image.width * image.height > MAX_PIXELS or image.format not in ("PNG", "JPEG", "BMP", "TIFF", "WEBP"):
                        raise ValueError(f"样本 {sample.id}：图像格式不支持或超过 1600 万像素")
                    frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
                yield index, sample, source, frame
            else:
                if source.suffix.lower() not in (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"):
                    raise ValueError("视频仅支持本地 MP4、AVI、MOV、MKV、WebM、M4V 文件")
                capture = cv2.VideoCapture(str(source))
                try:
                    pixels = capture.get(cv2.CAP_PROP_FRAME_WIDTH) * capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    if not capture.isOpened() or not 0 < pixels <= MAX_PIXELS:
                        raise ValueError("视频无效或分辨率超过 1600 万像素")
                    position = 0
                    # Decode each file once in ascending frame order; retain manifest order in storage.
                    for index, sample in sorted(entries, key=lambda entry: entry[1].frame_index):
                        while position < sample.frame_index:
                            if not capture.grab():
                                raise ValueError(f"样本 {sample.id}：视频帧超出范围")
                            position += 1
                        ok, frame = capture.read()
                        position += 1
                        if not ok:
                            raise ValueError(f"样本 {sample.id}：视频帧不可读取")
                        yield index, sample, source, frame
                finally:
                    capture.release()

    def _import(self, path: Path, *, lineage: dict | None = None) -> dict:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("清单必须是存在的 JSON 文件，且不超过 1 MiB")
        manifest = Manifest.model_validate_json(path.read_bytes())
        # No archive extraction or arbitrary URL access. Media stays under the manifest directory.
        media = {}
        locations = set()
        total_bytes = 0
        for sample in manifest.samples:
            relative = PurePosixPath(sample.path)
            candidate = (path.parent / sample.path).resolve()
            if (relative.is_absolute() or ".." in relative.parts or "\\" in sample.path
                    or ":" in sample.path or not candidate.is_relative_to(path.parent)
                    or not candidate.is_file()):
                raise ValueError(f"样本 {sample.id}：媒体路径必须位于清单目录内")
            location = (candidate, sample.frame_index)
            if location in locations:
                raise ValueError("多个样本指向同一文件或视频帧")
            locations.add(location)
            if candidate not in media:
                size = candidate.stat().st_size
                if size > MAX_MEDIA_BYTES:
                    raise ValueError("单个媒体文件不能超过 256 MiB")
                total_bytes += size
                if total_bytes > 1024 ** 3:
                    raise ValueError("数据集原始媒体总量不能超过 1 GiB")
                media[candidate] = file_digest(candidate)

        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.root) as temporary:
            staging = Path(temporary)
            indexed_records = {}
            for index, sample, source, frame in self._frames(path.parent, manifest.samples):
                frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(".png", frame)
                if not ok:
                    raise ValueError(f"样本 {sample.id}：无法编码图像")
                content = encoded.tobytes()
                asset = f"{index:04d}.png"
                (staging / asset).write_bytes(content)
                indexed_records[index] = {**sample.model_dump(), "asset": asset,
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "media_sha256": media[source]}
            # Detect source edits during import; never publish a partially imported dataset.
            if any(file_digest(p) != sha for p, sha in media.items()):
                raise ValueError("导入期间媒体发生变化，请固定文件后重试")
            records = [indexed_records[index] for index in range(len(manifest.samples))]
            if lineage is not None:
                if set(lineage) != {s['id'] for s in records}:
                    raise ValueError('编排来源记录与样本不匹配')
                records = [{**record, 'lineage': lineage[record['id']]} for record in records]
            saved = {"schema_version": 1, "name": manifest.name, "description": manifest.description,
                     "normalization": "640x480 BGR; INTER_AREA; PNG", "samples": records}
            dataset_id = digest(saved)
            (staging / "manifest.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            destination = self.directory(dataset_id)
            if destination.exists():
                self.load(dataset_id)
                for sample in records:
                    self.image(dataset_id, sample)
            else:
                # Rename a complete directory atomically; temporary directory cleanup handles failures.
                try:
                    staging.rename(destination)
                except OSError:
                    if not destination.exists():
                        raise
                    self.load(dataset_id)
            return self.summary(dataset_id, saved)
