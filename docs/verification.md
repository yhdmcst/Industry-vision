# 验证记录

## 工作空间交互优化 — 2026-10-10

macOS arm64／Python 3.12／Chrome，隔离合成工作台：事件草稿跨轮询、切页和刷新保留，跨事件不串写，人工保存及清空、同步缩放、本机路径浏览、桌面和 390px 布局、维护操作与 SQLite 下载通过。API 专项 10 项通过，React 构建通过。浏览器记录在 `artifacts/ui-refinements-interaction-v3/`；未调用语言模型、打开相机或开展效果实验。

## 历史与工作空间维护 — 2026-10-10

27 项相关测试通过：超过 200 个事件分页、超过 10000 条关联记录仍完整、保留范围与预览变化拒绝、先核验归档再释放、工作空间像素与配置恢复、摘要损坏和路径越界拒绝、维护期间拒绝写入。Chrome 隔离工作台完成工作空间下载与实际恢复、归档预览／确认／下载入口和空间回收；记录在 `artifacts/ui-refinements-storage/`。不包含设备迁移或语言模型效果验证。

## 剩余优化最终验证 — 2026-10-10

当前本机后端全量 **422 项通过**（95.27 秒），React 生产构建／Prettier、Python 源码编译和 diff 检查通过；保留一条上游 Starlette TestClient 弃用警告。新增模型测试覆盖封存摘要／阈值／ROI／来源／回执变化拒绝、依赖不匹配拒绝、同身份修复和写入失败回滚、在用版本禁止维护、回收区恢复；受控夹具不会宣称真实效果证据。

Apple M4／24GiB、macOS arm64、Python 3.12、CPU PyTorch 2.8.0／torchvision 0.23.0、Chrome：隔离工作台实际加载原有 PCB1 配方与 PCB4 封存协议部署版本，完成文件受损反馈／修复、预览卸载／回收恢复、工作空间下载及实际恢复、旧会话归档／空间回收、页面和终端诊断、分页和状态筛选、桌面／390px 功能检查。记录在 `artifacts/ui-refinements-reviewed/`；没有语言模型生成、摄像头或效果实验。

PCB4 部署阈值仍为 13.790014266967773，原封存摘要 `c05231368afe8a3d04a1ad91a2cd682dad13844f8d2ef2287432ee0c49f8e16a` 保留。对已观察的拟合参考图执行直接与独立进程推理，分数／判定一致，结果在 `artifacts/visual-deploy-refinements/process-parity-final.json`。不读取最终图像或重新拟合，不产生新的召回／误报率。未改变日常 8501／11435 服务和默认模型。

## P1 视觉与独立复核对照 — 2026-10-10

环境：Apple M4／24GiB、macOS 26.6 arm64、Python 3.12、torch 2.8.0／torchvision 0.23.0、Ollama 0.40.2、Chrome 155。视觉在 CPU 运行，模型在允许 Metal 的独立 11436 服务运行；浏览器使用独立临时数据库。未打开摄像头、改动默认模型选择、覆盖历史基准或生成 PPT。

当前最终验证：后端 `python -m pytest tests -q` 386 项通过（83.10 秒），前端生产构建、格式检查、Python 源码编译和 diff 检查通过；保留一条上游 Starlette TestClient 弃用警告。源码包白名单覆盖新增研究清单、视觉验收及长测说明，不含权重或本机实验目录。

- 新增固定收缩 PaDiM 和密集 patch 记忆候选，共 11 路；PCB1 及 PCB2 已观察验证集未证明新算法收益。新增 PCB4 先划分、验证选择、冻结后最终集单次消费；原有对齐 ROI PaDiM 最终 48 TP／45 TN／5 FP／2 FN，96% 召回／10% 误报／100% 覆盖，通过公开图像级点估计门槛。误报恰上限，区间较宽，不作为现场或新算法成功证据；未替换实时默认模型，PCB2 原失败记录保留。
- 固定官方 Qwen3-4B GGUF 通过同一大小与 SHA-256 校验；研究题库新增第五候选，生产管理仍仅官方 Spark。80 次真实调用均有结构化结果且 ≤30 秒，规则／4B 两路／1.7B／Qwen 类别一致为 20/20、20/20、20/20、14/20、11/20。只有已观察公开图像的 4 个根，软件变化标签、脚本检测及针对 Spark 优化的提示词均如实声明，不宣称架构排名、优于规则或用户收益。
- 人工三维配对展示、待配对分母、第五候选、固定请求参数和满规模评分容量已覆盖。全部真实人工评分仍为空、整体 `accepted=false`；UI 评分／写失败是单独明确夹具，不算真人质量证据。历史 PCB3 原 study／report 摘要实测不变，当前实验重新统计摘要也不变。
- Chrome 实际导入真实五方法报告、下载报告与匿名卡、待评展示、评分保存失败后重试、部分保存、原版本保留、刷新与读取失败恢复；桌面和 390px 截图已查看，配对指标逐项排列且无文档横向溢出或页面异常。日常合成工作台另做浏览器回归。最终专项在 `artifacts/ui-p1-independent-review-final/`，回归在 `artifacts/ui-p1-workbench-regression/`，真实实验在 `artifacts/p1-review-independent/experiment-metal/run/`；详见[复核结果](review-evaluation.md)与[视觉验收](vision-acceptance.md)。这些本机目录不入源码包。
- 首轮模型调用被沙箱 Metal 限制全部失败，原失败包保留；新开发目录在允许 GPU 的环境运行，不混入成功结果。11436 服务正常关闭，receipt 为 `stopped`，端口已关闭；日常 8501／11435 健康。启动前拒绝源码不匹配或已消费题库，失败／中断关闭自有服务的路径有专项验证。
- 8 小时合成采集／API 长测在独立 8504 实例后台运行，封存 revision `640ec8ccb48cc90f01d4ec9da81e3e615a428599`，研发改动不进入该实例。报告 `artifacts/p1-soak-8h/report.json` 持续写入；运行中不算通过。该负载不含真实视觉、模型或摄像头，也没有覆盖 CI、磁盘不足、保留策略及备份恢复，见[长测范围](soak.md)。

