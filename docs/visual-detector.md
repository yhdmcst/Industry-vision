# PaDiM 离线检测与姿态对齐

本模块用 ImageNet 预训练 ResNet18 提取真实图像特征，按 PaDiM 方法仅拟合正常样本，导出可导入工作台的固定检测结果。原图成像指标、检测器异常分数和独立标签分别保留；不训练基础模型，不自动控制设备。后续通过固定配方接入本地视频／摄像头，实际验收使用生成视频；步骤见[视觉验证与实时接入](vision-validation.md)。

## 复现与工作台

默认工作台无需 PyTorch。执行离线实验时安装可选依赖并下载固定官方权重：

```sh
python -m pip install -r requirements-vision.txt
python scripts/fetch_vision_weights.py
python scripts/run_padim.py --output artifacts/padim-visa-pcb1
```

默认输入为上一模块准备的 `data/public-datasets/visa-pcb1/` 和 `artifacts/public-data-visa-pcb1-final/manifest.json`。若尚未准备，按[公开数据实验](public-data.md)下载，再执行 `python scripts/benchmark_public_data.py --output artifacts/public-data-visa-pcb1-final`。已有目录拒绝覆盖；重跑应指定新 `--output`。CLI 可通过 `--manifest`、`--source`、`--weights` 指定路径，当前协议针对带官方原文件身份的 VisA 实验，不自动推断任意现场数据的训练划分。

1. 在“样本管理与回放”导入原始数据集清单。
2. 导入实验目录内的 `raw/inspection-results.json` 或 `aligned/inspection-results.json`，选择固定版本，再建立回放。两版均为实际模型输出，独立缺陷标签不参与推理。
3. 在监测或事件详情查看异常分数、固定阈值、原图和对齐质量；置信度显示“—”。在“回放评估”核对混淆矩阵、失败分母、逐图记录及同条件版本对比。

结果包按原始归一化图像 SHA-256 对齐。对齐后的像素仅送检测器，工作台继续观测原图，所以机械规则不会因检测器对齐被消除。`detected=true` 声明输入为已知待检物的整帧 ROI；该实验没有训练或运行目标定位器，不能用于证明空场中存在 PCB。

## 固定方法

- 输入从工作台固定的 640 × 480 BGR 像素转换 RGB，整图缩放到 224 × 224，按 ImageNet mean/std 归一化。没有中心裁剪，不使用测试集分数 min/max 归一化；非原比例缩放不用于尺寸计量。
- 使用 torchvision 0.23.0 的 ResNet18 `IMAGENET1K_V1`，CPU、eval/inference mode；组合 layer1/2/3 特征，将后两层按最近邻映射到 56 × 56 网格。在 448 个通道中用固定 NumPy seed 0 无放回选择 100 个。
- 每个空间位置保存完整 100 × 100 正常样本协方差，使用 `1/(N-1)`，加 `0.01 I` 正则，再计算 Mahalanobis 距离。距离图双线性扩展为 224 × 224，Gaussian sigma=4 平滑，图像分数取最大值。这是论文方法的独立实现，不是上轮手工 Lab 对角高斯，也不宣称复现上游全部训练或指标。
- 官方 train-normal 按固定文件名排序，前 40 张拟合、末 20 张仅标定；正常分数第 95 百分位的 higher quantile 为固定阈值。测试标签在所有预测结束后才加入报告；训练、阈值和对齐不查看测试标签。
- 核验全部源图 SHA-256，要求清单参考组准确对应固定拟合组，归一化像素逐图匹配官方源图；训练／标定重复像素拒绝。特征批次严格止于参考组末尾，避免不足 8 张的末批读入评估图像。

`raw` 和 `aligned` 使用相同拟合／标定／评估身份、权重及算法参数，各自仅在对应正常标定图像上确定阈值。每版的分数尺度可能不同，不比较分数数值高低。两版比较的是包含独立正常标定的完整流程。

## 姿态质量门

参考为清单中首张正常拟合图，不使用测试图或标签挑参考。ORB 2500 个特征、0.75 比率匹配、参考特征唯一对应；RANSAC 仅估计平移、旋转和统一尺度的相似变换，不允许镜像或投影变形。

