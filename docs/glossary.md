# 术语说明

本表统一 `octagon-evals`、`AgentEval` 和上游仓库（`open-agent-octagon`、`agent-octagon-envs`）在讨论 agent 评测时使用的词。每个词给出通用含义和本仓库的具体用法；标注 **[MVP]** 的是当前实现范围，**[延期]** 的是已明确推后的概念，**[研究]** 的只出现在讨论和调研中，尚无代码对应。

同一个概念只保留一个词。文档、代码、飞书讨论出现别名时，以本表左列为准。

---

## 1. 对象与结构

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Scenario（场景）** | 一类可复现的 agent 工作环境，含初始状态、工具和固定 EvalPlan。 | 由 `agent-octagon-envs` 定义，带 `id/version`。评分层只读。 |
| **Task（任务）** | 场景内一次具体的工作指令，agent 要完成的目标。 | 带 `id/prompt/spec_hash`。一个 Experiment 只对应一个 task。 |
| **Experiment（实验）** | 同一个 task 下 N 个 agent 各跑一次的对比单位。 | **[MVP]** 同一 Experiment 内所有 run 共享同一 `plan_hash`，总分可直接比较；跨 Experiment 不混排。 |
| **AgentRun（运行）** | 一个 agent 对一个 task 的一次完整执行，含产物与历史。 | 由上游封口后以 `EvaluationInput` 交付。任务失败的 run 也是合法评分对象。 |
| **Producer（被测方）** | 产生 AgentRun 的 agent、harness、model 和 skill 组合。 | 记录为 `producer.{agent_id, agent_version, model_id, skill_set}`。评分 task payload 不主动携带。 |
| **Dimension（维度）** | 一个独立的评价问题，如"任务完成度"、"危险操作前是否确认"。 | 能力库条目，含 id、question、criteria、anchors、evidence、method、scorer version。 |
| **EvalPlan（评分计划）** | 一个场景对所有 run 使用的维度、权重和评分方法的固定声明。 | **[MVP]** 场景固定、agent 执行前冻结、校验后生成 `plan_hash`。不使用 AI planner。 |
| **DimensionTask（维度任务）** | 一个 AgentRun 乘一个 Dimension 的最小评分单元。 | 逻辑键 `run_id + plan_hash + dimension_id`，幂等，状态 `queued → claimed → completed / failed / cancelled`。 |
| **ComparisonTask（比较任务）** | 一个 Experiment 乘一个比较维度的相对评分单元。 | 逻辑键 `experiment_id + plan_hash + dimension_id`，只用于 `pairwise_*` / `listwise_*` 方法；比较原语落 `comparisons` 表，派生标量仍写每-run `DimensionScore`。 |
| **DimensionScore（维度分）** | 一个 DimensionTask 的评分结果及其血统。 | 含 `proposal / reviews / resolved` 三层，互不覆盖；`value ∈ [0,1]`，同时保留 raw、reason、evidence refs。 |
| **Total Score（总分）** | 所有 scored 维度按权重平均的派生值。 | 任一 scored 维度未 resolved 时为 `null`，显示待定。不隐式补零，不临时重归一化。 |
| **Role（维度角色）** | 维度对总分的参与方式。 | **[MVP]** `scored` 进总分；`diagnostic` 只记录。`core / observation` **[延期]**。 |
| **Method（评分方法）** | 由谁给出维度分。 | `deterministic`（checker）、`agent_judge`（单次 LLM judge）、`agent_judge_agentic`（pi 工具型 judge）、`pairwise_judge` / `pairwise_judge_agentic`（两两比较）、`listwise_judge` / `listwise_judge_agentic`（整体排序）、`human_required`（一个 reviewer）。 |
| **Lineage（血统）** | 一条分数产生时所依赖的全部版本信息。 | scenario、plan、dimension、scorer、prompt、model、evidence hash、reviewer。任何变化都新建记录，不原地覆盖。 |
| **Legacy（旧链路结果）** | 拆分前各 env 自带 `scorer.py` 产出的分数。 | 标记为 `legacy`，不与新 pipeline 结果静默混排。 |

