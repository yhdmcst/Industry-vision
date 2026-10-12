# 第三方组件与原创边界

现有方案与代码由当前工作目录提供。此次工程迭代保留其工业质检漂移监测方向，补充真实推理、异步复核、证据、测试与提交材料。不推定原始代码的所有权或授权情况，团队提交前应核验。

| 组件 | 用途 | 许可证 / 核验方式 |
| --- | --- | --- |
| Spark-X2.5 官方模型 | 文本证据复核 | Apache-2.0，官方 README 与模型仓库 LICENSE |
| Qwen3-4B 官方 GGUF | 独立架构研究对照，不用于日常模型切换 | Apache-2.0，固定官方仓库及清单，见下文 |
| Ollama | 本地 GGUF 推理，包含 llama.cpp 运行能力 | 保留对应版本的上游许可证与依赖声明 |
| OpenCV | 图像质量、配准与合成扰动 | 查安装发行版及对应上游 LICENSE |
| React / React DOM / Vite / TypeScript | 独立前端与构建 | React、Vite 为 MIT；TypeScript 为 Apache-2.0，见 npm 发行包 LICENSE |
| Recharts / Lucide | 趋势图与图标 | Recharts 为 MIT；Lucide 为 ISC，见 npm 发行包 LICENSE |
| FastAPI / Uvicorn | 本地 API、后台服务与静态托管 | FastAPI 为 MIT；Uvicorn 为 BSD-3-Clause，见安装发行版许可 |
| SQLite / Python | 本地证据持久化与应用 | 各自上游许可证 |
| NumPy / SciPy | 数值计算 | 各自上游许可证 |
| python-pptx | 可编辑提交材料 | 各自上游许可证 |
| Playwright / Edge | 自动化浏览器验证 | 各自上游许可与使用条款 |

本项目没有训练新的基础模型，也不把上游框架算法宣称为原创。候选创新是面向质检现场的证据组织、竞争原因复核和人工验证闭环；真实用户增益尚需实验验证。

## 公开数据来源

本轮通过 GitHub 和官方数据入口访问，未克隆或复制下列仓库实现代码。下载的图像与标注只用于本地实验，不随源码分发；数据许可与代码许可分别核验。

