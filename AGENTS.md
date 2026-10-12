# Spark Guard 项目契约

## 产品边界

- 工业视觉质检旁路复核台；仅提供观测、原因假设和人工核验，不自动停线、放行或剔除。
- Spark 接收文本指标；参考残差检测是演示代理。合成扰动、真实采集和真实缺陷标签必须区分。
- 模型错误、证据冲突和证据不足须保留；不得用默认正常结果替代推理失败。

## 当前开发重心

- 优先可视化与交互、后端及模型工程，执行顺序以 `ROADMAP.md` 为准。检测效果、复核质量、性能基准与指标报告留到工作流完善后集中评估，不在每个模块串行追加实验。
- 功能测试、构建、错误处理、模型身份与数据完整性检查仍随实现完成；必要真实调用只用于确认工程接口可用。保留历史实验及已观察身份，不放宽既有协议或宣称尚未完成的效果验收。

## 任务入口

- 产品与运行说明：`README.md`、`SUMMARY.md`。
- Git 跟踪范围、基线缺失项与验证边界：`docs/repository.md`。
- 前端与 API：`frontend/src/`、`src/api/`；启动入口 `run.py`。
- 工作台维护：`src/llm/tasks.py`、`src/storage.py`、`frontend/src/MaintenancePanel.tsx`、`docs/operations.md`；任务终态与重启中断保留，不自动重发；SQLite 在线快照，恢复只写新数据库，不覆盖原证据。
- 采集与处理：`src/inspection/`、`src/pipeline.py`、`src/monitoring/`。
- 采集预检与留存：`src/acquisition.py`、`frontend/src/AcquisitionPanel.tsx`、`docs/acquisition.md`；预览不计入监测，显式留存保存像素，发布不修改既有版本。
- 样本与回放：`src/datasets.py`、`src/api/service.py`、`docs/datasets.md`；独立标签与采集描述不得进入模型快照。
- 跨批次编排：`src/composition.py`、`src/dataset_checks.py`、`docs/composition.md`；保留根来源身份，发布重验检查摘要，名称和公开分区不证明现场批次隔离。
- 公开图像实验：`scripts/prepare_visa.py`、`scripts/benchmark_public_data.py`、`docs/public-data.md`；数据与报告不入源码包，独立异常分数不冒充检测置信度或真实工位验收。
- 视觉异常检测：`src/inspection/padim.py`、`src/inspection/alignment.py`、`scripts/run_padim.py`、`docs/visual-detector.md`；PyTorch 为可选依赖，拟合与阈值标定隔离，训练末批不能读入评估图像；原图监测与检测器对齐独立，分数按 v2 协议接入。
- 视觉验证与模型配方：`src/inspection/vision_model.py`、`scripts/run_pose_study.py`、`scripts/run_condition_study.py`、`docs/vision-validation.md`；排除已观察图像，软件变换保留根身份且不增加真实样本分母，拒绝摘要／方法版本不匹配的模型。
- 视觉研发验收：`src/acceptance.py`、`scripts/compare_visual_methods.py`、`scripts/validate_visual_release.py`、`docs/vision-acceptance.md`；固定门槛先于评估，验证选择与最终集单次消费隔离，未通过／样本不足不得宣称验收；真实域由 `scripts/run_domain_study.py` 评估，软件视图与公开域均不替代工位证据。
- 实时视觉：`src/inspection/runtime.py`、`frontend/src/VisionPanel.tsx`；独立进程、单帧在途、超时终止与显式重载，不回退代理；模型切换清除基线，暂停允许已提交帧完成留证；`scripts/serve_acceptance.py` 为独立临时数据库验收入口。
- 视觉资产：`src/inspection/catalog.py`；固定配方完整校验并复制、版本幂等、显式加载与保存配置恢复；登记不改变基线，重启不自动启用，最近配置不冒充运行状态。
- 外部质检：`src/inspection/results.py`、`docs/inspection-results.md`；按样本和图像摘要对齐，缺失／失败／超时不得回退代理或补成正常。
- 回放评估：`src/evaluation.py`、`docs/evaluation.md`；标签只用于离线核对，缺失与证据不足保留分母，代理／合成／真实采集须明确标识。
- 用户模型管理：`src/llm/management.py`、`src/llm/runtime.py`、`frontend/src/ModelPage.tsx`；`src/llm/deployment.py` 统一平台能力与运行时发现，`preparation.py` 管理官方文件续传和原子发布，`validation.py` 负责真实推理切换门；`policy.py` 定义有界策略，自动恢复禁止接管外部服务或重发复核；前端消费后端计划；CLI 与页面共用进程所有权，禁止从历史 PID 接管／停止外部服务；配置随数据库隔离，健康探测与部署任务不持锁阻塞采集。
- 本地 Spark 部署：`scripts/install_model_runtime.py`、`scripts/start_model.py`；真实并行复核验收 `scripts/validate_local_review.py`，需独立模型服务与公开图像／视觉配方，不打开摄像头。
- 模型与证据：`src/llm/`、`src/storage.py`、`models/manifest*.json`。
- 历史与空间维护：`src/workspace.py`、`frontend/src/MaintenancePanel.tsx`、`docs/operations.md`；分页／关联查询不截断，归档先逐项核验再释放，当前会话受保护；受管 ZIP 与 SQLite 快照范围不同，恢复只写新目录，关闭模型自动动作，不含外部运行时和语言模型缓存。
- 视觉资产维护与研发部署：`src/inspection/catalog.py`、`deployment_assets.py`、`release_deployment.py`；原部署 v1 与封存适配 v2 独立，保留阈值、ROI、统计与封存身份，不消费最终图像；加载检查源码与依赖版本，运行版本禁止修复／卸载，受损及回收副本保留。共用诊断入口：`src/diagnostics.py`、`scripts/diagnose_workstation.py`。
- 复核效果：`src/review_study.py`、`scripts/compare_review_methods.py`、`scripts/run_review_experiment.py`、`frontend/src/ReviewStudyPanel.tsx`、`docs/review-evaluation.md`；生产提示词白名单复用、数值核对不代替模型回答，历史配方按封存版本验证；独立 Qwen 研究模型固定身份并使用独立服务，不进入日常模型候选；留出实验声明已观察根且单次消费，人工未评不得补成安全，软件类别对照不称现场验收。
- 提交打包：`scripts/build_submission.py`、`scripts/verify_package.py`、`tests/test_submission.py`。

## 验证

- 后端：`python -m pytest tests -q`；前端：`npm run build --prefix frontend`、`npm run format:check --prefix frontend`。
- 模型、浏览器与摄像头验证按 `docs/verification.md` 和 `docs/deployment.md` 执行，并说明实际硬件与范围。
- React 构建产物由 FastAPI 同源托管，单 worker、仅 loopback。标签页共享工作站，切页和关闭浏览器不会暂停采集。默认合成演示不依赖模型；历史测试记录不能算作当前验证。
- 生成脚本会覆盖证据、PPT ；运行前检查目标，提交前审阅这些差异。
- 实际参考外部代码时记录仓库、固定版本、文件、使用方式及许可，不以项目名称推定实现或授权。