## 用户模型维护闭环 — 2026-10-10

当前源码验证：后端 370 项测试通过，前端构建与格式检查、源码编译和 diff 检查通过；保留一条上游 Starlette TestClient 弃用警告。

本轮环境：Apple M4／24GiB、macOS 26.6 arm64、Python 3.12、Ollama 0.40.2、Chrome 155。测试使用隔离数据库与独立模型端口，未覆盖历史基准、默认证据或 PPT。

| 模块 | 门槛与证据 | 结果 |
| --- | --- | --- |
| 运行可靠性 | 启动 ≤180 秒、停止 ≤30 秒；取消后无迟到进程；日志有界；不停止外部服务；应用退出无遗留监听 | 自动测试通过；真服务启动 2.86 秒，重启与退出清理通过 |
| 部署准备 | 固定官方来源；续传／全量响应正确处理；取消保留片段；校验失败不发布；已有正式文件不覆盖；同文件排他准备 | HTTP 协议、ZIP／tar.zst 安全解包及取消夹具通过；页面真实已缓存官方文件通过校验，未重复下载 GB 文件 |
| 版本切换 | 真实生成与响应契约通过才发布选择；失败保留配置；回滚重新检查；复核版本冻结 | 本机两种官方规模真实自检、候选导入、切换与回滚通过；生成／保存／取消失败测试通过 |
| 运行维护 | 驻留／超时实际进入请求；自启动显式开启；连续三次失败、30 秒冷却、10 分钟最多三次恢复；不自动重发复核 | 页面资源方案释放驻留；实际终止隔离模型子进程后恢复新进程，复核条数不增加；次数门槛自动测试通过 |

4B 冻结事件真实复核 12.63 秒，预设门槛 ≤90 秒；启动期间状态接口 p95 10.31ms，门槛 ≤1 秒，采集帧数持续增加。自检只确认部署身份、实际生成和结构化契约，不证明模型回答正确。

复现实验：`python scripts/test_model_management_ui.py --output artifacts/model-maintenance-<新目录>`。本机报告、截图与真实事件位于 `artifacts/model-maintenance-20261010-v2/`，默认忽略，不随源码分发。桌面／390px 已查看截图；收口渲染另外覆盖六页、两种尺寸，无横向溢出或页面异常，见本机 `artifacts/ui-maintenance-final-20261010/`；常用前端流程另外使用 `scripts/test_ui.py`，报告在 `artifacts/ui-maintenance-regression-20261010/`，无页面异常。后者为合成流程与显式响应夹具，不算真实模型测试。

Windows／Linux 本轮仅验证平台选择、下载协议和安全解包，未做实机部署。首次网络全量下载、长期负载、另一台机器、真断网、功耗与现场准确率仍未通过本轮验收；这些不由工作台功能完成状态代替。真实工位数据无渠道，保留为外部限制。

## 历史：本地模型管理页（维护扩展前）— 2026-10-10

环境：Apple M4 / 24GiB、macOS 26.6 arm64、Python 3.12、官方 Ollama 0.40.2、Chrome 155。验收使用独立临时数据库与随机 loopback 端口，不改默认运行数据库、历史基准、PPT 或模型权重。

- 独立模型页完成官方 1.7B / 4B 选择持久化、真实文件预检、后台启停、周期健康／驻留查询、整机资源和有界日志。CLI 与页面复用进程所有权实现；不依据历史 receipt PID 停止服务。
- 平台适配由后端统一报告系统、架构、发现策略与准备命令；Apple Silicon 默认核验项目固定包，Windows 查 PATH 与用户安装目录，Linux／Intel Mac 查 PATH，允许保存完整运行时路径。增加旧版本／未知版本拒绝、Windows 目录发现、四种平台／架构策略、显式路径、未知平台与配置持久化测试。平台夹具不当作 Windows／Linux 本轮实机验收。
- 自动测试覆盖配置重启／损坏／保存失败、数据库隔离、外部进程保护、非法地址、启动失败重试、复核在途互斥、后台检查不阻塞采集、慢探测失效、健康过期与断连、未查询驻留保持未知、日志有界和关闭竞争。
- 真实浏览器门槛预先设为启动 ≤180 秒、停止 ≤30 秒、一次真实结构化复核 ≤60 秒、启动期间状态接口 p95 ≤1 秒且采集增加。最终平台适配版本实测启动 2.87 秒、状态 p95 16.69ms、4B 复核 13.04 秒；通过全部工程门槛。
- 浏览器实际完成：准备文件校验 → 页面启动 → 冻结事件真实复核 → 驻留显示 → 页面停止 → 应用重启恢复选择 → 外部终端服务连接且拒绝停止 → 服务退出自动清除连接 → 再启动并关闭应用清理子进程。桌面与 390px 截图已检查，无文档横向溢出；手机截图等待导航动画结束，避免把过渡画面当成页面布局。
- 现有合成浏览器回归通过采集、切页后台采样、告警冻结、人工记录、导出、基线保护、模型地址拒绝、移动导航和 API 断连恢复。其测试响应夹具与本节真实 4B 调用分别记录。

真实管理验收脚本：`python scripts/test_model_management_ui.py --output artifacts/model-management-<新目录>`。最终平台适配报告、截图、真实复核证据在 `artifacts/model-management-platform-20261010/`（先前检查保留在 `artifacts/model-management-20261010-final/`）；合成回归在 `artifacts/ui-model-management-regression/`。这些本机忽略目录不随源码提交。后端 327 项测试、前端构建与格式检查均通过；保留上游 Starlette TestClient 弃用警告。

该阶段只通过单机短时工程验收；当时首次准备仍用终端，页面没有下载、安装或卸载，日志尚未轮转。下载准备与日志轮转现已由本页顶部维护模块补齐；长期稳定、真断网、第二设备和功耗仍未验证。真实工位数据无渠道，现场验收暂列外部限制，见[开发优先级](../ROADMAP.md)。

