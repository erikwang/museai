# ProdGuard — Production Incident Triage Agent
# 生产事故分诊 Agent（练手项目）

为 Yu 量身设计：结合 Equity Derivatives Production Support + HPC / Grid (LSF/Symphony) 背景。
**铁律：只用虚构的合成数据，绝不使用任何真实公司日志、系统名、内部数据。**

## 一句话目标 / Goal

EN: Given a symptom ("pricing service is down", "vol_fit job stuck"), the agent investigates
logs, job status and runbooks on its own, then produces an evidence-backed incident report
with a root-cause hypothesis — it drafts actions, a human approves them.

CN：给一个症状，Agent 自己去查日志、查作业状态、查 Runbook，最后交一份
带证据的事故报告和根因假设；它只起草动作，执行必须人工批准。

## 为什么是这个项目

- 一次练全：ReAct、Tool Calling、Structured Output、RAG、Context 管理、防幻觉、Eval、Human-in-the-loop
- 用的是你最熟的领域直觉（日志、OOM、作业 pending、磁盘满），不用先补新业务知识
- 成品可以讲成一个完整的面试故事：问题 → 架构 → 怎么防幻觉 → 怎么用数据证明它有效

## 系统结构

```
User symptom
    │
    ▼
[ Agent — ReAct loop, temperature = 0, max_steps = 6 ]
    │  Thought → Action → Observation → ...
    ├── tool: query_logs(service, time_window)
    ├── tool: get_job_status(job_id)          ← 模拟 LSF / grid 作业
    ├── tool: get_service_health(service)
    ├── tool: get_recent_changes(service)     ← 部署 / 配置变更
    └── tool: search_runbook(query)           ← RAG over runbooks
    │
    ▼
[ Structured incident report — JSON ]
    │
    ▼
[ Human approval ] → draft_action only (restart / escalate / ticket)
                     → 永远不自动执行破坏性动作
```

## 合成数据（自己造，不要用真实数据）

- `logs/`：20 个虚构事故场景的日志片段
  OOM killed、DB timeout、disk full、vol_fit 加载链过大、LSF job pending（无空闲 slot）、
  网络抖动、证书过期、依赖服务 503、上游行情 feed 延迟、配置变更后报错 等
- `runbooks/`：10 篇短 Runbook（Markdown），每篇对应一类故障：症状 / 检查步骤 / 处置
- `jobs.json` / `services.json`：虚构作业与服务状态，工具就是读这些文件起步，后期再换 API

## 工具的输出契约（防幻觉核心）

每条 Observation 必须带证据 ID，例如 `log:pricing-1502-oom`、`runbook:oom-triage#step2`。
最终报告里的每个结论都必须引用至少一个证据 ID；没有证据的结论只能写 `unknown`。

最终报告 = Structured Output：

```json
{
  "severity": "P1 | P2 | P3",
  "symptom": "string",
  "root_cause_hypothesis": "string",
  "evidence": ["log:... ", "runbook:..."],
  "confidence": 0.0,
  "ruled_out": ["string"],
  "next_action_draft": "string",
  "needs_human_approval": true
}
```

## 分阶段路线（每阶段都有验收标准）

### Stage 1 — 裸写 ReAct（不用框架）· 约 2-3 小时
- Python 手写循环：拼 prompt → 解析模型输出的 Action → 查工具表执行 → 拼回 Observation
- 工具先做 3 个假的：`query_logs`、`get_job_status`、`get_service_health`（读本地文件即可）
- temperature = 0，max_steps = 6
- ✅ 验收：给一个症状，它能自己转 ≥2 圈、查对工具、最后停下来给结论；超步数会强制停

### Stage 2 — Structured Output + 证据规则 · 约 2 小时
- 用 JSON Schema 约束最终报告格式；解析失败自动重试 1 次
- 落地“无证据 = unknown”规则，亲手制造一个幻觉 case 并看它被拦住
- ✅ 验收：报告 100% 可被程序解析；故意给空日志时，它回答 unknown 而不是编根因

### Stage 3 — RAG Runbook · 约 3 小时 · ✅ 代码完成（2026-11-02，38 测试）
- Runbook 切块 → 检索 → 引用（落地时把原计划的 Embedding+Chroma 换成**关键词评分**：
  RAG 的形状 切块→打分→top-k→注入 完全一致，打分器可肉眼调试、零依赖；
  向量版只是替换打分器，接口不变 — runbooks.py 里留了这个缝）
- 体会 Context Window：top-k=2 且零分不返回 — 不相关的手册片段绝不硬塞进上下文
- ✅ 验收：问一个日志里没写处置方法的故障，它能从 Runbook 找到步骤并标出处
  （代码侧已验：相关性/排序/无匹配诚实返回/动作引用手册条款；本地模型实测待 Yu 跑）

### Stage 4 — 换 LangGraph + Human-in-the-loop · 约 3-4 小时 · ✅ 完成（2026-11-05，49 测试全过）
- 把手写循环迁到 LangGraph：状态、节点、checkpoint（graph_agent.py；手写版 agent.py 保留对照，工具/检索/报告/校验全部复用）
- “重启服务”类动作只能生成 draft，流程暂停等人工批准才继续（且仍只是模拟执行）
- 三件套已完成：YU-1 runbook 门禁路由（未查手册强制补查、最多一次）、YU-2 interrupt() 批准断点（approve/reject/edit + note，未知决定按拒绝处理）、YU-3 批准后路由（白名单 approved/edited 才进模拟执行，其余 finalize）
- ✅ 验收：批准点真停住、跨进程从 checkpoint 恢复、edit 替换动作、reject 不执行 — 均已实测

### Stage 5 — Eval（最拉开差距的一步）· 约 2-3 小时
- 建 20 个场景的金标集：期望工具、期望根因、期望 severity
- 指标：工具选对率 / 根因命中率 / 幻觉率（无证据结论占比）/ 平均步数 / 单次成本
- ✅ 验收：一键跑完出成绩单；改 prompt 或换模型后能对比分数有没有退步

### Stage 6（可选）— MCP + 多 Agent
- 把 `query_logs` 包成一个 MCP Server，让 Claude Code / Cursor 也能直接调
- 再拆 Supervisor + 日志专家 + Runbook 专家，体会多 Agent 的收益和代价

## 技术栈

- Python 3.11+，一个模型 API（OpenAI 或 Claude，任选其一先跑通）
- Stage 1-3 只用标准库 + `openai`/`anthropic` SDK + Chroma
- Stage 4 起加 LangGraph；UI 可选 Streamlit，不做 UI 也完全不影响学习目标

## 今天就能开始的第一步（90 分钟版）

1. 建 3 个虚构日志文件，其中一个写 OOM 场景
2. 写 `query_logs()` 假工具：按服务名返回对应日志文本
3. 手写 ReAct 循环骨架，先让模型输出纯文本版 Thought/Action，你用字符串解析
4. 跑通一个问题：“Why did the pricing service fail at 3pm?”
   看它是否先查日志、看到 OOM 后才下结论——跑通这一条，Agent 的核心你就懂了一半
