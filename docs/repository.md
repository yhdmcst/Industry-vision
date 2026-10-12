# Git 仓库与导入基线

本仓库于 2026-10-06 从已有文件夹建立版本控制。此前没有 `.git`，因此首个提交仅记录导入时的文件状态，不代表原始开发历史，也不能用于推断代码作者或第三方授权。

## 跟踪范围

保留Python 与 React 源码、测试、脚本、配置模板、Python 锁文件与 npm package-lock、文档、模型来源清单与 Modelfile。现有基准 JSON、三张界面截图及 PPT 草稿作为历史交付证据纳入版本控制；新证据须审阅内容并显式加入 `.gitignore` 白名单。

不跟踪 node_modules、frontend/dist、虚拟环境、Python 缓存、系统与编辑器状态、密钥、本地配置、模型权重与 Ollama 缓存、运行数据库、上传素材、日志、临时下载、ZIP 和隔离复现目录。忽略规则不删除本地文件，也不保护已经跟踪文件里的敏感内容。团队资料填写真实联系方式、证据加入现场数据后，发布前需重新检查。

当前保留的二进制证据体积较小，直接使用 Git；大型模型由固定版本与 SHA-256 清单恢复，不纳入仓库。远程托管为 `we-abdn-2026/SparkGuard`；仓库可见性由托管平台设置决定。

## 已知缺失与证据边界

- UI 已迁移为 `frontend/src/` 独立 React 应用，API 入口为 `src/api/app.py`；监测工作台默认使用合成 PCB，通过现有视觉链路计算指标。
- 三个监测模块已从缓存名源码恢复为标准 `.py`，移除了缓存名跟踪例外，原始材料可在导入提交中追溯。
- 文档引用的 `artifacts/test-results.xml`、`artifacts/package-verification.json`、`artifacts/submission/build-report.json` 和 `docs/original-proposal/` 不在当前文件夹中。
- 基准与截图记录的是此前 Windows 环境；导入时环境缺少 OpenCV、NumPy 和 Streamlit；当前已恢复 Python 源码，并为 React / FastAPI 架构重新锁定依赖。历史“65 项测试通过”不能证明本基线可运行。
- 初始化 Git 不改变业务逻辑，也不补造缺失源文件、模型权重或验证报告。

## 日常协作

默认主分支为 `main`。后续独立工作在短期分支进行，例如：

```sh
git switch -c fix/restore-source
git status --short
git diff
git add <本次修改的文件>
git diff --cached
git diff --cached --check
git commit -m "fix: restore runnable source layout"
```

提交按目的保持聚焦，使用 `feat:`、`fix:`、`docs:`、`test:` 或 `chore:` 前缀。涉及行为变更时运行对应验证，记录未执行项目及原因。不要为生成干净状态覆盖他人的未提交修改。

`.gitattributes` 在仓库中规范文本换行，PowerShell 检出为 CRLF，其余指定文本为 LF。历史证据 `artifacts/*.json` 例外保留原始字节，以免换行转换使记录中的文件哈希失效。Git 忽略规则与比赛 ZIP 的文件白名单分别管理；当前打包脚本收集 Python / PowerShell 与白名单中的前端源码、配置及 npm 锁文件，不包含 node_modules、dist 或 `.larkcache`。解包后需要安装前端依赖并构建；打包后仍需独立验证 ZIP 可运行性。

`scripts/build_submission.py` 保留已审阅的依赖锁，但会覆盖 PPT 和 ZIP。依赖更新使用 `uv pip compile requirements.txt --python-version 3.12 --universal --output-file requirements-lock.txt`；不要冻结一个混有旧依赖的开发环境。React 浏览器验收写入 `artifacts/ui-react/`，不覆盖历史截图；模型基准脚本仍须检查输出目标。

远程托管平台、仓库地址与可见性确定后再配置 `origin` 和推送；本地基线提交不包含这些外部动作。
