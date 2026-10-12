# 公开数据验证计划与证据

公开工业数据用于补充真实图像与受控变化的算法验证。它们不是本工作站的真实工位采集、独立产线标签或用户收益证据；类别／拍摄划分也不能冒称现场采集批次。图像预处理遵循工作台的 640 × 480 归一化方式，但固定相机视场、标定、曝光控制和设备读数在公开数据上均未验证。

## 数据集选择

| 数据集 | 合适问题 | 适用限制 |
| --- | --- | --- |
| [VisA](https://github.com/amazon-science/spot-diff/tree/2a692ab575001cbde74d402d897a7286086c6199) | PCB1–PCB4 的真实正常／异常图像、像素掩码、图像级异常筛查基准 | CC BY 4.0；原始包约 1.93 GB。官方 train/test 是算法划分，不是现场批次。PCB1 实际预览存在正常与异常样本的朝向差异，须排查姿态混杂。当前先测 PCB1 有界子集与轻量正常样本异常基线，不声称完整 SOTA 检测器。 |
| [MVTec AD 2](https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2) | 更困难的受控工业场景与未见光照条件；公开 test 有像素级异常标签 | 八类、总计超过 8,000 张高分辨率图像。test 另有不公开标签的部分，须通过官方评测服务器。CC BY-NC-SA 4.0，明示不得商用；下载须登记。此许可证对本项目使用是否合适需按计划用途确认，暂不自动下载或打包。 |
| [AeBAD](https://github.com/zhangzilongc/MMR/tree/22d1b171687509024e6f5b53b5a5e772d653d32b) | 航空发动机叶片外观异常，以及未见照明、视角和背景域偏移；AeBAD-S 有图像掩码，AeBAD-V 为视频域偏移 | 目标不是 PCB。官方 README 指出训练与测试的 background/view/illumination 不同。仓库代码 Apache-2.0；数据单独按 CC BY 4.0。Google Drive 下载请求超时；天翼云公开分享页返回 200，但未完成数据下载或账号操作。本轮未测试。 |

因此验证分两层：VisA PCB 检查单帧真实缺陷外观上的异常分数能力；MVTec AD 2、AeBAD 检查训练域外的照明与视角变化。后两类也混合了物体／背景变化，不能把检测变化单独归因为成像漂移。要检验现场告警可靠性，仍需对同一实体、固定曝光／白平衡、独立改变照明或视角，并保留环境与设备读数。

## VisA PCB1 初始实验

`prepare_visa.py` 读取固定上游提交 `2a692ab575001cbde74d402d897a7286086c6199` 的 `split_csv/1cls.csv`，按文件名排序后选择指定数量的 PCB1 train-normal、test-normal 和 test-anomaly。图像使用 HTTP Range 从官方 S3 tar 读取，只保存所选图像、CSV 和摘要元数据，不克隆仓库或把数据提交到 Git。来源记录保留仓库 revision、ETag、原始 tar 路径、分区和单图 SHA-256。结果目录默认位于被忽略的 `data/public-datasets/`。

CSV SHA-256 固定为 `a48557e6033318cb90556f706196bc9d247a776a23ea51aecee5a80dd0332995`；S3 ETag 为 `"05c830591a1172938cb714895c9e0cfb-113"`，总大小 `1929840640` 字节。脚本读取固定归档的约 300 MiB 区域，逐段核对 206、Content-Range、ETag 和长度，并校验 tar 头及精确文件名；这不是全归档 SHA 校验。版本隔离的本地分段缓存通过旁车摘要检测本地损坏，旁车不是上游权威摘要。数据目录完整写入后才重命名发布，失败清理临时内容，已有目录拒绝覆盖。

`benchmark_public_data.py` 是从零实现的轻量方法，不使用预训练权重：正常 train 图像拟合固定网格 Lab patch 对角高斯；独立保留的 20 张 train-normal 标定 95% 阈值；test 标签只在预测和阈值固定后计算 image AUROC、召回和误报。它不是 PatchCore、PaDiM，也不做像素定位。结果包括逐图预测与来源 SHA，且重写报告前拒绝已存在目标。生成的数据集清单只把异常样本标为缺陷，cause 保持 unknown；测试集保持原官方文件划分身份，不伪造独立工位批次。

```sh
python scripts/prepare_visa.py --train 60 --normal 40 --anomaly 40
python scripts/benchmark_public_data.py
python scripts/test_public_data_ui.py --url http://127.0.0.1:8501 --manifest artifacts/public-data-visa-pcb1/manifest.json
```

评估公开数据时应在“样本管理”导入生成的 `manifest.json`，把官方 train-normal 用作参考，test-normal 与 test-anomaly 用作评估；回放指标将报告合成／真实来源、重复图像和批次警告。该固定回放使用项目现有参考残差代理；图像级缺陷检测器的独立异常分数另由 benchmark 输出，不伪装成已接入的现场检测器或 Spark 推理。

## 本轮实际状态

后续 ResNet18／PaDiM 离线模型及姿态消融已经实际执行并接入工作台。未对齐／对齐版的召回为 100%／52.5%、误报为 22.5%／5%；每个姿态组均缺少另一类，不能直接认定高分来自缺陷外观。完整方法、版本与结果见[视觉检测](visual-detector.md)，下文保留初始手工基线记录，不覆盖历史证据。

2026-10-09，macOS arm64、Python 3.12，已下载 140 张真实公开图像：官方 train-normal 60 张，test-normal 40 张，test-anomaly 40 张。拟合使用前 40 张 train-normal，末 20 张仅用于正常分数阈值标定；未使用测试标签调参或阈值。首轮报告及逐图分数保存在 `artifacts/public-data-visa-pcb1/benchmark.json`；最终脚本重跑至 `artifacts/public-data-visa-pcb1-final/benchmark.json`，指标和数据集 ID 一致，源码摘要独立记录。

| 指标 | 实测 |
| --- | --- |
| image AUROC | 0.993125 |
| TP / TN / FP / FN | 40 / 31 / 9 / 0 |
| 缺陷召回 | 40/40 = 100% |
| 正常误报率 | 9/40 = 22.5% |

高 AUROC 只说明该小子集分数可分，正常误报偏高且抽样不具随机代表性。实际查看正常与异常各三张图发现器件朝向差异，因此分数可能依赖姿态／分区特征，尚未证明识别了缺陷本身。下一步应采用成熟 PatchCore／PaDiM 等方法，保留固定参数，在完整 PCB 类别及姿态分组上验证；对齐需只用正常训练数据建立，不根据测试标签选择旋转或阈值。原图经两条方法分别缩放至 320 × 240 与工作台 640 × 480，会改变非 4:3 比例，不进行尺寸计量。

工作台导入另保留 40 张拟合参考与 80 张评估，数据集 ID 为 `2f82e0dbc521ceba6024c7b20a63d0e238c6878a2ab413138ab2aa492f2e8d84`。独立数据库完整回放 80/80，参考代理检测状态全部 `ok`，无缺失／失败／超时；该状态只表示处理成功。归一化参考／评估无像素重复，80 张评估像素各异，但分区独立性仍是上游声明。规则观测为稳定 18、光学 3、机械 20、证据不足 39；40 张正常测试图中稳定 18、机械 20、证据不足 2。没有原因真值，不计算原因准确率；这些机械规则提示暴露了配准／姿态敏感性，不能认定现场设备移动。回放和评估 JSON 位于同目录的 `workstation-{replay,evaluation}.json`。

独立高斯异常分数未接入工作台检测结果包，也未冒充校准置信度。原始数据、归一化图像、数据库和报告均不提交 Git 或源码 ZIP，重新实验须指定新输出目录；实验目录在报告、图像、清单和导入验证全部成功后才发布，失败清理临时内容。浏览器脚本应只对专用实例执行。

- 已核验官方 VisA README 数据规模、PCB 子集和 CC BY 4.0；固定上游 commit 与官方 S3 ETag／大小已记录。
- 已核验 MVTec AD 2 官方页面的光照设计、公开／私有测试划分、下载登记和 CC BY-NC-SA 4.0 商用限制。
- 已核验 AeBAD 官方 README、`datasets/aebad_S.py` 与 `LICENSE-DATASET`：光照／视角／背景域偏移、S/V 子集、CC BY 4.0 数据许可。Google Drive 下载超时，天翼分享页面可访问但数据未取到。
- 初始手工基线无需 PyTorch；后续已安装可选 torch 2.8.0／torchvision 0.23.0 并运行本地 PaDiM，未运行官方 MMR 或 Spot-the-Difference 实现。
- 真实设备、相机采集、模型推理和产线指标不在公开图像离线实验范围内。任何指标只描述所选类别与文件子集，不外推现场效果。
