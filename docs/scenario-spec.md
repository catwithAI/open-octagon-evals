# 场景契约 v2（草案）

状态：draft，供讨论
适用：所有新建场景。旧场景保留为 `legacy`，不迁移。

本契约由评分层（`octagon-evals`）定义，场景仓库（`agent-octagon-envs`）实现。原因是评分层是场景的消费者，消费者定义输入格式比生产者各自发明更稳定。术语以 [`glossary.md`](glossary.md) 为准。

---

## 0. 契约要解决的问题

现有场景是三个时期各自的产物，共同缺陷是维度只有一行 description，没有 question、anchors、evidence、method、version，评分逻辑散落在每个场景的 `scorer.py` 和 `judge_local.py` 里。结果是评分层无法对齐维度，judge 无法被认证，rubric 无法被比较。

v2 的三条原则：

1. **评什么写成数据，怎么评写成可版本化的实现。** 维度是 `meta.yaml` 里的结构化条目，不是 Python 里的隐含逻辑。
2. **能写 checker 的不用 judge，judge 只读直接证据。** 事实类问题走 deterministic；judge 处理判断类问题，且默认不读 agent 的自述。
3. **judge 维度必须先认证再计分。** 没有通过可靠性认证的 judge 维度只能是 `diagnostic`。

---

## 1. 目录结构

```text
<scenario-id>/
├── meta.yaml                 # 场景身份 + eval 块（本契约核心）
├── README.md                 # 设计说明，给人看
├── tasks/*.json              # 任务，沿用 v1 schema（id / prompt / env_name / files / timeout_seconds）
├── inputs/                   # agent 可见的输入物料
├── private/                  # agent 不可见
│   ├── expected/             # deterministic checker 的标准答案
│   ├── rubrics/              # judge 维度的 rubric 文件，一维度一文件
│   └── reference/            # 参考交付物（专家答案或人工写的"好产物"）
├── probes/                   # judge 探针：注入缺陷的参考产物变体，用于 judge 认证
│   ├── manifest.yaml
│   └── <probe-id>/...
├── checkers/                 # deterministic checker 实现，按 dimension 命名
├── renderers/                # 产物到文本的确定性渲染（可选，可引用共享库）
├── certification/            # 认证报告，按 plan_hash 命名，由评分层写入
└── provenance.json           # 外部来源溯源（可选）
```

必需：`meta.yaml`、`tasks/`、`private/expected/` 或 `private/rubrics/` 至少一个、`probes/manifest.yaml`。
缺任一项加载即报错，不静默跳过。

不再允许：场景内自带 `judge_local.py`。judge 调用统一由评分层执行，场景只提供 rubric 数据。

---

## 2. `meta.yaml` 顶层字段

```yaml
name: <与目录名一致>
schema_version: "2.0"
family: document            # 场景家族：document / coding / workflow / benchmark-port
category: office-productivity
test_focus: <一句话，前端展示>
description: <两三句话>

prerequisites:              # 沿用 v1 分级
  level: none | skill-source | office | compiler | media
  requires: []
  on_missing: ""

materials:
  agent:
    - {path: inputs/xxx, target: xxx}

artifact:                   # 产物契约（新增）
  primary: <agent 必须产出的文件路径，相对 workspace>
  format: markdown | docx | xlsx | pptx | json | source-tree
  renderer: <renderer id 或 null>   # 非文本格式必须声明确定性渲染器

mutations:                  # 题面扰动声明，沿用 v1 语义（可选）
  allowed: [baseline]
  forbidden: [unicode-homoglyph, spacing, letter-case, instruction-position]
  scorer_invariant: true

eval:                       # 评分计划，见第 3 节
  schema_version: 2
  plan:
    version: 1
    aggregation: {...}        # 见 3.5
    dimensions: [...]
```

`mutations` 只描述题面可以怎样被扰动、评分是否应对扰动不变，与产物探针（`probes/`）无关。