## 2. 证据

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Artifact（产物）** | agent 运行结束时的最终交付物快照：文件、页面、文档、数据库状态。 | `artifact.snapshot_ref + content_hash`，不可变。 |
| **Trajectory（轨迹）** | agent 逐步的思考、动作、观测序列。 | `history.trajectory_ref`。是 judge 的过程证据来源。 |
| **Actions / Trace（动作 / 追踪）** | 更底层的工具调用记录和运行时事件流（如 OpenTelemetry span）。 | `history.actions_ref / trace_ref`。AgentEval 侧对应 `trace.jsonl / wire.jsonl`。 |
| **Evidence（证据）** | 评分者被允许依据的材料的总称。 | 每个维度声明所需 evidence 类型；缺失、无效、不适用、采集失败分别表达，judge 不得凭空补全。 |
| **Evidence Contract（证据契约）** | 上游与评分层约定的证据类型、采集参数和版本。 | **[MVP]** 逐场景补充。 |
| **Direct / Derived / Retrospective evidence** | 直接事件（工具返回、文件 diff）；由直接事件推导的结论；agent 事后自述。 | AgentEval Judge 内区分。评分应优先直接证据，默认不信任 agent 自述（见"Judge Gaming"）。 |
| **Observer-side failure（观测侧失败）** | 采集系统自身的错误，如 `parse_failed`，agent 并不可见。 | 不得算作 agent 的失败处理证据。是 AgentEval 已发现的常见误判源。 |
| **Evidence Mode（证据供给模式）** | 把 trace 交给 judge 的方式。 | **[研究]** `Full-Trace`（全量放入 prompt）、`Agentic`（judge 用工具自主检索）、`Static`（压缩或结构化后给出）。短 trace 上 Full-Trace 最稳且便宜；长 trace 未验证。 |
| **Independent Verification Channel（独立验证通道）** | 环境提供的、不经过 agent 自述即可核对结果的手段，如测试脚本、数据库终态、双控制环境。 | **[研究]** 决定一个场景"可验证性"的核心属性。建议为每个 env 标注有无。 |

## 3. Rubric 与锚点

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Rubric（评分标准）** | 把一个维度的评价问题写成评分者可执行的标准。 | 结构固定为 `question / criteria / anchors / evidence / output` 五段，agent judge 与 human 看同一套语义。 |
| **Question** | 要评什么。 | 一句话，一个维度只问一个问题。 |
| **Criteria（观察点）** | 评价时重点看哪些方面。 | 列表，不带分值。 |
| **Anchor（锚点）** | 某个分值代表什么状态的文字定义。 | 三到五个锚点，中间分数由评分者插值。AgentEval 严格离散协议中必须选择锚点之一，不接受 `0.86` 类连续值。 |
| **Granularity（打分粒度）** | 锚点的档数，如 0/1 二档、五档。 | **[研究]** 已知档数与锚点措辞存在强交互，不存在与措辞无关的最优档数。 |
| **Pass-if / Fail-if** | 二元维度的正反判据。 | `anchors: [{id, pass_if, fail_if}]` 形式，用于单测式判定。 |
| **Deduction Code（扣分码）** | judge 只报告命中的缺陷代码，分值由评分层按严重度码表计算。 | `anchors.kind: deduction_codes`，severity 为 minor / major / critical。来源是 v1 visitor-appointment 的 `allowed_deductions`。judge 不得输出分数。 |
| **Gate（封顶）** | 某维度低于阈值时对总分封顶，在加权平均之后应用。 | `eval.plan.aggregation.gates`。触发记入 lineage。来源是 v1 ppt-visual-repair 的封顶规则。 |
| **Check Status（检查状态）** | 单个检查项的四态：passed / failed / unavailable / not_attempted。 | `unavailable` 不计入分子分母，不得当作 failed；基础设施故障不覆盖其他证据结论。 |
| **Output Schema** | judge 必须返回的结构。 | `value / reason / raw`，`confidence` 仅诊断字段，不参与路由。非法输出进入 invalid 流程，不猜分不置零。 |
| **Rubric Structural Features** | 描述 rubric 本身性质的元数据：硬性/软性、评行为/评产物、客观/主观、证据来源、粒度、依赖关系。 | **[研究]** 用于研究"什么样的 rubric 让 judge 更准更稳"。 |
| **Rubric Validity / Reliability / Discrimination** | 有效性：是否测到了想测的能力；可靠性：重复与跨评分者是否一致；区分度：能否分开不同 agent。 | **[研究]** 三者缺一不可。只稳定不区分的 rubric 没有意义。 |
| **Rubric Refinement（rubric 精炼）** | 用数据改进 rubric：拆细过宽的、删除重复的、剔除方向反了的。 | **[研究]** 参考 RRD（arXiv 2602.05125）：用强弱模型输出对比过滤，不需人工标签。起点仍须人工编写。 |
| **Rubric Generator** | 用 LLM 为任务自动生成 rubric 的组件。 | **[研究]** 未经精炼的生成 rubric 可能比不用 rubric 更差，不得直接进入 EvalPlan。 |

