# 架构设计

## 总体拓扑

前后端分离，所有 agent 编排都在后端 LangGraph 里完成。

```
┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
│  Next.js    │  HTTPS  │  FastAPI         │  HTTPS  │  DeepSeek    │
│  (Vercel)   ├────────►│  + LangGraph     ├────────►│  API         │
│             │   SSE   │  (Railway)       │         │  (V3 / R1)   │
└─────┬───────┘         └────────┬─────────┘         └──────────────┘
      │                          │
      │  Auth + 读历史            │  pgvector / SQL
      ▼                          ▼
   ┌──────────────────────────────────┐
   │       Supabase (Postgres)        │
   └──────────────────────────────────┘
```

**为什么前后端分离**
- LangGraph 的 Python 版生态远比 JS 成熟，文档/教程/案例几乎都是 Python
- Vercel 的 Python serverless 对 LangGraph 这种长链路任务不友好（冷启动 + 超时）
- Railway 月费 $5 起，部署体验和 Vercel 类似
- 分离后能锻炼 API 边界设计，是简历加分项

---

## 共享基础设施

### 方法论知识库 (v1.1+)

```sql
create extension if not exists vector;

create table methodology_chunks (
  id          bigserial primary key,
  category    text not null,                -- 一、底层逻辑 / 三、套路 / 四、反面案例 / 五、特殊场景
  section     text not null,                -- ### 子标题，例如 "1. 选题方法论"
  content     text not null,
  metadata    jsonb default '{}'::jsonb,
  embedding   vector(1024) not null,        -- 默认匹配智谱 embedding-3 (dimensions=1024)
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);

create index on methodology_chunks (category);
create index on methodology_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);
```

外加一个 `search_methodology_chunks` RPC 做余弦相似度检索（见 `apps/api/supabase/migrations/0001_methodology_chunks.sql`）。

- **写入**：`apps/api/scripts/ingest_methodology.py` 一次性 chunk + embed + upsert；改完 markdown 重跑 `--reset` 即可
- **读取**：LangGraph `retrieve` 节点，top-k 默认 8，相似度阈值默认 0.30
- **重要**：硬规则与自检清单**不参与检索**，始终在 system prompt 头部，保证 Context Caching 高命中率 + 防止 retrieval 漏掉关键约束

### 店铺 Memory (v1.4+)

```sql
create table shops (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid references auth.users not null,
  shop_type          text,
  target_audience    text,
  voice_preferences  jsonb,         -- 喜欢什么语气、回避什么词
  history_summary    text,          -- 异步 LLM 总结的店铺画像
  updated_at         timestamptz default now()
);
```

---

## 创作 Workflow（v1.2 完整版预览）

```
            ┌─────────────────┐
            │  intake_node    │  规范化用户输入
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │  retrieve_node  │  RAG 方法论 + 对标爆款
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │  topic_node     │  生成 3-5 个选题方向
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │  writer_node    │  写笔记（标题+正文+标签+封面）
            └────────┬────────┘
                     │
            ┌────────▼────────┐◄────┐
            │  judge_node     │     │  retry (max 3)
            └────────┬────────┘     │
                     │              │
                ┌────▼────┐         │
                │ 合格?    │── No ──┘
                └────┬────┘
                     │ Yes
                     ▼
                  return
```

**v1.0 缩水版**：intake → writer → return，retrieve 用 prompt 硬编码替代，没有 judge。

**v1.1 现状**：retrieve_node → writer_node → return。Retrieve 拉 pgvector 检索结果，writer 用"硬规则 + 自检清单"（system prompt 头部，稳定缓存）+ "检索到的套路与反面案例"（user message 内）组合调用 DeepSeek。当 `EMBEDDING_API_KEY` 或 Supabase 缺失时自动降级为 v1.0 行为（硬编码全文 system prompt），零回归。

---

## 诊断 Workflow（v1.3）

```
parse_notes          ─►  从粘贴文本里结构化提取笔记
analyze_patterns     ─►  统计标题/标签/选题分布
retrieve_methodology ─►  RAG 出相关方法论 + 对标爆款
diagnose             ─►  对比分析，找问题
generate_report      ─►  输出可执行建议
```

**关键 trick**：让 diagnose 节点同时拿到"学员笔记"和"RAG 出的同类爆款"，要求它**对比说明**——"为什么 A 帖能爆而你的不行"，而不是空泛地评价。

---

## 关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| State 管理 | LangGraph `StateGraph` + `TypedDict` | 节点输入输出可追踪，调试友好 |
| 结构化输出 | DeepSeek function calling（OpenAI 兼容，不是 JSON mode） | function calling 在 deepseek-chat 上已稳定，强制 `tool_choice` 比 JSON mode 更可控 |
| Streaming | `graph.astream_events(version="v2")` + SSE | 前端能展示"当前 agent 在做什么"，体验和教育属性都拉满 |
| 数据获取（诊断） | 手动粘贴 → 后期浏览器插件 | 反爬绕不过去，先把核心价值交付 |
| 模型策略 | DeepSeek V3 (`deepseek-chat`) 主力 + R1 (`deepseek-reasoner`) 备用 | V3 便宜快(~¥2/M)，适合主创作；R1 留给 v1.2 judge / 复杂推理场景。Context Caching 自动命中长 prefix(方法论)，无需手动 `cache_control` 标记 |
| Embedding | 智谱 `embedding-3` (默认 1024d，OpenAI 兼容) | 中文质量好、便宜、走 HTTP API 无需本地 GPU；可自由切换 OpenAI / 阿里 |
| 部署 | Vercel (web) + Railway (api) + Supabase (db) | 零运维副业最优解 |

---

## 数据流（v1.0 创作流为例）

```
1. 用户在 Next.js 页面填表单
2. POST /api/generate (Next.js route) → 转发到 FastAPI
3. FastAPI 拿到 GenerationInput → 调 LangGraph.astream_events()
4. 每个 event → 序列化为 SSE → 流回 Next.js route → 流到浏览器
5. 浏览器边收边渲染（每个 agent 的进度 + 最终笔记）
6. 完成后异步写一条 generations 表记录
```
