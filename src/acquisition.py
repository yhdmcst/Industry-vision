"""Operator-owned capture drafts; pixels and annotations publish as immutable datasets."""

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from pydantic import BaseModel, ConfigDict, Field

from src.datasets import DatasetStore, Label, MAX_SAMPLES, Sample, Text
from src.inspection.quality_gate import quality_reasons
from src.monitoring.image_analyzer import ImageQualityMetrics


@contextmanager
def acquisition_io():
    try:
        yield
    except OSError as exc:
        raise RuntimeError(f"采集文件保存或读取失败，未发布本次变更：{type(exc).__name__}") from exc


class BatchMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: Text
    description: str = Field(default="", max_length=2000)
    created: str = Field(min_length=1, max_length=100)


class CapturedRecord(Sample):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    capture_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    sequence: int = Field(ge=1, le=MAX_SAMPLES)
    source: str = Field(pattern=r"^(synthetic|camera|video)$")
    source_session: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_generation: int = Field(ge=0)
    source_properties: dict[str, float | None]
    image_quality: dict[str, float]
    quality_reasons: list[str]
    provenance: str = Field(pattern=r"^operator_capture_unverified_labels$")


def write_json(path: Path, value: dict):
    """Replace metadata atomically; a failed update keeps the old annotation."""
    fd, temporary = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class AcquisitionStore:
    def __init__(self, root: Path, datasets: DatasetStore):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.datasets = datasets

    def directory(self, batch_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
            raise ValueError("无效的采集批次标识")
        return self.root / batch_id

    def create(self, name: str, description: str) -> dict:
        batch_id = uuid.uuid4().hex
        payload = BatchMetadata(id=batch_id, name=name, description=description,
                                created=datetime.now(timezone.utc).isoformat()).model_dump()
        with tempfile.TemporaryDirectory(prefix=".batch-", dir=self.root) as temporary:
            staging = Path(temporary)
            write_json(staging / "batch.json", payload)
            staging.rename(self.directory(batch_id))
        return self.load(batch_id)

    def load(self, batch_id: str) -> dict:
        directory = self.directory(batch_id)
        try:
            batch = BatchMetadata.model_validate_json((directory / "batch.json").read_bytes()).model_dump()
            if batch["id"] != batch_id:
                raise ValueError("采集批次标识不匹配")
            records = []
            for path in directory.iterdir():
                if re.fullmatch(r"[a-f0-9]{32}", path.name):
                    record = CapturedRecord.model_validate_json((path / "sample.json").read_bytes()).model_dump()
                    if record["id"] != path.name or record["path"] != f"{path.name}/image.png":
                        raise ValueError("采集样本标识不匹配")
                    if any(key not in record["image_quality"] for key in ImageQualityMetrics.__dataclass_fields__):
                        raise ValueError("采集质量指标不完整")
                    if (record["quality_reasons"] != quality_reasons(record["image_quality"])
                            or record["perturbation"] != "none" or len(record["conditions"]) > 27
                            or (record["source"] == "synthetic" and record["origin"] != "synthetic")
                            or (record["source"] == "camera" and record["origin"] != "real")):
                        raise ValueError("采集来源或质量记录不一致")
                    self.validate_reference(record)
                    records.append(record)
            records.sort(key=lambda item: item["sequence"])
            if [r["sequence"] for r in records] != list(range(1, len(records) + 1)):
                raise ValueError("采集顺序记录不完整")
            return {**batch, "samples": records}
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError("采集批次不存在或记录损坏") from exc

    @staticmethod
    def summary(batch: dict) -> dict:
        samples = batch["samples"]
        hashes = [s["sha256"] for s in samples]
        return {k: v for k, v in batch.items() if k != "samples"} | {
            "sample_count": len(samples), "baseline_count": sum(s["split"] == "baseline" for s in samples),
            "evaluation_count": sum(s["split"] == "evaluation" for s in samples),
            "duplicate_images": len(hashes) - len(set(hashes)),
        }

    def catalog(self) -> list[dict]:
        batches = []
        for path in self.root.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}", path.name):
                try:
                    batches.append(self.summary(self.load(path.name)))
                except ValueError:
                    batches.append({"id": path.name, "name": "批次损坏", "error": "请检查本地存储"})
        return sorted(batches, key=lambda item: item.get("created", ""), reverse=True)

    def record(self, batch_id: str, sample_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}", sample_id):
            raise ValueError("无效的采集样本标识")
        batch = self.load(batch_id)
        record = next((s for s in batch["samples"] if s["id"] == sample_id), None)
        if record is None:
            raise ValueError("采集样本不存在")
        return record

    def image_bytes(self, batch_id: str, sample_id: str) -> bytes:
        record = self.record(batch_id, sample_id)
        return self._verified_image(self.directory(batch_id), record)

    @staticmethod
    def _verified_image(directory: Path, record: dict) -> bytes:
        try:
            content = (directory / record["id"] / "image.png").read_bytes()
        except OSError as exc:
            raise ValueError("采集图像不存在") from exc
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ValueError("采集图像摘要不匹配")
        return content

    def save(self, batch_id: str, preview: dict, content: bytes, *, split: str,
             origin: str, conditions: dict, label: dict) -> dict:
        batch = self.load(batch_id)
        if len(batch["samples"]) >= MAX_SAMPLES:
            raise ValueError("每个采集批次最多留存 500 个样本")
        if any(s["capture_token"] == preview["token"] for s in batch["samples"]):
            raise ValueError("此预览已留存，请重新采集一帧")
        sample_id = uuid.uuid4().hex
        sample = Sample(id=sample_id, batch=batch["name"], path=f"{sample_id}/image.png", split=split,
                        origin=origin, conditions=conditions, label=Label.model_validate(label),
                        captured_at=preview["created"])
        record = {**sample.model_dump(), "sha256": hashlib.sha256(content).hexdigest(),
                  "capture_token": preview["token"], "source": preview["source"],
                  "sequence": len(batch["samples"]) + 1,
                  "source_session": preview["session"], "source_generation": preview["generation"],
                  "source_properties": preview["source_properties"], "image_quality": preview["image_quality"],
                  "quality_reasons": preview["quality_reasons"], "provenance": "operator_capture_unverified_labels"}
        record = CapturedRecord.model_validate(record).model_dump()
        self.validate_reference(record)
        with tempfile.TemporaryDirectory(prefix=".sample-", dir=self.directory(batch_id)) as temporary:
            staging = Path(temporary)
            (staging / "image.png").write_bytes(content)
            write_json(staging / "sample.json", record)
            staging.rename(self.directory(batch_id) / sample_id)
        return record

    @staticmethod
    def validate_reference(record: dict):
        if record["split"] == "baseline" and (quality_reasons(record["image_quality"]) or
                record["label"]["defect"] == "defect" or record["label"]["cause"] not in ("none", "unknown")):
            raise ValueError("基线样本必须通过取景质量门，且不能标注为缺陷或异常原因")

    def annotate(self, batch_id: str, sample_id: str, *, split: str, conditions: dict, label: dict) -> dict:
        record = self.record(batch_id, sample_id)
        validated = Sample.model_validate({k: v for k, v in record.items() if k in Sample.model_fields} |
                                          {"split": split, "conditions": conditions, "label": label})
        record = {**record, **validated.model_dump()}
        self.validate_reference(record)
        write_json(self.directory(batch_id) / sample_id / "sample.json", record)
        return record

    def publish(self, batch_id: str) -> dict:
        batch = self.load(batch_id)
        # DatasetStore validates partition counts and performs its usual atomic publication.
        with tempfile.TemporaryDirectory(prefix=".publish-", dir=self.directory(batch_id)) as temporary:
            staging = Path(temporary)
            samples = []
            for record in batch["samples"]:
                self.validate_reference(record)
                content = self._verified_image(self.directory(batch_id), record)
                filename = f"{record['id']}.png"
                (staging / filename).write_bytes(content)
                conditions = {**record["conditions"], "capture_source": record["source"],
                              "capture_batch_id": batch_id, "capture_session": record["source_session"]}
                samples.append({k: v for k, v in record.items() if k in Sample.model_fields} |
                               {"path": filename, "conditions": conditions})
            manifest = staging / "manifest.json"
            write_json(manifest, {"schema_version": 1, "name": batch["name"],
                                  "description": batch["description"], "samples": samples})
            return self.datasets.import_manifest(manifest)