`prerequisites.level` 去掉 v1 的 `judge` 级别。judge 不再是场景的前置依赖，而是评分层的配置。

---

## 3. `eval.plan.dimensions[]` 条目

每个维度必须包含以下字段。评分层加载时逐项校验，缺失即 `PlanError`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 稳定 ID，`snake_case`，场景内唯一。改语义必须改 ID 或升 version。 |
| `version` | int | 维度版本。question、anchors、evidence、checker 任一变化都要升。 |
| `role` | `scored` / `diagnostic` | 是否进总分。judge 维度未认证时强制 `diagnostic`。 |
| `weight` | number ≥ 0 | scored 权重。总分 = Σ(value × weight) / Σ(weight)。 |
| `method` | `deterministic` / `agent_judge` / `human_required` | 由谁评。 |
| `question` | string | 一句话，只问一件事。 |
| `criteria` | list[string] | 重点观察哪些方面。不带分值。 |
| `anchors` | list | 见 3.1。 |
| `evidence` | list[string] | 允许依据的证据类型，见第 4 节。 |
| `output_schema` | object | 评分输出结构，见 3.2。 |
| `scorer` | object | 实现引用，见 3.3。 |
| `applicability` | object，可选 | 适用性规则，见 3.4。 |

### 3.1 `anchors`

三种写法，一个维度只能选一种。

**离散锚点**（默认，judge 和 human 维度必须用这种）：

```yaml
anchors:
  - {score: 0.0, label: unsupported, description: "备忘中存在参考文件不支持的事实陈述"}
  - {score: 0.5, label: partial,     description: "所有事实有据，但至少一处推断未标明为推断"}
  - {score: 1.0, label: supported,   description: "所有事实陈述可在参考文件中直接找到，推断均已标明"}
```

约束：三到五个锚点；score 单调递增、首尾为 0 和 1；description 描述**可观察状态**，不用"较好"、"基本"之类程度词。judge 必须返回其中一个 score，连续值拒收。

**二元判据**（deterministic 维度可用）：

```yaml
anchors:
  - {id: london_gross, pass_if: "London 行 Combined Gross (USD) = 230754", fail_if: "缺行或数值不等"}
```

deterministic 维度的 value 为通过项占比，或由 checker 按 `expected/` 计算 F1，两者必须在 `scorer.aggregation` 声明。二元判据可带 `points`（默认 1），按分值加权计算占比。

**扣分码**（judge 维度可用，来源：v1 visitor-appointment / document-review 的 `allowed_deductions`）：

```yaml
anchors:
  kind: deduction_codes
  max_points: 15
  severity_points: {minor: 1, major: 3, critical: 5}
  codes:
    - {code: wrong_domain,           severity: critical, description: "产品仍以服务预约、消费订单或其他错误领域为主"}
    - {code: missing_core_roles,     severity: major,    description: "缺少访客、被访人、审核或到访登记中的核心概念"}
    - {code: semantic_inconsistency, severity: minor,    description: "README、实现和界面之间存在领域语义冲突"}
```

语义：judge **只报告缺陷**，输出为命中的 code 列表加每个 code 的证据引用；分值由评分层计算：`value = max(0, max_points − Σ severity_points) / max_points`。judge 不得输出分数，不得报告码表之外的 code。

何时用扣分码而不是离散锚点：一个维度有多个相互独立、可分别取证的失败方式时用扣分码；失败方式是同一连续谱上的程度差异时用离散锚点。两者都可认证，探针的 `targets` 对扣分码维度指的是"应命中某个 code"。

### 3.2 `output_schema`

所有 method 统一：

```yaml
output_schema:
  value: {type: number, min: 0, max: 1}
  reason: {type: string, required: true}
  raw: {type: object}          # deterministic: passed/failed 列表；judge: 选中的 anchor 或命中的 codes，及引用证据
  evidence_refs: {type: array} # judge/human 必须给出引用
  confidence: {type: number, required: false}   # 仅诊断，不参与路由
```

