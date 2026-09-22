# Judge 校准（RubricBench pairwise）

## 目标

一键校准 **LLM-as-judge**（`method: agent_judge`，OpenAI-compatible 单次调用），
**展现 judge 的可信度**：用带人工 gold 的基准数据跑 LLM-as-judge，统计其裁决与
人工 gold 的一致率，产出测量报告。

**为什么是 LLM-as-judge 而非 Agent-as-judge**：RubricBench 每个 case 的两个
response 都直接内联在 prompt 里，judge 的任务是"读 prompt → 按 rubric 比较 → 出
裁决"，**没有证据检索过程**。这本质上是单次 LLM 调用，不是带工具的 agent 循
环。因此校准目标锁定 `agent_judge`（inline，OpenAI-compatible 单次调用）；
`agent_judge_agentic`（pi + read/bash 工具检索证据）不在本轨道范围，需待有
"证据在工作区里、judge 需要检索"的数据再单独校准。

## 分层原则

校准是**测量 harness**，不是评分方法，不进 `agent_judge` / `pairwise_judge` 等
方法层：

- 校准直连 LLM-as-judge 的 **transport**（默认 inline，复用 `AgentJudgeConfig`
  读 `OCTAGON_JUDGE_ENDPOINT` / `OCTAGON_JUDGE_MODEL` / `OCTAGON_JUDGE_API_KEY`），
  prompt 是 RubricBench 官方协议原文，**不**使用方法层的 system prompt；
- 官方协议裁决是 `[[A]]`/`[[B]]` 非 JSON，**不走** judge service `/judge` 的
  `output_schema` 校验；`/judge` 保持 JSON 裁决不变；
- 评分方法层与 judge service 协议零改动，校准全部新增在 `calibration/` 包。

## 数据契约（仓库之外，只读）

`rubricbench/data/rubricbench_data.json`（list of 1147）：

| 字段 | 含义 |
|---|---|
| `case_id` | 唯一 id |
| `instruction` | 用户指令 |
| `response_a` / `response_b` | 两个候选回答 |
| `label` | 人工 gold：`0` = A 优，`1` = B 优 |
| `rubrics` | **官方原子 rubric**（专家标注，checklist 注入源，无缺） |
| `source` / `domain` | 来源与领域 |

label 均衡（584/563）。domain 分 5 组（与 rubricbench `eval_submission.py` 同口径）：

- IF：`precise if`, `ifeval`
- STEM：`stem`, `math`, `mmlu-pro`, `gpqa`
- CODE：`mbpp`, `code`
- SAFE：`safety`, `harmlessness`
- CHAT：`general`, `focus`, `human-preference`, `factuality`, `helpful`

## 官方协议

### Judge prompt（论文 Appendix F verbatim）

系统提示词全文内嵌为 `calibration/rubricbench.py` 的 `RUBRICBENCH_SYSTEM_PROMPT`：
角色（Impartial Judge / Strict Evaluator）、非偏见规则（位置、长度不干扰，除非是
checklist 条目）、三步流程（`<Evaluation>` 逐条 `[Meets]`/`[Fails]` + 理由 →
`<Justification>` → 独立一行 `[[A]]`/`[[B]]`）。来源：arXiv:2603.01562 Appendix F。

### 输入注入

user prompt = 模板（`calibration/rubricbench.py::build_user_prompt`）：

```text
[The User's Original <Instruction>]
{instruction}
[The Evaluation <Checklist>]
{rubrics}
[The Start of Assistant A's <Response>]
{response_a}
[The End of Assistant A's <Response>]
[The Start of Assistant B's <Response>]
{response_b}
[The End of Assistant B's <Response>]
```

`instruction` / `rubrics`（官方 rubric 作 checklist）/ `response_a` / `response_b`
逐字段注入，**不改原文**。

### 裁决解析

从 judge 原始文本提取 `[[A]]` / `[[B]]`（等价形 `A`/`B`/`0`/`1` 也可，对齐 rubricbench
`parse_prediction`）；提取不到记 **invalid**（按错计，单列 invalid 率）。若 judge
恰好回 JSON，退路用 `scorers/base.py::parse_judge_content` 取 `winner`。

## 抽样校准（默认模式）

全量 1147 个 pair 跑 judge 成本过高，默认**抽样**，报告带置信区间，不把样本当全量：

- `--strategy stratified`（默认）：按分组大小做 Hamilton 最大余数分配预算到各组，
  组内按 label 均衡，固定 `random.Random(seed)` 确定性选取；
- `--strategy random`：全局随机；
- `--strategy full`：全量（忽略 `--limit`）；
- `--limit N`：抽样预算，默认 100；过滤 `--domains` 后若 limit ≥ 可选量自动转全量；
- 抽样与幂等续跑可组合：本次抽样 case 落 verdicts 文件，下次扩大 `--limit`
  续判新 case，报告随累积更新。

## 指标

- 裁决映射：`[[A]]` → `0`、`[[B]]` → `1`；invalid 按错计。
- `ACC = correct / total`（invalid 按错）；`ValidACC = correct / parsed`；
- 组内 ACC（IF/STEM/CODE/SAFE/CHAT），口径与 rubricbench `eval_submission.py::evaluate`
  一致（新实现，不复用其代码）；
