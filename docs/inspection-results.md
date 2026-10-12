# 外部质检结果接入

本模块接收上游检测器导出的 JSON 判定，并在数据集回放中替代参考残差代理。支持文件导入、版本固定、逐样本对齐、不可用状态留存、事件复核和结果导出。[PaDiM 离线检测](visual-detector.md)可生成真实异常分数结果包；当前没有实时设备协议。

## 使用流程

1. 按[样本管理](datasets.md)导入数据集，取得数据集 ID 与归一化图像摘要。可从 `GET /api/datasets/{dataset_id}` 或本地数据集目录的 `manifest.json` 获取。
2. 将上游输出转换为下述结果包。每个结果通过数据集 ID、样本 ID、图像 SHA-256 关联，不能只按文件行号拼接。
3. 在“设置与演示 → 样本管理与回放 → 质检结果来源”输入本地 JSON 路径，点击“导入检测结果”。
4. 选择外部结果版本并建立回放。该选择仅作用于新会话，已有回放继续使用原版本。
5. 在监测页查看当前判定、分数及可用性；缺失、失败、超时自动留存事件。回放导出包含完整结果包、配置及逐样本测量。

选择“参考残差 · 演示代理”可显式建立代理回放。普通摄像头与视频采集仍使用代理；外部文件只在数据集回放中启用。

## 结果包

```json
{
  "schema_version": 1,
  "dataset_id": "填写已导入数据集的64位SHA-256",
  "producer": {
    "name": "inspection-detector",
    "version": "weights-v1+thresholds-v2",
    "provenance": "upstream",
    "score_semantics": "decision_confidence"
  },
  "results": [
    {
      "sample_id": "batch-b-001",
      "image_sha256": "填写对应归一化图像的64位SHA-256",
      "status": "ok",
      "detected": true,
      "confidence": 0.93,
      "is_ng": true,
      "defect_types": ["scratch"]
    },
    {
      "sample_id": "batch-b-002",
      "image_sha256": "填写对应归一化图像的64位SHA-256",
      "status": "timeout",
      "error": "Detector exceeded the upstream inference deadline"
    }
  ]
}
```

示例中的摘要为说明占位，使用时须替换。JSON 最大 2 MiB，最多 500 条记录，拒绝未知字段和重复样本。结果行顺序不影响版本，同一内容重复导入复用原版本。

| 字段 | 含义与约束 |
| --- | --- |
| `producer.name`、`version` | 检测器及固定版本；版本应涵盖权重、预处理和判定阈值 |
| `provenance` | `upstream` 为导入者声明的上游输出；`synthetic_fixture` 为人工构造的演示结果，不代表真实推理 |
| `score_semantics` | v1 接收 `decision_confidence`：对该条 OK／NG 判定的置信度，范围 `[0,1]`。未经概率标定的异常分数须使用下述 v2 协议，不填入 confidence；不接收 logits |
| `detected` | 上游是否检测到待检目标；与结果调用是否成功分开。无目标时由上游明确给出对应判定 |
| `is_ng` | 上游判定，必须为布尔值；高置信度的 NG 仍是 NG，高分不代表合格概率 |
| `defect_types` | 上游预测的缺陷类别列表，可为空；OK 判定不能携带缺陷类别 |
| `status` | `ok`、`missing`、`error` 或 `timeout`；文件未提供的评估样本自动记为 `missing` |
| `error` | 失败或超时必须给出说明；原文保留在事件和导出中 |

v1 成功记录须提供 `detected`、`confidence`、`is_ng`。不可用记录不得携带判定、分数或缺陷类别，导入后这些数值保持 `null`。超时状态由上游记录，本模块不会根据文件时间推断超时。

基线的每个样本都必须有成功检测结果，缺失或失败时结果包仍可保存，但不能用于建立回放。基线允许上游判定包含 NG；这属于参考检测表现，不自动将其解释成真实缺陷。

## 异常分数协议 v2

原 `schema_version=1` 继续仅接受判定置信度，重新导入保持原版本摘要。`schema_version=2` 支持显式异常分数与可选姿态证据，示例结构为：

```json
{
  "schema_version": 2,
  "dataset_id": "填写数据集摘要",
  "producer": {
    "name": "PaDiM ResNet18",
    "version": "包含权重、拟合数据、预处理与阈值的版本摘要",
    "provenance": "upstream",
    "score_semantics": "anomaly_score",
    "decision_threshold": 21.15
  },
  "results": [
    {"sample_id": "样本ID", "image_sha256": "填写归一化像素摘要", "status": "ok",
     "detected": true, "confidence": null, "anomaly_score": 17.24, "is_ng": false}
  ]
}
```

摘要和数值为结构示意。异常分数与阈值必须有限且非负，`is_ng` 必须准确对应 `anomaly_score > decision_threshold`，等于阈值时判 OK。异常模式禁止提供置信度；置信度模式禁止混入异常分数或异常阈值。失败记录仍不得携带分数和判定，不补成低分正常。

可选 `alignment` 包含 `passed`／`disabled`／`rejected` 状态。通过须保留 `angle_deg`、`shift_x`、`shift_y`、`scale`、`inliers`、`inlier_ratio`、`reprojection_error`、`coverage`；拒绝须提供 `error`，不能同时为成功检测。系统只验证结构及有限数值，不替导入者证明对齐算法有效。

完整异常分数窗口仍计算检测可用性、NG率与检测率；判定置信度均值／标准差／范围、稳定性和综合启发式评分保持 `null`，不把 Mahalanobis 距离变成概率。原因规则可继续使用原图变化和 NG率。模型快照仅增加经协议约束的分数语义，原始异常分数、标签、文件名、对齐记录及错误原文仍不进入模型输入。

## 不可用状态与统计

回放遇到检测缺失、失败或超时，继续进行图像测量并留存该状态，绝不调用代理补齐。当前滑动窗口只要存在不可用结果，暂停 NG、置信度及稳定性统计，不复用前一个窗口的结论；综合启发式评分为 `null`。窗口内全部结果恢复可用且不少于 10 帧后，统计恢复。

此策略优先保证结果可解释，会降低稀疏数据下的统计覆盖率。界面分别显示图像规则观测、当前检测状态和一致性证据不足。检测不可用本身不被分类为产品缺陷。

独立人工标签、样本描述、上游类别及错误原文不进入模型快照。模型接收经过选择的测量指标、检测状态、可用性计数和来源类型；空统计用 `null` 表达。上游预测不等于独立真值，不能直接据此声称产线准确率。

## 版本与复现

结果包保存在运行数据库同级的 `inspection-results/`，默认 `data/db/inspection-results/`。内容摘要确定版本；导入时验证数据集与每条图像摘要，建立回放时再次校验结果文件。会话内使用固定的已加载结果，重导入不会替换当前回放。

回放配置记录检测模式、结果版本、来源与检测器版本。导出包含完整结果包，历史回放可在服务重启后继续导出。图像数据仍需另行保留。若人工修改或删除本地结果包，历史导出会报错，不会默认替换为其他版本。

没有上游输出时，可用明确标注的合成夹具验证流程：

```sh
python scripts/create_demo_results.py --manifest data/db/datasets/<数据集ID>/manifest.json --output data/demo-results.json
```

夹具人为构造缺失、超时、失败和 NG 判定，不执行缺陷识别。独立单测与浏览器验收分别运行：

```sh
python -m pytest tests/test_inspection_results.py -q
python scripts/test_inspection_ui.py --url http://127.0.0.1:8501 --channel chrome
```

浏览器验收仅对专用合成工作站执行，会导入夹具并切换回放会话。