## 规则辅助复核优化与 PCB3 单次复测 — 2026-10-09

环境：Apple M4／24GiB、macOS 26.6 arm64、Python 3.12、Ollama 0.40.2、Chrome 155。当前生产提示词改为测量在前、顺序条件判读，并附从测量计算的阈值布尔核对；不提供独立标签或规则分类，不改写模型原始回答。历史提示词按封存配方验证；本节对应新配方，下节保留首轮工程与效果记录。

- 已观察 PCB1 开发诊断复现旧配方将变暗判正常；精简配方 4B 两路五条件各 4/5，仍错读 0.99 与 0.25 的比较。数值核对后各 5/5、1.7B 3/5，均是开发证据。一次旧配方思考模式 80.69 秒、2048 token 内没有最终回答，保留失败，没有替换默认限时模式。
- 从固定官方 VisA 归档新下载 PCB3，保留 revision、ETag、CSV 摘要及单图摘要。选 4 张 test-normal 根作五条件对照；与所声明已观察实验的规范化 PNG 摘要无重叠。软件标签、脚本 OK／缺失检测与重复参考帧如实声明；下载的 1 张异常图像不参与本次效果评估。
- 输入、提示词配方、源码及既定门槛先于 60 次真实模型调用封存；题库运行前排他消费、已完成，不自动重试。最终规则／4B 无上下文／4B 有上下文／1.7B 类别一致为 20/20、20/20、20/20、17/20，结构化覆盖和内部一致均 100%，全部调用 ≤30 秒。各路模型有 4 条检测缺失提示；人工危害率与质量评分仍为 `null`。
- 模型调用 p50／p95 分别为 14.44／20.12、15.28／18.77、8.76／9.67 秒。1.7B 三处错误为正常原图选 `unknown`，4B 同题改善 3／退化 0；通用上下文未见类别改善。固定候选顺序与机器负载影响耗时，不作随机性能结论。
- 两路 4B 类别检查通过，但只有 4 个独立根、一个公开分区，没有产品类、三批现场标签或真人评分；所有方法保留“证据不足”，`accepted=false`。新结果不能当作相同样本上从首轮 25% 到 100% 的提升，规则辅助不能冒充模型独立推理能力。
- 当前后端 297 项测试通过，保留一条 Starlette 上游弃用警告；React 生产构建、格式与 diff 检查通过。新增测试覆盖严格数值边界、不可用 NG、旧配方／未知配方、固定来源像素校验与已观察根排除、源码变更不消费、消费前置、成功／中断后禁止重跑。
- Chrome 验证历史、当前开发配方及 PCB3 真实结果的导入／报告与卡片下载、匿名三维待评、评分保存失败重试、部分保存、旧版本保留与刷新恢复。修复导入新报告期间旧报告仍可下载的竞态，报告区域仅在非繁忙且摘要匹配当前选择时显示。最终桌面与 390px 截图已查看，无页面错误或文档横向溢出；人工评分仍是另存的明确 UI 夹具。
- 当前提示词与真实 CPU PaDiM 并行的工程回归通过：三次复核 15.13／10.55／10.53 秒，采集增长 21／15／14 帧，状态接口 p95 15.67ms；HTTP 503 显式注入不产生成功记录，恢复后可重试，人工记录／导出／重启历史一致。没有真实相机、现场语义或用户收益验收。
- 实际再次调用已消费 PCB3 题库，在推理及输出目录创建前拒绝；当前源码摘要与封存值一致，全部 60 份留出提示词逐字核对。验收与模型服务 Ctrl+C 关闭后，8503／11435 端口关闭、receipt 为 `stopped`，无本轮模型、视觉或数据准备进程残留。

证据：`artifacts/review-optimization/pcb3-held-out/` 为消费完成的题库及原始结果；无评分报告摘要 `ab3bf38bb4c0347cd16254cbdf06479cf01915116f287c48b99bb237d2af913f`。工程并行回归在 `artifacts/local-review-optimized/`，最终浏览器证据在 `artifacts/ui-review-optimization-held-out/`；历史与当前开发配方浏览器证据另存于 `ui-review-optimization-historical/`、`ui-review-optimization-current-fixed/`。默认数据库、历史基准与 PPT 未改写，这些忽略目录不随源码提交。复现及局限见[复核评估](review-evaluation.md)。

## 复核效果评估与人工评分 — 2026-10-09

验证环境沿用 Apple M4／24GiB、macOS 26.6 arm64、Python 3.12、Ollama 0.40.2 与 Chrome 155。官方 1.7B Q4_K_M 下载与固定 manifest 的大小、SHA-256 一致；4B 使用上一模块已核验权重。本模块完成封存题库、四路同题对照、匿名人工评分、不可变版本与浏览器导入／导出，效果验收未通过。

