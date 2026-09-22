# 比较式评分：pairwise / listwise judge

本文定义 pairwise（两两比较）与 listwise（整体排序）两种相对评分的实现协议。
它们与 pointwise 是**平级的方法**，不是新的 HTTP 端点，也不是新的 judge 服务。

## 定位

MVP 的评分是 **pointwise**：一个 `DimensionTask` = 一个 AgentRun × 一个维度，
judge 对单 run 证据给出 `[0,1]` 标量，按权重聚合。

比较式评分是 **相对测量**：

| 方法 | 对象 | judge 回答 | 标量来源 |
|---|---|---|---|
| `pairwise_judge_agentic` | 一个 experiment 的一对 run | A 比 B 好 / B 比 A 好 / 平 | 成对胜负的确定性转换 |
| `listwise_judge_agentic` | 一个 experiment 的全部 run | 一个严格全序排名 | 名次的确定性转换 |

它们不回答"run A 多好"，而是回答"run A 相对 run B / 相对全体如何"。
语义与 pointwise 标量不同，因此：

- 比较维度是 **experiment 级**操作（跨 run），不是 per-run 任务；
- 相对结果必须**确定性地转换**回每-run `[0,1]` 标量，才能复用现有聚合与血统；
- 转换函数版本化、可解释，输入是持久化的比较原语，禁止从重采样结果反推。

## 分层原则

```text
octagon-evals 主体（方法层）───────── 平级方法：pointwise | pairwise | listwise
   │                                  每个方法 = 编排 + 校验 + 确定性转换
   │
   │  后端注入（方法与后端正交）
   ├── LLM-as-judge 后端    InlineJudge   （OpenAI-compatible 单次调用）
   └── Agent-as-judge 后端  AgenticJudge  （驱动独立 pi judge 服务，工具检索证据）
```

- **方法语义留在主体**：谁跟谁比、顺序怎么随机、winner/ranking 怎么校验、
  标量怎么转换、原语怎么持久化。pointwise / pairwise / listwise 是平级 scorer。
- **后端按方法分入口，每个后端自由特化**：后端不是单一 `judge()`，而是
  `score() / compare() / rank()` 三个入口，inline 与 agentic 对每个方法做各自的优化：

| 方法 \ 后端 | InlineJudge | AgenticJudge |
|---|---|---|
| pointwise | `score()`：单候选 prompt | `score()`：单候选工作区 |
| pairwise | `compare()`：双候选 prompt + 位置偏差抑制 | `compare()`：每候选独立证据目录 + 先分别探索再横向比较 |
| listwise | `rank()`：多候选排序 prompt | `rank()`：每候选独立目录 + 先全面浏览再排序 |

- **judge service 保持无知**：它不知道 pairwise / listwise 是什么，只是
  "给定 question + anchors + evidence + output_schema（+ 可选 system_prompt），
  跑 pi 工作区，返回一个满足 schema 的 JSON 裁决"。方法级系统提示由
  agentic 后端在主体拼好，经请求里的 `system_prompt` 字段传过去。

## Plan 声明

`models.Method` 新增四个值（与 `agent_judge` / `agent_judge_agentic` 命名对齐）：

```text
pairwise_judge            inline 后端，两两比较
pairwise_judge_agentic    pi 服务，两两比较
listwise_judge            inline 后端，整体排序
listwise_judge_agentic    pi 服务，整体排序
```

场景固定 EvalPlan 中：

```yaml
- id: code_quality
  role: scored              # 或 diagnostic：只存比较结果，不进总分
  weight: 0.4
  method: pairwise_judge_agentic
  question: "Which candidate implements the requirements more completely and correctly?"
  anchors: [ ... ]
  comparison:
    strategy: round_robin    # round_robin | sampled
    max_pairs: 12            # sampled 时生效；0 = 不限制
    allow_ties: true
    conversion: win_count    # win_count | bradley_terry | rank_interpolation
    conversion_version: "1"
    max_candidates: 16       # listwise 候选数上限
  output_schema: { type: object, required: [winner, reason, raw] }
```

- `comparison` 配置块随 `Dimension` 一起被 `plan_hash` 序列化，
  比较模式随 plan 版本冻结；同一维度不会一会儿 pointwise 一会儿 comparison。
- `validate_plan` 校验：方法白名单新增 4 个值；`comparison` 维度必须有
  `comparison` 块；`strategy` / `conversion` 必须取已支持值。
- `role: scored` 的 comparison 维度参与加权平均；`role: diagnostic` 只保存
  比较原语与派生结果，不进总分（用于纯排序视图）。
- comparison 维度**不创建 per-run DimensionTask**（`tasks/service.py` 跳过），
  它们由 experiment 级的比较编排驱动。

## 数据模型

新增 `ComparisonTask`（experiment 级）：