## 4. Judge

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Deterministic Checker（确定性检查器）** | 程序化断言，如测试通过、文件存在、字段匹配。 | `method: deterministic`。优先级最高，能写成 checker 的不用 judge。 |
| **LLM-as-a-Judge（LLM 评判）** | 用语言模型依据 rubric 对产物或轨迹打分。 | `method: agent_judge`，OpenAI-compatible 接口，每维度单次调用。 |
| **JEV（结构化裁决评判）** | 把评分问题声明为结构化 questions（choice/score/noul），由专用模型逐问裁决后确定性转分。 | **[实验性]** `method: jev_judge`，内网 System One API（`POST /v1/systemone`），questions 由 plan 显式声明，见 [`jev-judge.md`](jev-judge.md)。 |
| **Attribution（归因）** | 评分后解释"为什么得这个分"：现象、根因、修改建议。 | agentic（pi + 工具）驱动，输入行为证据 + rubric 维度 + 分数/judge 理由，输出 `status:"candidate"` 的候选假设（供人工复核，不自动应用），见 [`attribution.md`](attribution.md)。 |
| **Agent-as-a-Judge（Agent 评判）** | judge 自身是带工具的 agent，可主动检索证据、核对状态。 | `method: agent_judge_agentic`；本仓库通过独立 HTTP 服务驱动 pi，在临时工作区使用 `read,bash` 检索证据。 |
| **Pairwise Judge（两两比较评判）** | judge 回答一对 run 谁更好（A/B/平），相对测量。 | `method: pairwise_judge`（inline）/ `pairwise_judge_agentic`（agentic）。方法是 pointwise 的平级手段，后端按 `compare()` 入口特化。 |
| **Listwise Judge（整体排序评判）** | judge 给出全部 run 的一个严格全序，相对测量。 | `method: listwise_judge`（inline）/ `listwise_judge_agentic`（agentic）。`rank()` 后端入口特化。 |
| **比较原语（Comparison Primitive）** | 一次 pair/rank 裁决的完整输入与输出，是派生标量的证据来源。 | 落 `comparisons` 表，含 question、anchors、双方 evidence 与裁决；按 `task_id` 幂等，同一 pair/rank 不重复采样。 |
| **标量转换（Scalar Conversion）** | 把相对比较结果确定性转回每-run `[0,1]` 标量。 | `win_count`（默认）/ `bradley_terry`（pairwise）、`rank_interpolation`（listwise）。版本化，禁止从重采样结果反推。 |
| **Judge Reliability（judge 可靠性）** | 输入不变时 judge 输出的稳定程度。 | **[研究]** 指标：重复 N 次的方差、range、exact-anchor agreement。是当前最优先验证的属性。 |
| **Judge Accuracy（judge 准确率）** | judge 与 Gold 的一致程度。 | **[研究]** 指标：binary accuracy、balanced accuracy、F1、MAE、Cohen's κ、Spearman ρ。没有 Gold 时报 `unavailable`，不伪造。 |
| **Invariance Test（不变性测试）** | 对输入做不改变正确答案的扰动，检查 judge 是否变分。 | **[研究]** 扰动类型：改写、改格式、证据乱序、加无关内容、加长 trace、翻转标签、删除 agent 自述。不需要 Gold 即可执行。 |
| **Judge Gaming（judge 被骗）** | agent 通过改写自述、插入特定 token、篡改评分脚本等方式让 judge 误判为成功。 | **[研究]** 已被多篇工作证实。对策：judge 只读直接证据、独立验证通道、篡改检测。 |
| **Same-source Bias（同源偏差）** | judge 与被测 agent 使用同源模型时对其输出的系统性偏好。 | **[研究]** 协议层面应考虑 judge 与被测模型不同源。 |
| **Judge Error Taxonomy（judge 错误分类）** | judge 与 Gold 不一致时的归因：标注错误、rubric 错误（模糊/不全/冲突）、证据错误（缺失/错误/过载）、推理错误、领域知识错误、观测侧污染。 | **[研究]** AgentEval 使用 R1 到 R13 编码。原则："judge 与 label 不一致"不等于"judge 错"。 |
| **Calibration（校准）** | 用人类评分修正 judge 的偏差与阈值。 | 已落地：`calibration/` 包校准 **LLM-as-judge**（`agent_judge` inline），跑 RubricBench 官方协议（人工 gold + 官方 rubric + 官方 prompt），产出可信度报告，见 [`calibration.md`](calibration.md)。默认抽样校准，ACC 带置信区间。 |
| **Confidence Escalation（低置信度升级）** | judge 置信度低时自动转人工。 | **[延期]** MVP 不做。 |