- 固定 4 张此前已观察的 VisA PCB1 正常根图像，各 5 个条件，共 20 例／候选；重复帧仅作测量窗口。检测为明确的脚本 OK／缺失夹具，软件模糊、变暗、平移不构成现场物理原因真值，也未在本实验运行 PaDiM。仅一个公开分区，无产品类支持。独立支持与现场批次门槛不满足。
- 规则 20/20、4B 无上下文 5/20、4B 有上下文 5/20、1.7B 有上下文 4/20 类别一致。60 次真实模型调用均返回合规结构，内部一致率均为 100%，模型类别检查均低于固定 90% 门槛；大量异常被选为 `none`。4B 两路各 15 例、1.7B 16 例有测量冲突提示。结构正确和字段自洽不证明语义正确。
- 上述三路模型调用 p50／p95 分别为 8.33／10.73、13.75／15.45、7.20／9.96 秒，含元数据、适用的加载与缓存耗时。固定候选顺序、不同机器负载，不作为随机化性能比较。
- 4B 加入通用操作员上下文没有类别改善或退化；1.7B 到 4B 改善 1 例。没有真实维修上下文、独立架构备选模型或用户排查时间收益证据。规则标签贴近规则线索，100% 不能外推现场准确率。
- 真人证据忠实度、步骤可执行性与危害建议率全部待评，保留 `null`；不把未评分记为零危害。UI 保存测试评分明确标注夹具，另存报告版本，不写入真实原始实验。
- 生产提示词抽为单一白名单构造器；全部 60 份实测提示词与最终构造器、上一模块生产字符串逐字节一致。推理期间完善过评分器与界面，旧封存的源码摘要保留当时状态；不声称整套最终评分代码在首轮调用前已冻结。
- 后端 287 项测试通过，保留一条 Starlette 上游弃用警告；React 生产构建、格式和 diff 检查通过。覆盖失败／未执行分母、未知标签、封存与原始响应绑定、官方权重与采样参数、畸形规则字段、严格布尔评分、部分保存与原子失败、版本重启恢复。
- Chrome 验证真实实验导入、报告／匿名卡导出、失败案例、待评保留、评分保存失败后重试、旧版本不变与刷新恢复；旧回放评估流程回归通过，无页面错误。1440px、390px 报告及手机评分截图已查看；窄屏表格保持最小列宽并独立横向滚动，文档无横向溢出。

准备、真实对照与评分命令见[复核评估](review-evaluation.md)。浏览器验收使用独立临时数据库：

```sh
python scripts/serve_acceptance.py --port 8503
# 另一个终端：原始 study.json 必须来自已完成的对照运行
python scripts/test_review_study_ui.py --url http://127.0.0.1:8503 \
  --study artifacts/review-effectiveness/run-v1/study.json \
  --output artifacts/ui-review-study-new
```

本地原始题库与 60 次调用在 `artifacts/review-effectiveness/`；最终无人工评分报告为 `report-verified.json`，study 摘要为 `978a298f4149c6506a865b23f0ab8a7a6122c7f6982cdc8f54891053a8baa083`。浏览器证据为 `artifacts/ui-review-study-responsive/`，旧回放回归为 `artifacts/ui-review-evaluation-regression/`。这些忽略目录不随源码提交；未改写默认数据库、历史基准或 PPT。后续在已观察题库上优化只能算开发，须另留未观察现场批次验收。

## M4 本地 4B 部署与真实复核贯通 — 2026-10-09

验证环境：Apple M4、24GiB 统一内存、macOS 26.6 arm64、Python 3.12、Ollama 0.40.2、Chrome 155.0.8059.39。官方 4B Q4_K_M 下载字节与固定 manifest 的大小／SHA-256 一致，归档与安装文件通过校验。`/api/show` 核验 `spark2_5`、4.1B、Q4_K_M 与官方 blob，`/api/ps` 核验 4096 上下文和 2,787,995,810 bytes 驻留。

使用 VisA PCB1 已观察公开图像生成重复 MJPG 视频，实际执行独立 CPU ResNet18／PaDiM 和本机 Spark。无真实摄像头、现场原因真值或新增盲测集；同一冻结事件重复调用只验工程。默认运行数据库、已消费 PCB2 最终集和历史基准均未改写。

- `.venv/bin/python -m pytest tests -q`：259 项通过，保留一条 Starlette 上游弃用警告；React 生产构建、格式与 diff 检查通过。新增测试覆盖坏权重／静态标记无效、归档链接越界、占用端口拒绝、失败不复用旧回答、复核存储失败恢复、元数据失效与模型内部矛盾。打包包含运行时来源清单，不含二进制／权重／数据库；未重建历史 PPT。
- 首次结构化复核 10.30 秒，加载 2.80 秒，输出 31.93 token/s；属于单次首次加载记录，不能作为冷启动分布。
- `scripts/validate_local_review.py` 调用前冻结门槛：≥3 次结构化成功，每次 ≤30 秒且视觉采集增长 ≥1 帧；状态接口 p95 ≤1 秒；权重／4096 上下文一致；失败不得生成成功记录，恢复后可重试；人工结论／冻结事件／导出一致且服务重启可读。
- 实测三次 8.65／7.73／7.74 秒，帧增长 12／11／10，状态接口 p95 11.68ms；观察到的视觉提交至结果耗时约 26–37ms（轮询重复采样，不作为独立帧延迟分布）。上述工程门槛通过。
- 前台服务退出实测：Ctrl+C 后应用 8503／模型 11435 端口关闭，模型 receipt 标记 `stopped`；权重与运行包保留，重新启动无需下载。
- HTTP 故障为显式测试注入：loopback 中继转发真实服务元数据，推理请求返回 503；保存 `model_error`、冻结快照与提示词，无假答案；回到真实端点后成功复核。没有切断物理网络或终止真实模型服务来模拟故障。
- 整机可用内存最低约 4.0GiB，swap 当时约 22.6–23.1GiB；既有其他应用负载未关闭，不把变化归因于模型。只报告短时容量与并行表现，不证明长期稳定、峰值独占资源或功耗。
- Chrome 真实复核通过合成事件桌面／手机流程；`scripts/test_visual_live_ui.py --model-review` 通过公开 PCB 图像的真实 PaDiM → Spark → 人工记录 → 事件 JSON 下载，保留姿态拒绝及下一帧恢复。公开图像桌面、390px 复核截图与手机模型配置区域已实际查看；控制台无错误，无横向文档溢出。
- 实测模型曾在配准响应 0.2 时选机械变化，另一次 `drift_detected=true` 但分类为 `none`；保留原始输出，新增内部矛盾提示和漏报核查，不改写为正确原因。没有原因准确率或用户收益验收。

复现需已准备 `artifacts/pose-study-pcb1/manifest.json` 及 `data/models/padim-pcb1-aligned-runtime`，按[视觉接入](vision-validation.md)生成；保持独立模型服务运行：