非法输出进入 invalid 流程，不猜分、不置零。

### 3.3 `scorer`

按 method 不同：

```yaml
# deterministic
scorer:
  checker: checkers/revenue_facts.py     # 导出 check(artifact_text, expected) -> {passed, failed, value}
  expected: private/expected/revenue.json
  aggregation: pass_ratio | f1 | all_or_nothing
  version: "1"

# agent_judge
scorer:
  rubric: private/rubrics/source_faithfulness.md
  prompt_version: "1"          # 评分层 judge prompt 模板版本
  evidence_mode: rendered_artifact | full_trajectory | artifact_and_trajectory
  exclude_agent_narrative: true          # 默认 true：不给 judge 看 agent 的自述文本
  certification_required: true
  version: "1"

# human_required
scorer:
  form: private/rubrics/readability.md   # 与 judge 用同一份 rubric，只是呈现形式不同
  reviewers: 1
  version: "1"
```

judge 的模型、endpoint、温度等属于评分层配置，不写进场景。

### 3.4 `applicability`

适用性在 plan 阶段按 task 决定，不能按某个 agent 的运行结果动态删维度。

```yaml
applicability:
  requires_evidence: [trajectory]   # 证据缺失时该维度记为 not_applicable，不记零分
  tasks: [tour_pl_memo_001]         # 省略表示所有 task 适用
```

安全类维度须定义完整判据：未触发风险属于通过，触发前询问属于通过，未询问直接执行属于不通过。

### 3.5 `eval.plan.aggregation`

默认是 scored 维度加权平均。在此之上允许 **gate**：某个维度低于阈值时，总分被封顶。来源是 v1 ppt-visual-repair 的规则（图片未修好总分最高 79，几乎没改最高 59）。

```yaml
aggregation:
  method: weighted_mean
  gates:
    - {dimension: artifact_contract, below: 1.0, cap: 0.0,  reason: "没有合法产物文件，总分为 0"}
    - {dimension: revenue_facts,     below: 0.5, cap: 0.59, reason: "收入事实错一半以上，不能算可交付"}
```

规则：

- gate 在加权平均之后应用，`total = min(weighted_mean, cap)`，多个 gate 触发取最小 cap。
- gate 只能引用 `scored` 或 `diagnostic` 维度，被引用的 diagnostic 维度仍不进加权平均，但可以封顶。
- gate 触发与否、触发前的原始均值都写入 total 的 lineage，界面上显示"被 X 封顶"而不是只显示封顶后的数。
- gate 不是权重的替代。一个维度如果重要到要封顶，通常同时也应有正常权重。
- gate 的 `below` 和 `cap` 变化视为 plan version 变化。

---

## 4. 证据契约

### 4.1 证据类型

| 类型 | 内容 | 来源 |
|---|---|---|
| `rendered_artifact` | 主产物经确定性渲染后的文本 | 评分层调用 `artifact.renderer` |
| `raw_artifact` | 原始产物文件 | 上游快照 |
| `workspace_tree` | 工作区文件列表与哈希 | 上游快照 |
| `trajectory` | 工具调用与返回的结构化序列，**不含** agent 自述 | 上游 `history.trajectory_ref` |
| `agent_narrative` | agent 的思考、说明、完成声明 | 上游 trajectory 的文本部分 |
| `screenshot` / `video` | 视觉证据 | 上游采集 |

`agent_narrative` 必须显式声明才会提供给 judge。唯一合理的使用场景是 `completion_claim_integrity` 这类专门核对"agent 说的和做的是否一致"的维度。

### 4.2 渲染器

非文本产物（docx / xlsx / pptx）必须经确定性渲染成文本后再给 judge。渲染器是评分层的共享组件，场景只引用 ID。同一产物多次渲染必须字节相同，渲染器有版本号并进入 lineage。

理由：让 judge 在沙箱里自己读 Excel 引入的噪声和评分能力无关，v1 的 gdpval-official 场景就是这样做的。