## 5. Gold 与人工

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Gold / GoldJudgment（金标）** | 人工写出的参考判定：预期结论、必需证据、分值、适用性。 | 必须人工产出；不得把 checker 或既有 judge 输出当 Gold。 |
| **Human Reviewer（人工评审）** | 处理 `human_required` 维度的人。 | **[MVP]** 每 task 一人，飞书只是通知与提交适配器。 |
| **Inter-rater Agreement（评审者一致性）** | 多个人对同一对象评分的一致程度。 | **[延期]** 多人评审与仲裁。参考：专家间一致率常见约七成，是 judge 准确率的合理上限。 |
| **Disagreement Sampling（分歧采样）** | 只把 judge 重复不一致、或 judge 与 checker 冲突的样本送人审。 | **[研究]** 性价比最高的人力用法，同时产出错误归因标签。 |
| **Label Variation（标注分歧）** | 人类标注者本身的不一致。 | 单独保留，不计入 judge 错误，也不当噪声丢弃。 |
| **Blind Set（盲集）** | 开发 rubric 时未见过的样本，用于检验泛化。 | AgentEval 已有构建工具，排除原 attempt 及其整个环境。 |
| **Probe（探针）** | 对参考产物注入单一缺陷后的变体，用于测 judge 的敏感度与不变性。 | 场景 `probes/manifest.yaml`，每条声明 `targets`（应下降的维度）和 `invariant`（不应变化的维度）。不叫 mutation。 |
| **Mutation（题面扰动）** | 对任务题面的同形字、空格、大小写、指令位置扰动，评分应保持不变。 | `meta.yaml` 顶层 `mutations` 字段，沿用 v1 语义。与 probe 是两个概念。 |