```sh
python scripts/start_model.py --size 4b
# 另一个终端：必须使用新输出目录
python scripts/validate_local_review.py --output artifacts/local-review-new
# 浏览器使用独立临时 DB，完成后关闭服务
python scripts/serve_acceptance.py --port 8503
# 再另一个终端
python scripts/test_visual_live_ui.py --url http://127.0.0.1:8503 \
  --model data/models/padim-pcb1-aligned-runtime --model-review \
  --output artifacts/ui-public-review-new
```

本轮完整资源与门槛报告位于忽略目录 `artifacts/local-review-4b-verified/`；真实公开图像浏览器证据在 `artifacts/ui-local-public-review/`，最终合成场景真实 4B 回归在 `artifacts/ui-local-spark4b-verified/`。首次加载证据为 `artifacts/local-spark4b-smoke.json`。测试夹具、公开图像和现场证据分别保留，不把本轮短时工程通过当成生产验收。

## Isolated live visual inference — 2026-10-09

macOS arm64、Python 3.12、torch 2.8.0、torchvision 0.23.0、Chrome 155.0.8059.39。最终后端 233 项通过，保留一条 Starlette 上游弃用警告；实时专项 7 项覆盖独立进程、协议拒绝、进程退出、超时终止、显式重载边界、单帧在途、查询响应、暂停、模型快照隔离、逐帧恢复、基线失败保留旧版本与关闭清理。后续观测与模型方法摘要分别留存；模型统计归档展开大小限制及重复拟合／标定身份拒绝已纳入最终实现。

React 生产构建和格式检查通过。`scripts/test_visual_live_ui.py` 使用实际隔离的 ResNet18／PaDiM 模型进程和公开 PCB 图像生成 MJPG 视频；基线使用 10 张重复正常帧，仅验工程机制。单帧结果为 `ok/ok/ok/error/ok`，合成空白帧实际拒绝对齐，没有判定或分数，下一帧正常处理。重新连接视频后连续后台处理的状态一致，切到基线页面不暂停推理，视频结束自动暂停并留存错误。模型切回代理清除基线，置信度保持空；桌面与 390px 页面无横向溢出，无控制台错误，失败截图与手机设置截图已实际查看。

最终浏览器证据保存在忽略的 `artifacts/ui-visual-live-final/`，当前方法模型配方在 `data/models/padim-pcb1-aligned-runtime/`，验收实例使用 `scripts/serve_acceptance.py` 的独立临时数据库。120 张两版离线回放与原工作台浏览器回归通过，无控制台错误；证据位于 `artifacts/ui-vision-{offline,workstation}-regression/`。默认工作台在禁止导入 torch／torchvision 时仍可采样。没有打开真实摄像头、执行 Spark 推理或验证产线准确率／吞吐／功耗／断网；生成视频不作为新增独立现场标签。使用步骤、计时范围与错误语义见[视觉验证](vision-validation.md)。

## Fixed imaging conditions and model recipes — 2026-10-09

后端 226 项通过，保留 Starlette 上游弃用警告；成像条件／AeBAD 入口／模型导出专项 4 项通过。用真实 PCB1 新增 120 张原图，各执行原始、亮度 ×0.7／×1.3、5×5 模糊和平移 12px，原图／对齐两版分别固定正常标定阈值，实际 CPU 推理重跑一致。对齐变亮有 21/120 不可用（正常 4、缺陷 17），按全部缺陷计找到 28/60，报告保留成功子集与全部标签分母。姿态各组的两类原图拼图已查看。模型导出、摘要损坏拒绝、标签翻转不改变预测、域训练末批隔离、重复像素拒绝与失败清理均验证。

AeBAD 官方 Google Drive 在沙箱内外超时，天翼只有分享元信息，未取得图像；用户没有本地数据。本地准备与域评估仅以生成夹具验证，不能称 AeBAD 实测。MVTec AD 2 未下载。当前软件变换不等于物理成像变化，回放提示不等于真实每小时告警率，也未执行相机或 Spark 推理。实际报告位于忽略的 `artifacts/conditions-pcb1-{raw,aligned}-verified/`；模型配方位于 `data/models/padim-pcb1-{raw,aligned}/`，不分发权重。步骤与完整分母见[视觉验证](vision-validation.md)。

## Expanded pose study — 2026-10-09

macOS arm64、Python 3.12、ResNet18／PaDiM CPU。后端 222 项通过，保留 Starlette 上游弃用警告；姿态与统计加载专项 3 项，联合视觉专项 9 项通过。新增 120 张原图按身份和归一化像素排除此前观察与训练样本，两个姿态组均包含正常和缺陷。固定参数下原图模型召回 95%、误报 58.3%；对齐模型召回 50%、误报 3.3%。固定 180° 配对变换引起 33／3 个判定翻转，不作为额外独立样本。没有测试阈值调整、相机采集或现场验收。报告及复现步骤见[视觉验证](vision-validation.md)。

## PaDiM anomaly results and pose alignment — 2026-10-09

验证环境为 macOS arm64、Python 3.12、torch 2.8.0、torchvision 0.23.0 和 Chrome 155.0.8059.39。在本机执行 ResNet18／PaDiM CPU 推理，输入为 VisA PCB1 真实公开图像；没有打开真实摄像头、执行 Spark 语言模型推理或连接产线。