- 每个 ACC 带 **Wilson 95% 置信区间**；抽样报告标注样本量与区间。

## 持久化与续跑

每条 case 裁决一行 JSONL（`--verdicts`）：

```json
{"case_id": "rubric_eval_1", "prompt_version": "rubricbench-v1",
 "system_prompt_hash": "sha256:...", "user_prompt": "...",
 "raw_output": "...", "verdict": 1, "gold": 0,
 "backend": "agentic", "model": "deepseek-flash", "correct": false}
```

按 `(case_id, prompt_version)` 幂等：续跑跳过已判，除非 `--force`。报告只读
verdicts 文件即可复现。同时满足"持久化真实输入"：prompt 原文与裁决原文都落盘。

## CLI

```bash
python -m octagon_evals.calibration \
  --data ../rubricbench/data/rubricbench_data.json \
  --backend inline            # 默认 inline = LLM-as-judge；agentic 保留作对照
  --strategy stratified|random|full \
  --domains code,chat \
  --limit 100 \
  --seed 1 \
  --concurrency 4             # 并发 judge 调用数（默认 4，1 = 串行）
  --verdicts calibration_verdicts.jsonl \
  --out calibration_report.md
```

inline 端点配置走环境：`OCTAGON_JUDGE_ENDPOINT` / `OCTAGON_JUDGE_MODEL` /
`OCTAGON_JUDGE_API_KEY`（或 `--model` 只覆盖 model）。

## 真实校准记录

### 2026-09-22（第一次尝试：方向修正）

首次真实跑误用了 `--backend agentic`（pi 驱动），虽然 `--no-tools` 时功能上接近
单次调用，但 pi 是 agent harness，**不是 LLM-as-judge 目标**（用户指出：实验里
没有证据检索过程，本质是 LLM-as-judge）。该次数字（deepseek-flash 经 pi，
code+chat 抽样 10，ACC 0.80）**不作校准结论**，仅记录为方向修正。

### LLM-as-judge inline 校准（2026-09-22）

**judge**：LLM-as-judge（inline，单次 OpenAI-compatible 调用），llm3 网关
`https://llm3.bladeai.com.cn/v1/chat/completions` + `deepseek-4-flash`；
数据 `rubricbench_data.json`（1147，hash `71ed5f86343e61ef`）。

**主记录（stratified 40，全 5 组，seed=1，并发 4）**：

| 分组 | judged | ACC | 95% CI |
|---|---|---|---|
| Overall | 40 | **0.8750**（35/40） | [0.74, 0.95] |
| IF | 4 | 1.0000 | [0.51, 1.00] |
| STEM | 9 | **0.5556**（5/9） | [0.27, 0.81] |
| CODE | 9 | 1.0000 | [0.70, 1.00] |
| SAFE | 3 | 1.0000 | [0.44, 1.00] |
| CHAT | 15 | 0.9333（14/15） | [0.70, 0.99] |

invalid 0。错误 5 条里 4 条在 STEM（rubric_eval_1010/109/157/900）+ 1 条 CHAT
（456），judge 理由都是**实质分歧**（对数学验证、结构、细粒度判据的读法与人工
gold 不同），是 RubricBench 有意筛出的难例，非泄露亦非崩溃。

**前序记录（stratified 10，只 code+chat，seed=1）**：ACC 1.0（10/10，CI [0.72, 1.0]）
——小样本 + 恰在最易的 code+chat 上，出现天花板，**不代表全量水平**；扩到全 5 组
n=40 后落到 0.875。

**答案泄露核查（数据四字段 + 构造 prompt）**：
- `[[A]]`/`[[B]]` 显式裁决在数据中 **0 命中**；"X is better / preferred / winner +
  点名 A/B"收紧扫描无命中（仅任务内容误报）；
- `build_user_prompt` 只注入 instruction / rubrics / response_a / response_b，
  **label 永不见 judge**；
- rubric 与两个 response 的词汇重叠 gap（gold−other）≈ **+0.02**（词）、
  **+0.0068**（4-gram 逐字），近均衡，倾向 gold 者 47.6% vs 40.4%——更像
  "更好的 response 自然更贴合 rubric 判据"的合法信号，不是答案被内嵌；
- **结论**：满分非泄露所致；真实水平由 40 条全组给出（Overall 0.875，STEM 弱）。

**对照**：官方 gemini3-flash rubric 系统全量 Overall ≈ 0.58、CODE ≈ 0.56–0.63、
CHAT ≈ 0.49–0.61。本次 n=40 仍偏小，CI 宽，但已显示 deepseek-4-flash 在
rubric 引导下明显高于官方基线、且 STEM 是短板。

## 边界

- pointwise（agent-octagon gold）与 listwise 校准、多模型一致性、阈值搜索、
  prompt 变体对比——后续演进；
- **Agent-as-judge（带证据检索）校准**：需要"证据在工作区、judge 检索"的数据，
  RubricBench 不适合，留待相应数据源；
- 修改评分方法层 prompt 或 judge service 协议；
- 不改 rubricbench 仓库，其数据只读。
