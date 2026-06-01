# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-06-01

方法论 RAG 化：把 v1.0 硬编码进 system prompt 的非必须章节（套路 / 反面案例 / 特殊场景 / 底层逻辑）搬到 pgvector，按用户输入动态检索 top-k 注入到 user message。硬规则与自检清单仍留在 system prompt 头部，保证 Context Caching 命中率。

### 新增
- `apps/api/rag/`：方法论 chunker（按 `###` 切分）/ embedding 客户端（OpenAI 兼容，默认走智谱 BigModel `embedding-3`）/ pgvector store
- `apps/api/scripts/ingest_methodology.py`：一次性把 `methodology.md` chunk + embed + 入库的 CLI
- `apps/api/supabase/migrations/0001_methodology_chunks.sql`：pgvector 扩展 + `methodology_chunks` 表 + `search_methodology_chunks` RPC
- LangGraph 新增 `retrieve` 节点：`START → retrieve → generate → END`
- `CreationState` 增加 `retrieved_chunks` 字段
- `/health` 暴露 `rag` 字段
- 测试：`test_chunker.py` / `test_rag.py`（含 RAG 关闭时回退、embedder 失败回退、chunk 注入校验）

### 变更
- `prompts/system.py` 重构为 `SYSTEM_PROMPT_RAG` / `SYSTEM_PROMPT_NO_RAG` 双版本 + `build_user_message()` 构造器
- 当 RAG 关闭时自动回退到 v1.0 的硬编码方法论行为（无破坏性变更）

### 工程化
- 新增 settings：`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` / `RAG_TOP_K` / `RAG_MIN_SIMILARITY`
- `Settings.rag_enabled` property = `supabase_enabled and EMBEDDING_API_KEY` — 不配置自动降级

## [1.0.0] - 2026-05-26

首个开源版本。

### 新增
- 创作流：表单输入 → 1-3 篇结构化小红书笔记 + 选题思路
- 内置约 300 行通用方法论（硬规则 / 套路 / 反面案例三段式），覆盖选题、标题、正文、标签、封面、违禁词
- LangGraph 单节点 `StateGraph`，DeepSeek function calling 强制结构化
- SSE 流式事件，前端实时展示 agent 进度
- 标签 / 字段 / 数量等约束在 Pydantic schema 里硬绑定
- DeepSeek Context Caching 自动命中长 prefix，日志输出 `cache_hit` 比例

### 工程化
- Supabase 改为**可选依赖**，未配置时持久化自动 no-op
- DeepSeek 调用带超时 + 校验失败重试（默认 2 次，注入纠错消息）
- SSE 异常被序列化为 `event: error` 帧而非中断连接
- 后端 `pytest` 测试套（schema 校验 / 图构建 / 健康检查）
- `ruff` + `pyproject.toml` + GitHub Actions CI
- 前端错误状态 / 空状态 / 后端不可达 502 提示
- CONTRIBUTING / CODE_OF_CONDUCT / Issue & PR 模板