- `.venv/bin/python -m pytest tests -q`：219 项通过，其中本模块专项 19 项；保留一条 Starlette `TestClient` 上游弃用警告。覆盖 v1 内容寻址 ID 不变、v2 分数／阈值约束、非有限值与混合语义拒绝、不可用分母、空置信度统计、模型输入隔离、完整协方差数值、受控 180° 对齐、无特征拒绝、训练末批隔离、标签翻转不改变预测、逐图推理失败、存储回滚及坏权重拒绝。
- React 生产构建、格式检查与 `git diff --check` 通过。默认工作台在禁止导入 torch／torchvision 的条件下仍可采样，视觉依赖保持可选；打包测试确认视觉文档和可选依赖清单纳入源码包，运行数据与权重仍排除。
- `scripts/test_anomaly_ui.py` 完成两版真实结果导入、各 80 张完整回放、离线／工作台混淆矩阵一致、空置信度、版本对比、姿态证据及 1440px／390px 布局。另以独立合成夹具注入对齐拒绝，验证失败仍为不可用，不混入真实指标。最终显示调整后重跑通过，桌面／手机与手机拒绝截图已实际查看，页面无横向溢出。
- `scripts/test_inspection_ui.py`、`scripts/test_evaluation_ui.py`、`scripts/test_reliability_ui.py` 浏览器回归通过；四组脚本控制台均无错误。验收服务使用独立临时数据库，没有覆盖默认运行库。
- 固定 40 张正常拟合、20 张正常标定、40 张正常测试与 40 张异常测试，未按测试结果调整阈值。原图 PaDiM：AUROC 1.0000，TP/TN/FP/FN=40/31/9/0，召回 100%，正常误报 22.5%；对齐 PaDiM：AUROC 0.9625，TP/TN/FP/FN=21/38/2/19，召回 52.5%，正常误报 5%。当前代码重跑指标一致，140 张对齐均通过质量门。

本子集正常测试图全部接近参考方向，异常测试图全部旋转约 180°；姿态分组各缺少另一类，组内 AUROC 无法计算。原图高 AUROC 不能证明缺陷语义能力，对齐降低误报但增加 19 张漏检，不能推荐为生产默认。已查看漏检、命中和误报热图，未获取像素真值或计算定位准确率。尚缺同姿态的正常／异常样本、现场标签、真实相机吞吐、功耗与断网验证；MVTec AD 2 和 AeBAD 仍未实测。

最终实验保存在本地 `artifacts/padim-visa-pcb1-verified/`，浏览器证据位于 `artifacts/ui-anomaly/` 和 `artifacts/ui-anomaly-{inspection,evaluation,reliability}/`，均未纳入 Git。方法、参数、权重摘要与复现步骤见[视觉检测](visual-detector.md)。

## Cross-batch composition and public images — 2026-10-09

验证环境为 macOS arm64、Python 3.12 和 Chrome 155.0.8059.39。工程验收使用合成采集与生成视频，另以 VisA PCB1 真实公开图像验证导入和回放；没有打开真实摄像头、执行 Spark 推理或连接产线。

- `.venv/bin/python -m pytest tests -q`：200 项通过，保留一条 Starlette `TestClient` 上游弃用警告。跨批次专项 13 项；公开数据与下载专项 7 项。覆盖根来源追溯、跨版本重复原样本拒绝、同名批次区分、过期标签／配置拒绝、坏像素、写入回滚、幂等发布、服务重启、标签隔离、固定 HTTP 范围与版本、缓存损坏重取、失败清理与重试、测试标签不影响预测。
- React 生产构建、格式检查与 `git diff --check` 通过；打包测试确认编排与公开数据文档纳入源码 ZIP，运行数据和本地报告仍排除。
- `scripts/test_composition_ui.py` 通过跨来源选择、图像预览、重复提示、编辑失效、另一标签页修改后的 409 拒绝、重新检查发布、根身份保留、固定回放和 1440px／390px 布局。采集、样本管理与回放评估浏览器回归通过；控制台无错误。
- `scripts/test_public_data_ui.py` 通过真实公开图像显示、80/80 完整回放、演示代理指标隔离与桌面／手机布局。编排桌面、真实图像桌面及手机评估截图已实际查看；验收实例使用独立临时数据库，不覆盖默认运行库。
- VisA PCB1 下载 60 张正常训练图、40 张正常测试图和 40 张异常测试图。独立手工 Lab patch 对角高斯基线用 40 张拟合、20 张标定，image AUROC 0.993125、TP/TN/FP/FN=40/31/9/0。最终脚本重跑指标与数据集 ID 一致，未调整阈值。正常误报 22.5%，实际图像存在朝向差异；不代表完整算法基准、缺陷语义识别或现场可靠性。
- 工作台参考代理处理 80/80，无检测缺失／失败／超时；40 张正常测试图有 20 张机械规则提示。没有原因真值，不计算原因准确率，也不将代理判定作为缺陷准确率。MVTec AD 2 仅研究官方要求，未下载；AeBAD 的 Google Drive 请求超时，天翼分享页可访问但数据未获得，两者均未实测。

本地工程报告位于 `artifacts/ui-composition/`、`artifacts/ui-composition-{acquisition,dataset,evaluation}/`；公开图像 UI 位于 `artifacts/ui-public-data/`，算法重跑位于 `artifacts/public-data-visa-pcb1-final/`，初始实验与独立工作台回放位于 `artifacts/public-data-visa-pcb1/`。均未纳入 Git。来源、数据许可、固定版本和复现步骤见[公开数据实验](public-data.md)，工程操作见[跨批次编排](composition.md)。

来源摘要与批次检查不证明统计独立；公开 train/test 不等于现场采集批次。本轮仍未验证真机成像参数、环境读数、独立工位标签、告警误报率、模型收益或断电耐久性。

## Acquisition preflight and captured datasets — 2026-10-09

验证环境为 macOS arm64、Python 3.12 和 Chrome 155.0.8059.39。输入为合成 PCB 和生成的 MJPG 视频；相机属性通过测试替身验证，没有打开真实摄像头，也没有执行模型推理。

