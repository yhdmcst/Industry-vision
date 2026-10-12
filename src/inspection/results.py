"""Versioned upstream inspection results aligned to immutable dataset samples."""

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.datasets import DatasetStore, digest
from src.monitoring import DetectionRecord

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SHA = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class Producer(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: Text
    version: Text
    provenance: Literal["upstream", "synthetic_fixture"]
    score_semantics: Literal["decision_confidence", "anomaly_score"]
    decision_threshold: float | None = Field(default=None, ge=0, strict=True)


class Alignment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    status: Literal['passed', 'disabled', 'rejected']
    angle_deg: float | None = None
    shift_x: float | None = None
    shift_y: float | None = None
    scale: float | None = Field(default=None, gt=0)
    inliers: int = Field(default=0, ge=0)
    inlier_ratio: float | None = Field(default=None, ge=0, le=1)
    reprojection_error: float | None = Field(default=None, ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1)
    error: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def complete_evidence(self):
        if self.status == 'passed' and (self.error.strip() or self.inliers == 0 or any(value is None for value in
                (self.angle_deg, self.shift_x, self.shift_y, self.scale, self.inlier_ratio, self.reprojection_error, self.coverage))):
            raise ValueError('对齐通过必须保留完整变换与质量证据')
        if self.status == 'rejected' and not self.error.strip():
            raise ValueError('对齐拒绝必须说明原因')
        return self


class InspectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_id: Text
    image_sha256: SHA
    status: Literal["ok", "error", "timeout", "missing"]
    detected: bool | None = Field(default=None, strict=True)
    confidence: float | None = Field(default=None, ge=0, le=1, strict=True)
    anomaly_score: float | None = Field(default=None, ge=0, strict=True)
    alignment: Alignment | None = None
    is_ng: bool | None = Field(default=None, strict=True)
    defect_types: list[Text] = Field(default_factory=list, max_length=30)
    error: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.status == "ok":
            if self.detected is None or self.is_ng is None:
                raise ValueError("成功结果必须提供 detected 和 is_ng")
            if self.error.strip() or (not self.is_ng and self.defect_types):
                raise ValueError("成功结果不能含错误；OK 判定不能含缺陷类别")
        elif (self.detected is not None or self.confidence is not None or self.anomaly_score is not None
              or self.is_ng is not None or self.defect_types):
            raise ValueError("失败、超时或缺失结果不能携带判定、分数或缺陷类别")
        elif self.status in ("error", "timeout") and not self.error.strip():
            raise ValueError("失败或超时必须保留错误说明")
        if len(set(self.defect_types)) != len(self.defect_types):
            raise ValueError("缺陷类别不能重复")
        if self.status == 'ok' and self.alignment and self.alignment.status == 'rejected':
            raise ValueError('对齐拒绝不能携带成功判定')
        return self


class ResultPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2]
    dataset_id: SHA
    producer: Producer
    results: list[InspectionResult] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_samples(self):
        if len({r.sample_id for r in self.results}) != len(self.results):
            raise ValueError("检测结果 sample_id 不能重复")
        anomaly = self.producer.score_semantics == 'anomaly_score'
        if self.schema_version == 1 and (anomaly or self.producer.decision_threshold is not None
                or any(r.anomaly_score is not None or r.alignment is not None for r in self.results)):
            raise ValueError('异常分数与对齐证据必须使用 schema_version=2')
        if anomaly != (self.producer.decision_threshold is not None):
            raise ValueError('异常分数必须声明判定阈值；置信度模式不能声明异常阈值')
        for result in self.results:
            if result.status != 'ok':
                continue
            if anomaly:
                if result.confidence is not None or result.anomaly_score is None:
                    raise ValueError('异常分数模式必须提供 anomaly_score，confidence 保持 null')
                if result.is_ng != (result.anomaly_score > self.producer.decision_threshold):
                    raise ValueError('NG 判定必须与 anomaly_score > decision_threshold 一致')
            elif result.confidence is None or result.anomaly_score is not None:
                raise ValueError('置信度模式必须提供 confidence，不能混入异常分数')
        return self


def aligned_result(package: dict, sample: dict) -> dict:
    return next((r for r in package["results"] if r["sample_id"] == sample["id"]), {
        "sample_id": sample["id"], "image_sha256": sample["sha256"], "status": "missing",
        "detected": None, "confidence": None, "is_ng": None, "defect_types": [],
        "error": "结果包未提供此样本的检测结果",
    })


def detection_record(package: dict, sample: dict, index: int) -> DetectionRecord:
    result = aligned_result(package, sample)
    return DetectionRecord(float(index), result["detected"], result["confidence"], result["is_ng"],
                           {"detector": "external_results", "producer": package["producer"],
                            "result": result}, status=result["status"])


class ResultStore:
    def __init__(self, root: Path, datasets: DatasetStore):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.datasets = datasets

    def load(self, result_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{64}", result_id):
            raise ValueError("无效的检测结果版本")
        try:
            package = json.loads((self.root / f"{result_id}.json").read_text(encoding="utf-8"))
            if digest(package) != result_id:
                raise ValueError("检测结果摘要不匹配，请检查本地存储")
            return package
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("检测结果不存在或文件损坏") from exc

    def summary(self, result_id: str, package: dict) -> dict:
        samples = self.datasets.load(package["dataset_id"])["samples"]
        counts = {status: 0 for status in ("ok", "error", "timeout", "missing")}
        baseline_ready = True
        for sample in samples:
            result = aligned_result(package, sample)
            counts[result["status"]] += 1
            if sample["split"] == "baseline" and result["status"] != "ok":
                baseline_ready = False
        return {"id": result_id, "dataset_id": package["dataset_id"], "producer": package["producer"],
                "counts": counts, "baseline_ready": baseline_ready}

    def catalog(self, dataset_id: str) -> list[dict]:
        self.datasets.load(dataset_id)
        items = []
        for path in sorted(self.root.glob("*.json")):
            package = self.load(path.stem)
            if package["dataset_id"] == dataset_id:
                items.append(self.summary(path.stem, package))
        return items

    def import_file(self, path: Path) -> dict:
        path = path.expanduser()
        try:
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("检测结果须为不超过 2 MiB 的本地 JSON 文件")
            validated = ResultPackage.model_validate_json(path.read_bytes())
            # Preserve canonical v1 hashes for already published confidence packages.
            excluded = ({'producer': {'decision_threshold'},
                         'results': {'__all__': {'anomaly_score', 'alignment'}}}
                        if validated.schema_version == 1 else None)
            package = validated.model_dump(exclude=excluded)
            samples = self.datasets.load(package["dataset_id"])["samples"]
            by_id = {s["id"]: s for s in samples}
            for result in package["results"]:
                if result["sample_id"] not in by_id:
                    raise ValueError(f"检测结果包含未知样本：{result['sample_id']}")
                if result["image_sha256"] != by_id[result["sample_id"]]["sha256"]:
                    raise ValueError(f"样本图像摘要不匹配：{result['sample_id']}")
            order = {sample["id"]: i for i, sample in enumerate(samples)}
            package["results"].sort(key=lambda r: order[r["sample_id"]])
            result_id = digest(package)
            destination = self.root / f"{result_id}.json"
            if destination.exists():
                self.load(result_id)
            else:
                fd, temporary = tempfile.mkstemp(prefix=".import-", dir=self.root)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(package, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    os.replace(temporary, destination)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            return self.summary(result_id, package)
        except OSError as exc:
            raise ValueError("无法读取或保存检测结果文件") from exc