```python
@dataclass
class ComparisonTask:
    id: str                 # f"{experiment_id}:{plan_hash}:{dimension_id}"
    experiment_id: str
    plan_hash: str
    dimension_id: str
    method: str             # pairwise_judge* | listwise_judge*
    state: str = "queued"   # queued -> completed / failed
    attempts: int = 0
    lease_until: float | None = None
```

**比较原语必须持久化**（这是硬约束：存的必须是喂给 judge 的输入原文，
禁止用重新采样的输入解释旧结果）。新增 `comparisons` 表，一行一次 judge 裁决：

```text
comparisons: id | task_id(unique) | experiment_id | plan_hash | dimension_id
             | kind('pair'|'rank') | input_json | output_json | lineage | created_at
```

- `kind='pair'` 行的 `task_id` = `{exp}:{plan_hash}:{dim}:{a}_vs_{b}`（a<b 字典序），
  `input_json` = 该 pair 的 question + anchors + 双方完整 evidence，
  `output_json` = judge 原始裁决（winner/reason/raw）。
- `kind='rank'` 行的 `task_id` = `{exp}:{plan_hash}:{dim}:rank`，
  `input_json` = question + anchors + 全部候选 evidence，`output_json` = ranking/reason/raw。
- 幂等：同一 pair/rank 的 `task_id` 已存在时复用其输出，**不重新采样**。

**派生标量**仍用现有 `{run_id}:{plan_hash}:{dimension_id}` task_id 写
`DimensionScore`，聚合层完全不动。派生分数携带 comparison 血统。

## Judge 服务协议扩展

`POST /judge` 仍是唯一端点。请求体增加两个可选字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `system_prompt` | string | 覆盖默认 judge 系统提示；由主体里的 agentic 后端按方法拼好 |
| `files` | object | 显式工作区文件映射（`path -> content`，path 可含 `/` 建子目录） |

响应体增加 `result`：始终携带 pi 输出解析出的完整 JSON 裁决。
pointwise 裁决是 `{value, reason, raw}`，`value/reason/raw` 三个派生字段照旧填充，
向后兼容；compare/rank 裁决是 `{winner, ...}` / `{ranking, ...}`，
`value` 为 `null`，后端在主体校验方法级语义（winner ∈ 候选 ∪ {tie}、ranking 是全排列）。

工作区布局：`evidence.json` 保留完整请求；默认把 `evidence` 每个顶层 key
写成 `evidence/<key>` 文件。agentic 后端的 compare/rank 通过 `files` 把每个候选的
evidence 落到 `{candidate_id}/<key>` 子目录，系统提示要求先分别探索再比较/排序。
pi 命令、NDJSON 解析、去重、超时与错误协议不变。

## 标量转换

确定性函数，版本化，输入来自持久化比较原语，输出 `[0,1]` 标量。
缺失比较的 run 该维度无分数 → 该 run total 保持 pending（缺失不隐式当零分）。

### pairwise

比较矩阵 `M`：对每个 pair 计 a 胜 b / b 胜 a / 平（平记各 0.5）。

- `win_count`（默认，透明）：`score_a = (wins_a + 0.5·ties_a) / comparisons_a`。
  语义 = "a 在一对一比较中的胜率"。完整 round_robin 矩阵下最干净。
- `bradley_terry`（sampled / 比较次数不均时推荐）：迭代估计强度 `s_a`，
  使 `P(a>b) = s_a/(s_a+s_b)`，按最大强度归一化到 `[0,1]`。lineage 记录迭代参数。

### listwise

- `rank_interpolation`：K 个候选、无平局，`score = 1 − (rank−1)/(K−1)`（K=1 → 1.0）。

## 编排与 API

- `POST /experiments/{id}/runs`：comparison 维度不创建任务。
- 新端点 `POST /experiments/{experiment_id}/compare`，body：

```json
{
  "dimension_id": "code_quality",
  "evidence": { "run-a": { "...": "该 run 该维度的证据" }, "run-b": { "...": "..." } }
}
```

  服务流程（`service.score_comparison`）：
  1. 读 experiment 全部 run 的该维度证据，排序得到 run_ids；
  2. 按 `strategy` 构建对偶（round_robin 全量 / sampled 用 `max_pairs`，
     种子 = plan_hash 确定性采样）；
  3. 每对：pair key 已存在于 `comparisons` 表 → 复用输出；否则后端
     `compare()` 取裁决 → 校验 winner → 持久化原语；
  4. 转换函数把矩阵/排名转成每-run 标量；
  5. 每 run 写派生 `DimensionScore`（幂等），并登记 per-run DimensionTask（completed）；
  6. 标记 `ComparisonTask` completed。全部完成后
     `GET /experiments/{id}/score` 无需改动即可出总分。

- 幂等与"一次采样"：pair/rank 原语落库后重复触发复用，不重复调 judge；
  重复提交同一 comparison 返回既有派生分数。