- `.venv/bin/python -m pytest tests -q`：180 项通过，其中采集专项 30 项。保留一条 Starlette `TestClient` 上游弃用警告。覆盖无基线预检、监测状态隔离、确切预览像素与摘要、来源强制标记、过期与跨会话失效、系统时钟回拨、坏帧参考拒绝、500 帧与条件字段限制、损坏记录、写入故障回滚、独立标注、不可变发布、服务重启与模型标签隔离。
- React 生产构建、格式检查与 `git diff --check` 通过。打包测试确认新文档随源码打包，采集图像与运行草稿不进入源码包。
- `scripts/test_acquisition_ui.py` 验证预览无需基线、保存显示的当前像素、未标注初始状态、重复留存禁用、独立标注、发布后数据集列表刷新、旧版本不变、草稿刷新恢复及发布数据集回放。暗场可留作评估而不能参考；视频结束清除旧预览；注入 API 留存失败后无成功提示。
- 样本回放、基线与告警、原工作台三个浏览器脚本回归通过，控制台无错误。原工作台初次在重置按钮滚动定位时超时，完整重跑通过。专项桌面与 390px 手机截图已实际查看；手机截图等待侧栏收起动画结束后拍摄，页面无横向溢出。
- 本轮使用独立临时数据库和本地单 worker 服务，未覆盖运行数据库或历史证据。报告与截图位于 `artifacts/ui-acquisition/`，回归报告位于 `artifacts/ui-acquisition-{dataset,reliability,regression}/`，均未纳入 Git。复现步骤见[采集说明](acquisition.md)。

留存图像为 640 × 480 归一化像素；没有验证原分辨率留存、真实设备参数可用性、断电文件耐久性、现场标签或基线稳定性。摄像头来源标为真实采集不证明真实缺陷，合成验收也不代表产线效果。

## Baseline and alert reliability — 2026-10-09

验证环境为 macOS arm64、Python 3.12 和 Chrome 155.0.8059.39。输入为合成 PCB、生成的 MJPG 视频与脚本检测结果；没有执行真实摄像头采集或模型推理。

- `.venv/bin/python -m pytest tests -q`：150 项通过，保留一条 Starlette `TestClient` 上游弃用警告。覆盖单帧过暗／过曝／无纹理、尺寸不一致、采集／编码／检测失败、基线原子发布、SQLite 写入故障、告警类型抖动、恢复中断、不可用窗口、人工标记隔离和重启后的历史恢复证据。
- `npm run build --prefix frontend` 和 `npm run format:check --prefix frontend` 通过。
- `scripts/test_reliability_ui.py` 验证基线拒绝后保留旧版本、告警去重、连续恢复、检测不可用、事件新增／恢复证据导出和 1440px／390px 布局。使用独立临时数据库与本地单 worker 服务，未覆盖运行数据库。
- 原工作台、检测结果接入、回放评估、样本管理四组浏览器脚本回归通过，控制台无错误。新增证据与终止／恢复记录按事件顺序展示；桌面复核与手机基线截图已实际查看，并修复拒绝详情横向挤压和旧成功提示残留。
- 当前截图与 JSON 位于本地 `artifacts/ui-reliability/`，回归证据位于 `artifacts/ui-reliability-{regression,inspection,evaluation,dataset}/`，均未纳入 Git。机制及复现命令见[基线与告警可靠性](reliability.md)。

SQLite 失败通过测试触发器注入，未验证真实断电、磁盘耐久性、产线误报或不同采样率下的恢复时间。逐帧质量门也不证明基线稳定或产品正常。

## External inspection results — 2026-10-08

验证环境为 macOS arm64、Python 3.12 和本机 Chrome。输入为合成 PCB 图像与人工构造的检测结果文件，没有执行真实缺陷模型、摄像头采集或产线准确率评估。

- 后端完整测试 103 项通过，其中外部结果专项 17 项；覆盖样本／图像错配、非法分数、版本幂等、基线完整性、缺失／失败／超时、窗口恢复、禁止代理回退、模型输入隔离及服务重启后的完整结果包导出。
- 基线统计使用全部参考样本，非法更新保持旧统计与窗口；同一输入与配置的重复回放摘要一致。
- React 生产构建和格式检查通过。专项浏览器验证文件导入、样本预测预览、异常留存、高置信度 NG、事件／回放下载、显式切回代理及旧证据保留。
- 已有样本回放与工作台浏览器流程执行回归。桌面和 390 px 页面没有横向溢出，专项桌面异常状态和手机监测截图已实际查看。
- 新报告与截图保存在本地 `artifacts/ui-inspection/`，不覆盖历史证据，也未纳入 Git。复现命令见[接入说明](inspection-results.md)。

一次 Starlette TestClient 上游弃用警告仍保留。结果包是导入者声明的上游输出；文件接入完成不代表真实产线协议、模型准确率或现场可靠性已经验证。

## Dataset replay — 2026-10-08

新增样本清单导入与固定回放。验证使用 macOS arm64、Python 3.12 和 Chrome，数据为明确标注的合成图像与生成视频；不涉及真实摄像头、模型推理或产线准确率评估。

- 后端覆盖非法清单、路径越界、重复样本、坏图像、视频指定帧、摘要损坏、基线失败、标签隔离、会话切换和重启后导出。
- 同一数据集按相同顺序独立回放两次，逐样本测量及汇总摘要一致；执行时间与耗时不纳入比较。
- 浏览器覆盖导入、分组／批次筛选、分页、图像预览、单帧／连续回放、暂停、完成与部分结果下载；检查桌面和 390 px 布局。
- 原工作台浏览器回归继续覆盖监测、事件核验、基线、离线恢复与模型输出展示夹具。
- 新报告和截图位于本地 `artifacts/ui-replay/`，未纳入 Git。复现方法与范围见[样本管理](datasets.md)。

## Replay evaluation — 2026-10-09

回放评估使用已保存的合成图像、脚本标签和人为构造的上游检测结果，验证离线报告与版本对比流程；不涉及真实摄像头、模型推理、独立缺陷真值或产线准确率。

- 后端专项覆盖显式分母、缺失／失败／超时／未运行保留、原因证据不足、参考代理隔离、重复图像与共同批次提示、结果对齐和同条件版本比较。
- `python -m pytest tests -q`：122 项通过；`tests/test_evaluation.py`：19 项通过。保留一条 Starlette `TestClient` 弃用警告。
- `npm run build --prefix frontend` 与 `npm run format:check --prefix frontend` 通过。
- `scripts/test_evaluation_ui.py --url http://127.0.0.1:8502 --channel chrome` 通过；覆盖评估入口、覆盖率／混淆矩阵、样本筛选与图像预览、报告和对比下载、部分／不兼容回放、读取失败恢复，以及 1440px 和 390px 布局。浏览器控制台无错误。
- 截图、报告和 JSON 保存在本地 `artifacts/ui-evaluation/`，未纳入 Git。验证使用新启动的单 worker 本地 API，端口由脚本按需选择。