| 来源与固定版本 | 核对文件／页面 | 使用方式与许可 |
| --- | --- | --- |
| [amazon-science/spot-diff](https://github.com/amazon-science/spot-diff/tree/2a692ab575001cbde74d402d897a7286086c6199) | `README.md`、`split_csv/1cls.csv`、README 的官方 VisA S3 tar | PCB1 开发对照、PCB2／PCB4 独立最终评估及 PCB3 留出根图像的指标复核；数据 CC BY 4.0。本地方法独立编写，不复制 Spot-the-Difference 代码。 |
| [zhangzilongc/MMR](https://github.com/zhangzilongc/MMR/tree/22d1b171687509024e6f5b53b5a5e772d653d32b) | `README.md`、`datasets/aebad_S.py`、`LICENSE-DATASET` | 仅研究 AeBAD 域偏移设计和读取约定，尚未获得数据或运行 MMR；代码 Apache-2.0、数据 CC BY 4.0。 |
| [MVTec AD 2 官方页](https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2)及[直接下载页](https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2/downloads) | 官方 vial 归档 ETag `67e6a011-3067295c`、`readme.txt`、`license.txt`、train／validation／test_public 目录；2026-10-09 访问 | 下载并运行公共真实照明实验，未复制上游算法实现或提交私有评测。数据 CC BY-NC-SA 4.0，官方明确不得商用。字节摘要、局限和命令见[研发验收](vision-acceptance.md)。 |

VisA 作者来源为 Zou 等，*SPot-the-Difference Self-Supervised Pre-training for Anomaly Detection and Segmentation*，ECCV 2022。来源摘要、逐图文件身份和实测边界见[公开数据实验](public-data.md)。

MVTec AD 2 作者为 Lars Heckler-Kram、Jan-Hendrik Neudeck、Ulla Scheler、Rebecca König、Carsten Steger，*The MVTec AD 2 Dataset: Advanced Scenarios for Unsupervised Anomaly Detection*，arXiv:2503.21622，2025。归档内 README 要求科学研究引用此文；本项目保留原始归档于本地，不将数据或派生图片放入源码包。

## 视觉异常检测来源

成像域本地入口通过 GitHub 读取上述 MMR 固定版本的 `datasets/aebad_S.py`，核对 `good`、异常子目录以及 `same`／`background`／`illumination`／`view` 的 PNG 布局；未复制实现。新脚本独立准备本地文件并使用本项目 PaDiM；真实 AeBAD 数据仍未取得，夹具验证不能称域偏移实测。

- PaDiM 方法来源：[Defard 等，PaDiM: a Patch Distribution Modeling Framework for Anomaly Detection and Localization](https://arxiv.org/abs/2011.08785)。本地独立实现空间多元高斯与 Mahalanobis 距离，不宣称论文算法原创。
- 通过 GitHub 阅读 [taikiinoue45/PaDiM，固定提交 e67fae9a4c029180dbd8c747a3e0cf842a0f01e3](https://github.com/taikiinoue45/PaDiM/tree/e67fae9a4c029180dbd8c747a3e0cf842a0f01e3) 的 `README.md`、`LICENSE`、`padim/runner/runner.py`，核对空间统计、特征组合和距离计算思路。仓库 MIT；未克隆或复制其实现。本项目使用 ResNet18、Gaussian 平滑及独立正常阈值，不声称复现该仓库的 WideResNet 结果。
- 可选依赖固定为 torch 2.8.0、torchvision 0.23.0，分别核对发行包许可证；torchvision 为 BSD-3-Clause。ResNet 定义通过安装的 torchvision API 使用，权重 URL 来自该版本 `torchvision/models/resnet.py` 的 `ResNet18_Weights.IMAGENET1K_V1`，完整 SHA 见[检测说明](visual-detector.md)。权重不随源码分发。
- [torchvision v0.23.0 官方权重说明](https://github.com/pytorch/vision/blob/v0.23.0/docs/source/models.rst)指出预训练权重可能受训练数据的独立条款约束。代码许可证不等同权重的商业使用授权；本轮使用固定 ImageNet 权重作本地算法实验，未将其标为 CC BY 的 VisA 数据或宣称商用授权已核验。

Python 安装版本固定在 `requirements-lock.txt`，前端版本固定在 `frontend/package-lock.json`。界面参考位置与借鉴边界见 [UI 设计](ui-design.md)。分发第三方可执行文件或大模型权重前，应附各组件许可证，不因本 README 而免除许可义务。提交 ZIP 默认不分发 Ollama 可执行文件与权重。

## 本地推理运行时

研究模型使用 [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/bc640142c66e1fdd12af0bd68f40445458f3869b) 固定版本 `bc640142c66e1fdd12af0bd68f40445458f3869b` 的 `Qwen3-4B-Q4_K_M.gguf`；核对官方文件元数据、模型说明与 Apache-2.0 许可。官方 [ModelScope 镜像](https://modelscope.cn/models/Qwen/Qwen3-4B-GGUF) 固定 revision `8cca206c792af04f8d452368bd30b43ec18007f1`，文件大小 2497280256 bytes、SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` 与官方 Hugging Face LFS 元数据一致。仅下载并调用该权重；未克隆仓库、复制模型实现或训练新模型，不分发权重。研究用途与操作见[复核评估](review-evaluation.md)，清单位于 `models/research-qwen3-4b.json`。

通过 GitHub 直接读取 [ollama/ollama v0.40.2](https://github.com/ollama/ollama/tree/v0.40.2) 的 `LICENSE`、`docs/faq.mdx` 和 release 资产元数据；未克隆仓库或复制其实现。Ollama 为 MIT。独立安装脚本固定官方 `ollama-darwin.tgz` 大小 167473220 bytes 与 release 声明的 SHA-256 `e888b7637291ceb80b622c00ea067f62c86d9c50d419b3eb903032e4f1f8a4f6`，直接下载、校验并解包；归档内附带依赖许可随本地安装保留，不随源码包分发。服务配置参考官方 FAQ 的 `OLLAMA_HOST`、`OLLAMA_MODELS` 与 `OLLAMA_NO_CLOUD`；实际 Spark 模型由该版本的 llama.cpp runner 执行，不将归档包含 MLX 库视为已采用 MLX 推理。

Windows x64／arm64 portable ZIP 与 Linux x64／arm64 tar.zst 同样来自 [v0.40.2 release](https://github.com/ollama/ollama/releases/tag/v0.40.2)，大小与摘要固定在 `models/runtime-platforms.json`。独立下载与安全解包实现位于 `src/llm/preparation.py`，未复制上游代码。Zstandard 通过 Python `zstandard` 解压；发行包包含其许可与上游声明。运行包不随源码分发。