### 4.3 缺失与不适用

缺失、无效、不适用、采集失败分别表达，judge 不得凭空补全。上游任务失败的 run 仍是合法评分对象。

每个检查项（二元判据、扣分码、探针）的状态取四值之一，来源是 v1 visitor-appointment 的 `logic_check_policy`：

```text
passed         证据充分且满足
failed         证据充分且不满足
unavailable    所需证据缺失或采集失败，不计入分子分母
not_attempted  本次评分未执行该检查
```

`unavailable` 不得被当作 `failed`。基础设施原因（渲染器失败、截图工具不可用）导致的 `unavailable` 不能覆盖已有的其他证据结论。

---

## 5. `private/rubrics/*.md`

一维度一文件，judge 和 human 共用。结构固定：

```markdown
# <dimension id> v<version>

## Question
<一句话>

## Criteria
- ...

## Anchors
| score | label | 可观察状态 |
|---|---|---|

## Evidence
允许依据：rendered_artifact, private/reference/*
禁止依据：agent 自述

## Notes for reviewer
边界情况说明，例如"参考文件里没有的城市名算 unsupported"
```

`meta.yaml` 里的 `anchors` 与此文件必须一致，lint 会比对。

---

## 6. `probes/`

探针（probe）是对参考产物注入单一缺陷后得到的变体，用于 judge 认证，也是 rubric 边界的活文档。每个场景至少提供参考产物加三个探针。

命名说明：v1 场景 `meta.yaml` 里的 `mutations` 指**题面扰动**（同形字、空格、大小写、指令位置），v2 保留该字段和语义（见第 2 节）。产物变体一律叫 probe，避免混用。

```yaml
# probes/manifest.yaml
base: private/reference/tour_pl_memo.md
probes:
  - id: wrong_london_gross
    edit: "London 行 Combined Gross 230,754 → 203,754"
    targets: [revenue_facts]              # 应当下降的维度
    invariant: [executive_readability]    # 不应变化的维度
    expected_direction: down
  - id: drop_as_of_header
    edit: "删除 As of 12/31/2024"
    targets: [structure_completeness]
    expected_direction: down
  - id: fabricated_stop
    edit: "新增 Rome 一行，参考文件中不存在"
    targets: [source_faithfulness, revenue_facts]
    expected_direction: down
  - id: paraphrase_only
    edit: "所有段落改写措辞，数字与结构不变"
    targets: []
    invariant: [all]
    expected_direction: none              # 不变性测试
```

规则：一个探针只动一处；每个 judge 维度至少被一个探针 target、被一个探针 invariant。deterministic 维度同样适用，checker 也会写错。

---

## 7. 认证

judge 维度进入 `scored` 前，评分层对 `(dimension, rubric version, prompt version, judge model)` 运行认证，报告写入 `certification/<plan_hash>.json`。

| 项目 | 做法 | 通过阈值（草案） |
|---|---|---|
| 重复稳定性 | 参考产物 + 每个探针，各重复 N=5 | exact-anchor 一致率 ≥ 0.8，score std ≤ 0.1 |
| 探针敏感度 | 对 `targets` 中的维度 | 探针分数低于参考产物，且 5 次中 ≥ 4 次保持排序 |
| 不变性 | 对 `invariant` 维度及 `paraphrase_only` 类探针 | 均值变化 ≤ 0.1 |
| 自述依赖 | 同一产物，有/无 `agent_narrative` 两种输入 | 均值变化 ≤ 0.1（仅对未声明 narrative 的维度） |

阈值先定成这样，跑过第一批场景后再调。认证不需要人工 Gold。

未通过：维度降为 `diagnostic`，报告中记录失败项。改 rubric 后升 version 重新认证，旧报告保留。

---

## 8. 版本规则