## React migration — 2026-10-08

Current application: React + TypeScript + Recharts frontend, FastAPI local backend, Python 3.12.13 on macOS arm64. The browser suite uses installed Chrome 154 at 1440px desktop and 390px mobile widths.

- `python -m pytest tests -q`: 72 backend/API/packaging tests passed. One upstream Starlette TestClient deprecation warning remains.
- Vite development proxy and production endpoint both accepted same-origin writes and rejected a foreign Origin; Vite explicitly preserves the original Host.
- `npm run build --prefix frontend`: TypeScript and production build passed. Charts are a separate bundle; no CDN assets are required.
- `scripts/test_ui.py`: synthetic capture and continuous background sampling, pause, image dialog keyboard behavior, metric switching, automatic incidents, human review, search/filter, JSON export, baseline reset/rebuild, model endpoint rejection, four mobile pages and offline recovery.
- Current report and screenshots: `artifacts/ui-react/`. Desktop review and mobile baseline screenshots were visually inspected during development. The automated report does not claim human visual approval.
- Dependencies resolved from the new requirements into a separate environment without Streamlit. Frontend and Python dependencies have separate lock files.
- Source ZIP reproduced in `/private/tmp/spark-react-package`: CRC/source checks, offline installation of 39 Python and 110 npm packages, React build, and all 72 tests passed. Generated PPT/ZIP stayed in this isolated directory; historical project evidence was preserved. Current reproduction report is copied to `artifacts/ui-react/package-verification.json`. This is a same-device cache-based reproduction, not an offline-model or second-device test.

This validates a synthetic workstation and its UI/API workflow. No genuine model inference or camera acquisition was performed on the current Mac. Historical model benchmarks below remain historical evidence, not React acceptance results.

## Historical implementation evidence — 2026-10-04 / 2026-10-05

The following records describe the previous Windows environment and UI. Some referenced reports were absent from the imported folder; consult `docs/repository.md` before citing them.

## Completed Engineering Checks

| Requirement | Evidence | Scope |
| --- | --- | --- |
| Official model deployment | `models/manifest*.json`, archived official file lists, genuine `spark2_5` inference and `/api/ps` records | Official 1.7B / 4B Q4_K_M; loopback Ollama; GPU-resident models; 4096-token inference context |
| Local interactive workflow | `artifacts/ui-test.json` | 11 browser workflows, including real 4B review, human assessment, latest-data download, model evidence, pause/reset and local-only endpoint recovery |
| Desktop/mobile rendering | `artifacts/screenshots/`, screenshot pixel checks | 1440x1080 / 390x844, nonblank output, no horizontal document overflow; not a human visual review |
| Algorithm and evidence behavior | `artifacts/test-results.xml` | 65 tests; zero failures/errors/skips; zero baselines, signal gates, simulator identity, inference failure evidence, session history and provenance |
| Submission structure | `artifacts/submission/build-report.json` | Editable 12-slide PPT; no detected out-of-slide geometry, estimated text overflow or text/table overlap |
| Fresh source reproduction | `artifacts/package-verification.json` | ZIP extracted to an isolated workspace; 55 dependencies installed offline from local cache into a fresh environment; all 65 tests passed |
| Packaging safety | Package verifier | ZIP CRC, source freshness, locked dependencies; weights, runtime caches, databases and logs excluded |

The package reproduction is a fresh environment on this computer, not a second-device deployment or a disconnected-network model test.

## Measured Model Behavior

The latest `benchmark-4b.json` contains one fast-mode call per synthetic scenario:

| Scenario | Rule Observation | Model Category | Wall Time |
| --- | --- | --- | --- |
| Normal | none | none | 5.20 s |
| Focus blur | optical | none | 2.50 s |
| Dimmed light | illumination | optical | 3.32 s |
| Position shift | mechanical | mechanical | 3.11 s |

Each scenario's measured vision-analysis p50 is about 13.2-13.6 ms. Model wall time is separate, includes applicable loading/queue overhead, and is not a statistically estimated latency distribution.

The focus and light cases demonstrate a miss and a category error. The application flags known measurement contradictions; it preserves the original model answer. An absence of warnings does not establish correctness. These debugging examples were used during prompt iteration and are not held-out accuracy or model-irreplaceability evidence.

Fixed-prompt 4B thinking-mode replays exhausted 2048 and 3072 token budgets without a valid final answer (approximately 24-42 seconds per failed call). Both failed runs are retained. The tested thinking setting is not made the default.

## Camera Evidence

Camera index 0 is accessible with approved device permissions and supplies 640x480 frames. Its latest observed scene is nearly uniform and dark (brightness around 7, contrast below 0.1). `artifacts/device-camera.json` records that the calibration gate rejected this signal. No camera pictures or videos were persisted.

An earlier low-signal trial completed model calls before this gate was added; it is retained separately and is not a valid quality-inspection evaluation.

## Still Not Proven

- A usable real industrial scene, physically induced faults, independent defect labels and real upstream inspection results.
- Measurable user benefit or evidence that the official model is difficult to replace.
- Disconnected-network model operation, physical power consumption and another-device reproduction.
- Human visual review of the interface/PPT, including font substitution and screenshot readability.
- Team biographies, partners/resources, signed originality declaration and final submission deadline confirmation.

## Current Release Status

Engineering prototype and submission draft available. **Not a final competition-ready or factory-validated release.**

Before submission, follow `docs/submission.md` and `ROADMAP.md`. Do not present placeholders, synthetic cases, failed thinking calls or low-signal camera frames as completed field validation.
