# 自动归因（Attribution）

## 目标

评分之后，用 **agent（pi + `read,bash` 工具）** 对一次评分做归因：给定**行为证据**
（工作区文件）、**rubric 维度**（question / 扣分锚点）、**分数与 judge 理由**，
输出**现象描述、根因（内核）、修改建议**——供人工复核的候选假设。

设计模仿 agent-eval 的归因分层，继承三条纪律：

- **candidate-only**：归因是候选假设，不是自动错误判定，绝不自动应用；
- **无对照数据不强行归因**：证据不足时如实写 `insufficient_evidence`，不编造成因；
- **根因区分来源**：agent 行为 / rubric 缺陷 / 证据缺口 / 工作流，不把"低分"
  直接归成单一成因。

归因是评分后的**分析角色**，不是 scoring Method，不进总分。

## 输入契约

一次归因 = 一个任务的一个已评分维度：

| 输入 | 内容 |
|---|---|
| `dimension` | id / question / score_anchors（扣分点）/ evidence / method |
| `score` | value / reason（judge 理由）/ source / lineage |
| `evidence` | 行为（与评分同构的 dict，铺进工作区供 agent 检索） |

归因 agent 能看到**实验视角可见的一切**：行为、rubric 扣分点、分数、judge 理由等。

**行为证据必须是 semantic runtrace，不是 transport**：记录"这一轮决策时 agent 实际
可见的全部语义状态 + agent 对外产生的可见动作/结果"（system/tools/user prompt/注入
context/assistant 消息/tool call+result/最终答案），而不是底层传输过程（SSE chunk、
token delta、heartbeat、socket/HTTP 事件等）。判据：**删掉后会影响 agent 下一步决策
的信息属于 semantic；不影响决策、只影响传输/调试的不属于**。transport 只能作为调试
日志，不能当行为证据——否则归因 agent 会去啃流式噪声（实测：434KB wire 里大部分是
传输碎片，导致归因超时且无信息量）。

## 输出 schema（`octagon_evals.attribution.v1`，candidate-only）

```json
{
  "schema_version": "octagon_evals.attribution.v1",
  "status": "candidate",
  "phenomenon": "观察到 agent 在该维度得分 X，行为层面……",
  "root_causes": [
    {"category": "agent_behavior|rubric|evidence|workflow|insufficient_evidence",
     "description": "...", "evidence_refs": ["..."], "confidence": "high|medium|low"}
  ],
  "suggestions": [
    {"target": "agent|rubric|evidence|workflow", "action": "...", "rationale": "..."}
  ],
  "notes": ["归因是候选假设，供人工复核；证据不足不得强行归因"]
}
```

## 模块

```
src/octagon_evals/attribution/
  role.py      # ATTRIBUTION_SYSTEM_PROMPT + build_user_prompt + parse_attribution + schema 校验
  service.py   # AttributionService：create_evidence_workspace → PiRunner(agentic) → parse
```

- `role.py`：系统提示词定义归因 agent（先陈述现象 → 定位根因 → 给修改建议，只认证据
  支持的根因）；`build_user_prompt(dimension, score, evidence_meta)` 三段块注入；
  `parse_attribution` 用 `parse_judge_content` 容错解析 + schema 校验。
- `service.py`：`create_evidence_workspace` 铺行为证据 → `PiRunner(config).run`
  （agent 用 `read,bash` 检索后输出 JSON）→ `parse_attribution`；lineage 记录
  `{model, prompt_version, judge_service_version}`。

## 触发（API 端点）

- `POST /tasks/{task_id}/attribute`，body `{evidence}`：单维度归因；
- `POST /runs/{run_id}/attribute`，body `{evidence}`：该 run 所有已评分维度批量归因。

配置走 `JudgeServiceConfig`（env `OCTAGON_JUDGE_PI_BIN` / `OCTAGON_JUDGE_PROVIDER` /
`OCTAGON_JUDGE_MODEL` 等）。

## 边界

- 仅 agentic 后端（pi + 工具）；inline 归因不做；
- 归因 v1 仅 API 返回候选，不落 DB（归因表后续）；
- 跨 run/跨模型的归因聚合（gap 分解那种需要多 run 对照数据，遵循"无对照不归因"）；
- 自动应用修改建议不做（candidate-only，人工复核后才有下游动作）。

## 真实归因记录（2026-09-22）

用真实 pi（agentic，deepseek provider + deepseek-flash）对 sum_of_squares 的
claude-code attempt 做归因（dimension `execution_quality`，value 0.4，judge 理由
"有 write 动作但核对动作不足"）：

- **现象**：得分 0.4 落在 noop=0.0 / verified=1.0 之间；行为层面只有 `final_answer=385`
  正确 + 一次写后 read-back 确认，无可见的独立计算/核对动作；
- **根因（区分来源）**：
  - `evidence`（high）：execution_summary 被截断，无工具调用轨迹，judge 无法确认
    "真计算" vs "只声称"——低分可能反映**观测缺口**而非行为失败；
  - `rubric`（high）：锚点是二元的，无法表达"写了结果但核对不足"的 0.4 带，且
    read-back 是否算"核对"语义不清；
  - `agent_behavior`：可见轨迹内，agent 仅以单次 read-back 作为核对，无独立复核；
- 候选假设（`status: candidate`），证据引用与 confidence 齐全，供人工复核。