至少 12 个内点、内点比例 0.35、尺度 0.85–1.15、中位重投影误差不超过 3 px、有效画面覆盖至少 80%，且内点凸包覆盖参考画面至少 5%。通过后按线性插值变换，边界使用 reflect padding；这些条件防止明显坏匹配，不证明缺陷没有被插值削弱，也不证明同一实体或正确目标。

对齐记录保留旋转角、仿射平移项、尺度、内点数／比例、重投影误差和覆盖率。平移项包含绕原点旋转的补偿，不直接等同工位物理位移。质量门拒绝时无成功判定或分数；不回退原图冒充对齐成功。参考或标定对齐失败时，该版本不发布模型与检测结果，错误保留在实验报告。

逐图特征／分数推理失败导出 `status=error` 和错误说明，不提供判定或分数；若发生在参考组，结果包不可建立回放。拟合、阈值标定或存储失败终止实验并清理未发布目录，不覆盖旧证据。

## 实测与取舍

2026-10-09，macOS arm64、Python 3.12、torch 2.8.0、torchvision 0.23.0；真实公开 PCB1 图像，40 张正常拟合、20 张正常标定、80 张测试。未执行 Spark 推理或真实相机采集。

| 方法 | AUROC | TP / TN / FP / FN | 召回 | 正常误报 |
| --- | --- | --- | --- | --- |
| 未对齐 PaDiM | 1.0000 | 40 / 31 / 9 / 0 | 100% | 22.5% |
| 对齐 PaDiM | 0.9625 | 21 / 38 / 2 / 19 | 52.5% | 5.0% |

对齐降低误报，也漏掉 19 张异常，不能直接推荐为更优生产版本。本子集 40 张正常测试图均接近参考方向，40 张异常图均旋转约 180°，每个姿态分组缺少另一类，组内 AUROC 无法计算。未对齐的高 AUROC 因此不能证明分数识别了缺陷外观；对齐也可能去除本应检测的摆位异常。若反向摆放属于工位缺陷，应单独保留姿态规则，不能自动旋转掩盖。后续须补齐两种姿态的正常与缺陷图，或采集固定摆位的独立工位数据。

原图、对齐热图中的漏检、命中及误报示例已实际查看；有正常误报的热点在背景，热图不是独立缺陷掩码。未下载像素真值，未计算定位准确率。配准质量通过也不保证缺陷筛查可靠。

当前交付代码的重跑位于本地 `artifacts/padim-visa-pcb1-verified/`；先前实验目录保留，指标保持一致。保存 `experiment.json`、两版结果包、`normal-model.npz` 均值／逆协方差证据，以及按正常标定阈值着色的逐图热图。权重、模型统计、图像和报告不入 Git 或源码 ZIP；热图当前只保存在实验目录，工作台显示原图及对齐记录。报告的 `prediction_ms_p50` 只计 CPU 特征提取与分数计算，排除解码、对齐、训练和可视化 I/O，不能当作摄像头端到端延迟。

## 权重与验证

后续扩展到新增 120 张原图，两个姿态组都包含正常与缺陷：原图模型召回 95%、误报 58.3%，对齐模型召回 50%、误报 3.3%。两版仍不推荐为生产默认。新样本排除、姿态分组与固定旋转配对见[视觉验证](vision-validation.md)；上文 80 张保留为初始实验记录。

官方 URL：`https://download.pytorch.org/models/resnet18-f37072fd.pth`。固定完整 SHA-256：`f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec`。下载失败清理临时文件，加载前重验摘要，并使用 `torch.load(weights_only=True)`；既有损坏权重拒绝覆盖。运行实验不会隐式联网下载权重。

```sh
python -m pytest tests/test_anomaly_results.py tests/test_visual_detector.py tests/test_padim_experiment.py tests/test_vision_weights.py -q
python scripts/test_anomaly_ui.py --url http://127.0.0.1:8501 --manifest artifacts/public-data-visa-pcb1-final/manifest.json --experiment artifacts/padim-visa-pcb1-verified
```

浏览器脚本只对专用实例执行，回放真实两版输出，另注入明确标记为合成夹具的对齐拒绝记录，验证错误呈现；注入记录不参与实际准确率。后续已完成独立进程的视频推理链路，未验证真实摄像头吞吐、现场误报、功耗或工业设备协议。来源及权重使用边界见[第三方说明](third_party.md)。
