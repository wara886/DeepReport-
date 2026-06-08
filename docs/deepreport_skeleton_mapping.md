# DeepReport -> Open DeepReport++ 骨架映射

| DeepReport 原模块 | Open DeepReport++ 对应模块 | 处理策略 |
|---|---|---|
| `main.py`（Gradio 主入口） | `src/app/main.py` + `src/app/pipeline.py` | 改写 |
| `config.py`（`.env` / Settings 配置） | `configs/*.yaml` + `src/utils/config.py` | 改写 |
| `src/agents/`（Planning / Researcher / Browser / Analyze / FinalAnswer） | `src/agents/`（planner / analyst / writer / verifier / orchestrator） | 保留骨架，改写职责 |
| `src/search/`（SearchManager / engines） | `src/retrieval/` + `src/search/` 兼容层 | 改写 |
| `src/report/`（HTML / charts / citations） | `src/templates/` + `src/charts/` + `src/report/` | 保留分层，重写实现 |
| `src/utils/model_adapter.py` | `src/generation/backend_base.py` 及后端实现 | 改写 |
| `src/utils/mcp_manager.py` | `src/utils/` 中的工具接入层 | 保留后抽象 |
| `docker-compose.yml` | `docker-compose.yml` / `Dockerfile` / `start.sh` | 保留，按新服务调整 |
| `docs/en` / `docs/zh` | `docs/` / `docs/architecture` / `docs/cloud_training.md` | 保留结构，扩展内容 |
| `requirements.txt` | `pyproject.toml` + 最小依赖集 | 删除旧式锁定，改写 |
| `examples/` | `tests/fixtures/` / `data/raw/mock/` | 改写为可测试样例 |

## 说明

### 目录结构

- 保留“按职责分层”的思路。
- 新项目需要补齐 `schemas / data / features / retrieval / generation / training / evaluation / templates / charts`。

### 运行入口

- DeepReport 的单入口 `main.py` 改为 `src/app/main.py`。
- 新项目要支持 CLI / 本地 smoke / 后续云端训练脚本，而不是只依赖 Gradio。

### 配置层

- 旧项目依赖环境变量直读。
- 新项目改为 YAML 驱动，`.env` 仅保留密钥覆盖层。

### agent 编排层

- 旧项目的多 agent 结构保留。
- 但职责要改成 claim-first：planner、analyst、writer、verifier、orchestrator。

### 搜索 / 检索层

- 旧项目的在线搜索引擎只适合作为远端数据源参考。
- 新项目要补本地 BM25 / 证据库 / 离线检索层，支持 mock 和 local_file。

### 报告导出层

- 旧项目的 HTML 输出方式可借鉴。
- 但必须重写为“证据绑定 + 质量门 + 表格 / 图表 / 引用”一致的导出链路。

### Docker 层

- 旧项目的 docker-compose 结构可保留。
- 需要重新定义服务启动方式、卷挂载、配置注入和 smoke test 入口。

### 依赖管理

- 旧项目的 `requirements.txt` 是典型单文件依赖清单。
- 新项目应改为 `pyproject.toml`，并把模型、batch size、topk、开关都放进 `configs/*.yaml`。