- `eval.plan.version` 任何维度增删或字段变化都升。
- 维度 `version` 语义变化时升；只改 typo 不升但必须记 changelog。
- `plan_hash` 由评分层对规范化 plan 计算，同一 Experiment 内必须一致。
- 参考产物、expected、probes 变化视为场景 version 变化。
- 旧结果不覆盖。重新聚合和重新评分是两个操作。

---

## 9. lint 校验清单

评分层提供 `octagon-evals lint-scenario <dir>`，全部通过才可加载：

1. 目录必需项齐全；`name` 与目录名一致；`schema_version` 为 `"2.0"`。
2. 每个维度十个必需字段齐全，`id` 唯一，`weight` 有限非负，scored 权重和大于零。
3. `anchors` 满足 3.1 约束；judge / human 维度使用离散锚点。
4. `evidence` 只含第 4.1 节类型；使用 `agent_narrative` 的维度在 README 中有说明。
5. `scorer` 引用的文件存在；deterministic 的 `expected` 可解析；checker 导出 `check`。
6. `private/rubrics/*.md` 与 `meta.yaml` 的 question / anchors 一致。
7. `probes/manifest.yaml` 中每个 judge 维度至少一次出现在 `targets`、一次出现在 `invariant`。
10. 使用 `deduction_codes` 的维度：码表非空，每个 code 有 `severity`，`max_points` 与 severity 分值能推出 `[0, 1]` 映射。
11. `aggregation.gates` 引用的维度存在，`cap` 在 `[0, 1]` 内。
8. 非文本 `artifact.format` 声明了 `renderer`。
9. 同一缺陷不在多个近义维度中重复计权（人工审阅项，lint 只提示 criteria 重叠）。

---

## 10. 与 v1 的差异

| v1 | v2 |
|---|---|
| `dimensions[].description` 一行文字 | 十个结构化字段 |
| 每场景自带 `scorer.py` 混合所有维度 | 一维度一 checker，judge 由评分层执行 |
| 每场景自带 `judge_local.py` | 禁止；场景只提供 rubric 数据 |
| judge 自己在沙箱读 Excel / PPT | 评分层确定性渲染后给文本 |
| judge 维度直接进总分 | 必须先认证 |
| 无产物探针 | `probes/` 必需 |
| judge 只能直接打分 | 支持 `deduction_codes`：judge 只报缺陷，分值本地计算 |
| 总分只有加权平均 | `aggregation.gates` 支持封顶 |
| `mutations` 指题面扰动 | 语义保留；产物变体改叫 probe |
| `prerequisites.level: judge` | 取消 |
| 权重 0 到 100 | 权重任意非负数，评分层归一 |

---

## 11. 评分层需要跟进的代码

契约落地前 `octagon-evals` 需要改动：

- `models.Dimension` 增加 `criteria`、`scorer`、`applicability` 字段；`load_plan` 目前 `Dimension(**d)` 遇未知键会抛错。
- `validate_plan` 增加 3.1 锚点与 `deduction_codes` 校验、`schema_version == 2` 分支、judge 维度未认证强制 `diagnostic`。
- `aggregation/` 支持 `gates`：封顶在加权平均之后应用，gate 触发记入 total 的 lineage。
- 新增 `renderers/` 共享组件与版本号进入 lineage。
- 新增 `lint-scenario` 子命令和 `certify` 子命令。
- `scorers/agent_judge.py` 支持 `evidence_mode` 与 `exclude_agent_narrative`。

---

## 12. 待讨论

1. 认证阈值是拍脑袋的，第一批场景跑完再定。
2. `human_required` 维度在 pilot 期是 `scored` 还是 `diagnostic`。倾向 diagnostic，作为 judge 的对照而不是阻塞总分。
3. deterministic 维度是否也需要探针敏感度测试。已写入第 6 节：需要。
4. 家族级共享物（渲染器、通用 rubric 如可读性）放场景仓库还是评分层。倾向评分层。
5. 第一个场景样例见 [`scenarios/doc-tour-pl-memo/meta.yaml`](scenarios/doc-tour-pl-memo/meta.yaml)。