## 血统

派生 `DimensionScore.lineage`：

```json
{
  "comparison_type": "pairwise",
  "strategy": "round_robin",
  "conversion": "win_count",
  "conversion_version": "1",
  "allow_ties": true,
  "position_order": "seeded-random",
  "comparisons": 6, "wins": 4, "losses": 1, "ties": 1,
  "pair_task_ids": ["exp:p-h:dim:run-a_vs_run-b", "..."]
}
```

## 边界（不提前实现）

- listwise 的平局组（`/rank` 只接受严格全序）；
- 每 pair 双次对称调用标定（保持每 pair 一次，位置偏差用种子随机化缓解）；
- 多模型 judge 一致性 / 校准；
- 跨 Experiment 综合 leaderboard（比较是 experiment 内相对测量，不可跨实验拼）；
- knockout / 二分锦标赛式采样。

## 真实冒烟记录（2026-09-20）

用 `agent-octagon/data-smoke-deepseek` 的真实 attempt 做了一次端到端真实评测：
真实 pi judge（`deepseek` provider，`deepseek-flash` 模型），驱动独立 judge 服务。

- **数据**：`sum_of_squares`（example-coding）任务的 3 个 completed attempt，
  产物与行为均来自磁盘上的真实 wire/trajectory/answer.txt：
  `claude-code`（有推理 + Bash 写盘 + read-back 核对）、`codex`（单句自述
  "Done. Wrote 385."）、`fake`（`task_started → file_written → task_completed`
  的 0 推理 stub）。三者 `answer.txt` 都是正确答案 `385`。
- **维度**：`execution_quality`，问题强调"真实计算/核对、不是 no-op stub"。
- **无 rubric 基线**：
  - **listwise**（一次 rank 调用）：`claude-code 1.0 > codex 0.5 > fake 0.0`。
  - **pairwise**（round_robin，3 次 compare 调用）：`claude-code 1.0 > fake 0.5 > codex 0.0`。
  - 同一批证据下两方法对 `codex` / `fake` 的排序**不一致**。

### fake 案例的定性（查数据后澄清）

`fake` 是 harness 的 **CI/冒烟测试桩**：`backend/adapters/fake_agent.py` 明确"用任务
自带的期望产物确定性地完成 attempt，不参与真实对比评测"。输入快照
`{"fake_agent": {"files": {"answer.txt": "385"}}}` 说明答案是**预置**的；
`execution_locus: in_process_fake`、0 token、0 tool、0ms。因此它在**计算层是零证据**，
但在**产物层全对**（答案正确、`file_written` 是真实副作用、事件日志真实）。
**产物+事件证据无法区分它和"秒写正确答案的真 agent"**——所以早期"judge 被事件日志
迷惑"的说法不准：judge 拿到的证据里本来就不存在区分手段。

### rubric 对照实验（验证判定标准假设）

同一个维度，加上显式 3 条 criteria（artifact / computation / verification）与
tie 规则，重跑两方法：

- **listwise（with rubric）**：`claude-code 1.0 > codex 0.5 > fake 0.0`，
  但 judge 明确说"codex 和 fake 只满足 criterion 1、**相等、顺序任意**"。
- **pairwise（with rubric，单对 codex_vs_fake）**：`winner = tie`（各 0.5）。

**结论**：无 rubric 时的两方法排序不一致，根因是**判定标准未定义**——judge 对
"什么算真实执行"自由发挥，pairwise 里把 `file_written` 事件当成了强证据。带上显式
rubric 后两方法的**底层判断收敛一致**：`claude-code > {codex ≡ fake}`。
剩余差异只在转换层：`rank_interpolation` 无法表达平局，把 judge 判"相等"的两个
硬排成 0.5 / 0.0，而 pairwise 的 `win_count` 正确给出各 0.5。这正是边界里
"listwise 平局组不提前实现"的真实代价——有真实数据支撑后应重新考虑。

### 真实测试抓到的实现问题

- **agentic client 对 judge 服务非 200 会崩调用链**：pi 超时返回 422 时，
  `urllib.HTTPError` 未被捕获，整个比较被打崩。已修：客户端把 4xx/5xx 转成
  `InvalidJudgeOutput`，compare 端点映射 422 可重试。
- **比较编排不是崩溃可恢复的**：一次比较中途某对失败时，已判的 pair 原语未落库，
  重试会对同一 task_id 重新采样，撞上 judge 服务 409 去重。比较原语应**逐对**落库
  （与"至少一次投递 + 幂等写入"的队列原则一致），才能承受中途失败。

这验证了设计里的两个约束：比较原语必须持久化（可回看 judge 到底看到了什么），
以及转换输入必须来自持久化原语（不能用重新采样的输入解释旧结果）。
当前是单次无重复采样，不做统计结论；多模型/多重复的一致性测试在边界外。
