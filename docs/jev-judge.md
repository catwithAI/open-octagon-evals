# JEV-as-Judge（实验性 `jev_judge`）

> **实验性**：纯增量改动，不进入任何现有场景 plan；不触碰 `agent_judge` /
> `agent_judge_agentic` / pairwise / listwise 的任何代码路径。稳定前方法名与
> 字段带实验语义，评分默认路径不变。

## 目标

尝试把 **JEV**（内网 System One 开源模型）作为 judge：输入被评文本 `state` +
结构化 `questions`，返回每 question 的结构化裁决，确定性转换为 `[0,1]` 维度分。

## API 契约（内网 `http://192.168.130.23:8100`，实测）

- `GET /v1/models` → `auto`(→kev-4b)、`kev-4b`(8192 ctx)、`laya-multilingual`(1024)、
  `laya-english`、`laya-typed-decisions`；
- `POST /v1/systemone`：
  ```json
  {"model": "laya-multilingual", "state": "<被评文本>",
   "questions": {"<name>": {"type": "choice|score|noul", "instructions": "...",
                             "criteria": {...}, "expected": "..."}}}
  ```
- question 合法类型（实测）：
  - `choice` → `{type, choice, probabilities, confidence}`；
  - `score` → `{type, score: 0-1, legend, probabilities, confidence}`；
  - `noul` → `{type, noul: 0-1, confidence}`；
- openapi 为空壳，仅实测可得；`expected` 是我们加在 question 上的**评分期望**，
  API 透传忽略。

## 设计

### 新模块 `src/octagon_evals/scorers/jev.py`

- `SystemOneConfig`：url/model/timeout，env `OCTAGON_JEV_URL` /
  `OCTAGON_JEV_MODEL` / `OCTAGON_JEV_TIMEOUT`；
- `SystemOneClient.judge(state, questions)`：POST `/v1/systemone`，非 200 →
  `InvalidJudgeOutput`；
- `JevJudge.score(task_id, evidence, dimension_question, *, anchors=None,
  output_schema=None, evidence_keys=(), jev_questions=None)` → `DimensionScore`；
  测试可注入 fake opener / client。

### state 解析（实验性 v1）

按 `dimension.evidence` 命中的第一个**字符串**证据值 → state；否则依次取
`final_answer` / `answer` / `artifact_text`；再否则 `json.dumps(evidence)`。
字符串截断到 `STATE_MAX_CHARS`（3000，对齐 laya 1024 token ctx 的保守界）。

### questions 来源

plan 显式声明的 `dimension.jev_questions`（见下），逐字透传给 API。

### 值转换（确定性）

- `score` → 取 `score`（0-1）；
- `choice` → `1.0` 若 `choice == expected`，否则 `0.0`；无 `expected` 记
  **diagnostic**（不进均值）；
- `noul` → `1 - noul`；
- `value` = 非 diagnostic 问题均值；全 diagnostic → `value = 0`；
- `reason` = 每 question 的 `{type, verdict, confidence}` 摘要串；`raw` =
  `{"answers": <API 全量>, "verdicts": <逐问判定>}`；`lineage` =
  `{model, api, prompt_version}`；`source = "jev_judge"`。

### 方法层接线（纯增量）

| 文件 | 改动 |
|---|---|
| `models.py` | `Method` 追加 `"jev_judge"`；`Dimension` 追加 `jev_questions: dict \| None = None` |
| `plan/validator.py` | `_METHODS` 追加；`_validate_jev` 校验 questions 结构 |
| `service.py` | `__init__` 追加 `jev_judge`；新增 `score_jev_judge`（镜像 `score_agent_judge`） |
| `api.py` | `create_app` 追加 `jev_judge` 参数；scoring dispatch 追加 `jev_judge` |

### plan 声明示例

```yaml
- id: answer_quality
  version: 1
  role: scored
  weight: 1.0
  method: jev_judge
  question: "评估答案质量"
  evidence: [final_answer]
  jev_questions:
    correctness:
      type: score
      instructions: "答案是否正确且可验证？"
      criteria: {low: "错误或无法验证", high: "正确且可验证"}
    computed:
      type: choice
      instructions: "是否真实完成计算？"
      criteria: {yes: "有计算过程", no: "没有计算"}
      expected: "yes"
```

## 边界

- 仅 pointwise；pairwise/listwise 的 JEV 后续再议；
- `state` 受模型 ctx 限制，长 evidence 仅截断，不做分段；
- 模型默认 `laya-multilingual`（示例默认），`kev-4b` 可配；不做模型对比；
- 实验性：不进入现有场景 plan，评分默认路径不变。

## 真实冒烟（2026-09-22）

sum_of_squares 的真实 evidence（`final_answer=385`）走 `jev_judge` dimension
（correctness score + computed choice(expected yes) + polish noul）：

- value = **0.7464** = mean(0.9583, 1.0, 1−0.7191)，reason/verdicts/lineage 正常；
- 观察：noul 对裸 `"385"` 判 0.72"空"——state 过于稀疏时 noul 会惩罚；声明
  dimension 时应选更丰富的 evidence（如最终产物全文或含执行摘要），而非单数字。