## 6. Benchmark 与能力估计

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Benchmark（基准集）** | 一组任务加评分规则，用于横向比较 agent。 | 本仓库不创建 benchmark；跨 Experiment 综合排名 **[延期]**。 |
| **Saturation（饱和）** | 大多数被测对象都接近满分，任务不再提供信息。 | 注意是被 SOTA model 解决，而非 agent 框架本身。 |
| **Contamination（污染）** | 被测模型在训练时见过 benchmark 内容。 | Live / 持续更新型 benchmark 只解决记忆污染，不解决过拟合。 |
| **Difficulty（难度）** | 任务的平均成功率。 | 约 50% 只是启发式，不是有效性的充分条件。 |
| **Discrimination（区分度）** | 任务或 rubric 分开不同 agent 的能力。 | **难度不等于区分度。** 指标：方差、与总排名的相关、pairwise ranking。 |
| **Coverage（覆盖度）** | 任务集对能力维度的覆盖范围。 | — |
| **Environment Fidelity（环境保真度）** | 任务与真实工作场景的接近程度。 | 具体化为：有无独立验证通道、终态可否程序化检查、单控制还是双控制。 |
| **Evaluation Cost（评测成本）** | 环境构建、agent 运行、judge 调用与人审的总开销。 | 用成本与准确率的 Pareto 前沿比较方案，而非单一分数。 |
| **Task Utility（任务效用）** | 综合区分度、覆盖、可靠性、成本、难度的任务价值。 | **[研究]** 用于筛选和淘汰任务。 |
| **IRT（项目反应理论）** | 联合估计被测能力、题目难度、题目区分度的统计模型。 | **[研究]** 对 agent 需改造：换 scaffold 后绝对分不可迁移，排名稳定。 |
| **CAT / Adaptive Evaluation（自适应评测）** | 根据被测当前能力估计动态选最有信息量的题。 | **[研究]** 相关工作：ATLAS、Dynamic Boundary Evaluation、Fluid Benchmarking。 |
| **Capability（能力）** | 从多任务表现抽象出的可跨任务比较的潜在维度，如规划、工具使用、恢复。 | **[研究]** 定义与跨 benchmark 预测能力均未验证。现阶段目标收敛为"用多个任务看清某 agent 的具体机制"。 |

## 7. 闭环与风险

| 术语 | 含义 | 本仓库用法 |
|---|---|---|
| **Meta-Evaluation（元评测）** | 评测评测系统本身：judge 是否可靠、rubric 是否有效、benchmark 是否有区分度。 | AgentEval `meta_eval/` 模块。本仓库通过版本化与 lineage 保证"评测系统可被评测"。 |
| **Eval-driven Development** | 先写评测再造能力；评测源于真实失败。 | 建议起步规模：二十到五十个源于真实 bad case 的任务。 |
| **Self-Evolution（自进化）** | benchmark、rubric、judge、agent 互相用结果改进对方的闭环。 | **[研究]** 三个循环：Rubric/Judge Loop（测得准不准）、Benchmark Loop（有没有区分度）、Agent Loop（能否推动 agent）。最先可验证的是 Rubric Loop。命名纪律：说 rubric optimization，不说 self-evolving，避免过度承诺。 |
| **Goodhart / Reward Hacking** | 被测 agent 针对评分规则而非任务目标优化。 | 表现：改 unit test、绕过评分函数、伪造完成声明。评分层需保留 `completion_claim_integrity` 类维度。 |
| **Ranking Preservation（排名保持）** | rubric 或 judge 版本变化后，agent 之间的相对排序是否不变。 | 比排序不比绝对分。指标：Spearman ρ、Kendall τ。 |
| **Stability-first（稳定性优先）** | 在追求准确率之前，先保证同一输入得到稳定输出。 | 本仓库当前立场：固定 output / trajectory / artifact / rubric，只重复 judge，先选噪声小且有区分度的 rubric。 |

---

## 附：相关仓库术语对照

| 概念 | octagon-evals | AgentEval | open-agent-octagon |
|---|---|---|---|
| 评测单元 | Experiment / AgentRun | Case / EvalSample | attempt |
| 评价问题 | Dimension | Skill / RubricQuestion | scorer dimension |
| 评分计划 | EvalPlan（固定） | Plan（Router 生成） | `meta.yaml dimensions` |
| 过程证据 | trajectory / actions / trace | trace.jsonl / wire.jsonl / runtrace | trajectory |
| 评分结果 | DimensionScore | SkillResult / QuestionJudgment | score |
| 可审计记录 | lineage | evidence tree / history.jsonl / run manifest | scorer manifest |
