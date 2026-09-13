# Agent 评测与自进化项目阶段性调研报告

## 1. 调研背景与核心方向

近期主要围绕 **Agent Evaluation 与 Agent Self-Evolution** 两个方向开展调研与实验。

随着 Agent 能力快速提升，传统 Benchmark 面临两个越来越明显的问题：

一方面，部分较早期 Benchmark 已被新一代 SOTA Agent 大量解决，整体成功率趋于饱和，难以进一步区分 Agent 能力差异；另一方面，部分较新的 Benchmark 虽然具有较高难度和较强区分能力，但往往依赖复杂的运行环境、模型下载、GPU 资源或特定工具链，导致评测成本和环境适配成本较高，难以直接纳入现有评测体系。

与此同时，LLM-as-a-Judge 已逐渐成为 Agent Evaluation 中的重要组成部分，但实际实验发现，Judge 的准确性并不是一个与 Benchmark 无关的固定能力，而可能受到 **任务类型、Rubric 设计、证据类型、轨迹长度以及领域知识等因素的共同影响**。

因此，本阶段的核心探索逐渐从单纯的“如何生成更多 Benchmark”或“如何提高 Judge accuracy”，转向一个更完整的问题：

> **如何在有限评测成本下，更准确地估计 Agent 的真实能力，并通过评测反馈持续优化 Benchmark、Rubric 和 Agent 本身。**

基于这一目标，目前重点探索以下三个方向：

1. **Benchmark 自动生成与自适应优化**
2. **Rubric 与 LLM-as-a-Judge 的可靠性优化**
3. **Benchmark、Rubric、Judge 与 Agent 的自进化闭环**

---

# 2. 当前核心问题定义

当前阶段将问题拆分为三个层次。

## 2.1 如何构造能够有效区分 Agent 的 Benchmark？

Benchmark 的目标并不是单纯提高任务难度，而是在有限成本下，尽可能获得有效的 Agent 能力信息。

因此需要同时考虑：

* **Difficulty**：任务难度
* **Discrimination**：任务对不同 Agent 的区分能力
* **Coverage**：对不同能力维度的覆盖程度
* **Reliability**：重复运行结果是否稳定
* **Environment Fidelity**：任务是否能够合理反映真实 Agent 工作场景
* **Evaluation Cost**：环境构建、Agent 运行、Judge 和人工复核成本

其中尤其需要区分：

> **Difficulty ≠ Discrimination**

一个任务即使平均成功率约为 50%，如果所有 Agent 的表现都集中在相近区间，也不一定具有良好的区分能力。

因此，后续 Benchmark 优化不应仅以平均成功率作为目标，而应进一步研究任务难度、Agent 能力和任务区分度之间的关系。

---

## 2.2 如何构造能够稳定评价 Agent 的 Rubric？

Rubric 是 Agent 行为与最终评价之间的重要中间层。

当前观察到，Rubric 的设计方式可能显著影响 LLM-as-a-Judge 的判断，包括：

* 任务要求是否明确
* 是否存在硬性要求
* 评价标准是否主观
* 评价对象是 Agent 行为还是最终产物
* 证据来自产物还是 runtime trajectory
* Rubric 的打分粒度
* 是否存在多个标准之间的隐含冲突

因此需要进一步研究：

> **Rubric 的结构特征如何影响 Judge 的准确性、稳定性和区分能力。**

---

## 2.3 如何从 Benchmark 表现进一步推断 Agent Capability？

Benchmark 最终产生的是 Task-level Performance，但实际希望获得的是 Agent-level Capability。

即：

```text
Agent
  ↓
Benchmark Tasks
  ↓
Trajectory / Artifact
  ↓
Rubric
  ↓
Judge
  ↓
Task Performance
  ↓
Capability Diagnosis
```

因此，一个更长期的问题是：

> **如何从有限、带噪声且具有环境依赖的 Benchmark 表现中，估计 Agent 的潜在能力，并使该能力指标能够预测 Agent 在未见任务中的表现？**

这一问题目前尚未形成完整方案，但可能成为 Benchmark、Rubric 与 Agent 自进化之间的核心连接点。

---

# 3. Agent 自进化总体框架

基于目前的实验与调研，初步形成三循环的 Agent Evaluation Self-Evolution 框架。

```text
                         ┌──────────────┐
                         │    Agent     │
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │  Benchmark   │
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │    Rubric    │
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │    Judge     │
                         └──────┬───────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │ Capability Diagnosis│
                     └─────────┬───────────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
        Agent Update      Rubric Update   Benchmark Update
               │               │               │
               └───────────────┴───────────────┘
                               │
                               ▼
                              Agent
```

三个循环分别解决三个问题：

### Loop 1：Rubric / Judge Loop

> **我测得准不准？**

通过历史评测、人类标注、Judge disagreement、Rubric diagnostics 等信息，持续优化 Rubric 和 Judge。

### Loop 2：Benchmark Loop

> **我测得有没有区分度？**

根据 Agent 当前表现动态发现低信息量任务，并生成或筛选更具有区分能力的任务。

### Loop 3：Agent Loop

> **评测结果能否真正推动 Agent 能力提升？**

将 Benchmark 与 Rubric 的评价结果映射到 Capability，进一步用于 Agent 策略、工具使用、规划及执行能力的优化。

---

# 4. Benchmark 自动生成与自迭代

## 4.1 Benchmark 自动生成的必要性

现有 Benchmark 主要存在两类问题。

### 问题一：Benchmark 饱和

部分较早期 Benchmark 已被大量新 SOTA Agent 解决，整体成功率接近饱和，导致进一步区分 Agent 能力的空间有限。

### 问题二：Benchmark 环境成本过高

部分新 Benchmark 虽具有较高难度，但依赖复杂环境。

例如：

* 下载大型模型
* 构建训练环境
* GPU 调度
* 特定工具链
* 复杂依赖
* 长时间运行

这些环境并不一定适合当前统一评测平台。

因此，希望探索一种：

> **能够利用现有环境知识生成具有真实场景 grounding 的 Benchmark，并在生成后自动筛选具有有效区分度的任务。**

---

## 4.2 基于知识库的 Benchmark Generation

当前计划引入 Benchmark Knowledge Base，为任务生成 Agent 提供：

* 已有 Benchmark
* 已有 Task
* Environment 信息
* Tool / API 信息
* Workflow
* Domain knowledge
* 历史 Agent failure cases
* 历史评测结果

需要强调：

> 知识库并不是简单用于“增加任务难度”，而是用于提高 Benchmark Generation 的 grounding 能力。

目标是使生成任务建立在真实环境、工具和工作流程之上，减少生成任务与实际 Agent 场景之间的偏差。

初步设想：

```text
Knowledge Base
      ↓
Environment / Tool / Workflow Grounding
      ↓
Task Generation
      ↓
Candidate Tasks
      ↓
Pilot Agent Evaluation
      ↓
Difficulty / Discrimination / Cost
      ↓
Task Selection
      ↓
Benchmark Pool
```

---

## 4.3 Benchmark 区分度

当前初步考虑使用 Agent 成功率分布评估任务难度，并进一步引入统计方法评估区分度。

平均成功率约 50% 可以作为任务难度控制的启发式指标，但不作为 Benchmark 有效性的充分条件。

例如：

```text
Agent A   50%
Agent B   51%
Agent C   49%
Agent D   50%
```

虽然平均成功率接近 50%，但该任务几乎没有区分能力。

相反：

```text
Agent A   95%
Agent B   80%
Agent C   55%
Agent D   20%
```

即使平均成功率并非 50%，也可能具有更强的区分能力。

因此后续考虑进一步研究：

* Variance
* Correlation-based discrimination
* Pairwise ranking
* Information Gain
* IRT / Item Response Theory
* Agent capability estimation

其中 IRT 可以作为一种潜在的建模方法，用于联合估计：

```text
Agent ability
Task difficulty
Task discrimination
```

但目前仍处于探索阶段，不预设最终采用某一种具体方法。

---

## 4.4 Benchmark 自迭代

传统 Benchmark 的评测过程通常成本较高，因此难以对所有任务、所有 Agent 进行完整测试。

由此考虑将 Benchmark 构造从一次性 Dataset Generation 转变为动态迭代过程：

```text
历史评测数据
      ↓
Agent Capability Distribution
      ↓
发现低信息量任务
      ↓
生成候选任务
      ↓
Pilot Evaluation
      ↓
Discrimination / Cost Evaluation
      ↓
保留高信息量任务
      ↓
更新 Benchmark Pool
```

其核心目标不是简单增加任务数量，而是：

> **在有限评测预算下最大化每一个任务提供的 Agent capability information。**

因此后续需要进一步建立：

> Benchmark Utility = f(Discrimination, Coverage, Reliability, Cost, Difficulty)

目前该部分仍处于方案设计阶段。

---

# 5. LLM-as-a-Judge 评测优化

## 5.1 当前实现

目前已经基于 Harness evaluate-w 框架实现基础的 LLM-as-a-Judge 能力，当前重点转向 Judge accuracy 与稳定性的优化。

初步实验发现，不同任务类型下 Judge accuracy 存在明显差异。

例如：

* Deep Research：约 85%
* Coding：约 80%
* Medical：约 65%

在切换到其他 Benchmark 后，准确率进一步下降至约 60%～70%。

由于当前实验规模有限，暂时无法判断该差异主要来自：

* Task distribution
* Rubric distribution
* Domain knowledge
* Trajectory length
* Evidence quality
* Task complexity

因此当前结论应理解为：

> **LLM-as-a-Judge 的表现可能存在明显的 Task / Rubric / Evidence Distribution Dependency。**

下一阶段需要通过控制变量实验进一步拆解。

---

# 6. Rubric 对 Judge 的影响

## 6.1 Rubric 结构因素

当前初步观察到以下因素可能影响 Judge：

* Tool call 逻辑是否明确
* Error message 是否标准化
* Question 是否复杂
* Question 是否存在歧义
* Rubric 是否明确要求行为结果
* Rubric 是否明确要求最终产物
* 证据来源是 artifact 还是 trajectory
* 打分粒度是否合理

因此计划将 Rubric 表示为结构化数据，并建立 Rubric Structural Features。

初步维度包括：

| 维度                | 示例                        |
| ----------------- | ------------------------- |
| Requirement Type  | Hard / Soft               |
| Evaluation Object | Action / Artifact         |
| Objectivity       | Objective / Subjective    |
| Evidence Source   | Artifact / Trajectory     |
| Granularity       | Binary / Multi-level      |
| Dependency        | Independent / Conditional |

进一步分析：

```text
Rubric Structural Features
          ↓
Judge Accuracy
Judge Reliability
Judge Discrimination
```

目前这些维度仍属于研究假设，需要通过统计实验验证。

---

# 7. Rubric 打分粒度实验

目前对比了：

* 0 / 1 二元评分
* 0 / 0.25 / 0.5 / 0.75 / 1 五档评分

初步观察到，多档评分似乎能够降低部分任务中的评测方差。

但目前尚无法确认该现象是否真正来自评分粒度。

可能原因包括：

1. 多档评分本身能够缓解边界判断问题；
2. 当前 Rubric 描述较粗，不适合直接二元化；
3. Judge 对中间状态存在一定判断能力；
4. 当前任务中存在大量“部分满足”的情况。

因此后续需要进一步区分：

```text
Rubric Quality
        ×
Scoring Granularity
        ↓
Variance / Agreement / Accuracy
```

同时可以借鉴部分成熟 Benchmark 的设计经验：

> 当 Rubric 设计足够精细时，二元评价同样可能获得较稳定的结果。

因此目前不认为“五档评分一定优于二元评分”，而是将其作为一个待验证的交互因素。

---

# 8. Runtime Evidence 对 Judge 的影响

目前针对 Agent runtime evidence 尝试了三种方式：

### 方法 A：Agent 自主 Search Evidence

让 Judge Agent 自行从 runtime trajectory 中搜索相关证据。

### 方法 B：Structured Trajectory

将 runtime trajectory 转换为结构化格式后提供给 Judge。

### 方法 C：Full Runtime Trajectory

直接向 Judge 提供完整 runtime trajectory。

初步结果显示：

> 完整 runtime trajectory 的效果相对较好，并且整体成本与 evidence search 方法接近。

但该结果目前基于有限实验，暂时不能直接得出“完整轨迹一定优于检索”的结论。

可能存在以下混杂因素：

```text
Evidence completeness
Trajectory length
Evidence retrieval ability
Irrelevant information
Judge context capacity
```

因此后续计划进行更严格的对照实验：

```text
Full trajectory
Relevant evidence only
Oracle evidence
Retrieved evidence
Random evidence
Structured trajectory
```

重点回答：

> Judge accuracy 的提升究竟来自“更多证据”，还是来自“更准确的证据选择”。

---

# 9. Judge Error Taxonomy

当前在 Bad Case 分析中发现，Judge 判断错误可能来自不同层级。

因此计划建立 Judge Error Taxonomy：

```text
Judge Error
│
├── Annotation Error
│
├── Rubric Error
│   ├── Ambiguous
│   ├── Incomplete
│   └── Conflicting
│
├── Evidence Error
│   ├── Missing Evidence
│   ├── Wrong Evidence
│   └── Evidence Overload
│
├── Reasoning Error
│
└── Domain Knowledge Error
```

不同错误对应不同优化方向：

| 错误来源                   | 对应优化                             |
| ---------------------- | -------------------------------- |
| Annotation Error       | 人工复核 / 重标注                       |
| Rubric Ambiguity       | Rubric Refinement                |
| Rubric Incomplete      | 补充评价标准                           |
| Missing Evidence       | Evidence Retrieval               |
| Wrong Evidence         | Evidence Selection               |
| Evidence Overload      | Evidence Compression             |
| Reasoning Error        | Judge Prompt / Model / Reasoning |
| Domain Knowledge Error | Knowledge Augmentation           |

该机制可以进一步作为 Rubric 自进化的输入。

---

# 10. Rubric 自进化机制

当前设计“基于 Rubric 的 Rubric”机制，即不只评价 Agent，也评价 Rubric 本身。

Rubric 的评价可以拆分为三个核心维度：

### 10.1 Rubric Validity

该 Rubric 是否真正测量了预期能力？

### 10.2 Rubric Reliability

不同 Judge、不同运行之间是否能够稳定得到一致结果？

### 10.3 Rubric Discrimination

该 Rubric 是否能够区分不同 Agent？

因此：

```text
Rubric Quality
├── Validity
├── Reliability
└── Discrimination
```

进一步将 Rubric 的结构特征与上述指标关联：

```text
Rubric Structural Features
             ↓
 ┌───────────┼───────────┐
 ↓           ↓           ↓
Validity  Reliability  Discrimination
             ↓
         Rubric Update
```

---

# 11. Rubric Bad Case 自迭代

对于 Judge 持续判断错误的案例，当前计划不直接修改 Rubric，而是首先进行错误归因。

流程：

```text
Judge Bad Case
      ↓
Human Review
      ↓
Error Attribution
      ↓
Annotation / Rubric / Evidence / Reasoning
      ↓
对应优化
      ↓
A/B Evaluation
      ↓
保留改进版本
```

其中尤其需要关注：

> Judge 错误并不一定意味着 Judge 本身能力不足，也可能意味着 Ground Truth 或 Rubric 本身存在问题。

因此需要避免：

```text
Judge disagrees with Label
        ↓
Judge is wrong
```

而应该变成：

```text
Judge disagrees with Label
        ↓
Error Diagnosis
        ↓
Label Error?
Rubric Error?
Evidence Error?
Judge Reasoning Error?
```

该机制是后续构建可靠 Judge Pipeline 的重要基础。

---

# 12. Agent Capability 与自进化

Benchmark 与 Rubric 最终都需要服务于 Agent 能力提升。

当前计划将不同 Benchmark 的 Rubric 结果映射到统一的 Capability 层。

例如：

```text
Task Performance
      ↓
Rubric
      ↓
Capability
├── Planning
├── Tool Use
├── Reasoning
├── Recovery
├── Research
├── Coding
└── Execution
```

最终形成：

```text
Agent
 ↓
Benchmark
 ↓
Rubric
 ↓
Capability Diagnosis
 ↓
Agent Weakness
 ↓
Agent Optimization
 ↓
New Evaluation
```

目前最大的未解决问题是：

> **Capability 如何定义，以及 Capability 是否具有跨 Benchmark、跨任务的预测能力。**

后续需要验证：

1. 同一 Capability 是否能够被多个 Benchmark 稳定测量；
2. Benchmark 上的 Capability 分数是否能够预测未见任务表现；
3. Capability 是否比简单的 Benchmark score 更具有泛化能力；
4. Capability 是否能够真正指导 Agent optimization。

---

# 13. 当前阶段性结论

经过当前阶段的调研与实验，形成以下三个初步判断。

### 结论一：Benchmark 的核心问题不是“更难”，而是“更有效”

Benchmark 的有效性需要同时考虑：

> Difficulty、Discrimination、Coverage、Reliability 与 Evaluation Cost。

平均成功率约 50% 可以作为难度筛选的启发式指标，但不能直接代表区分度。

后续需要进一步研究如何在有限评测预算下最大化 Benchmark 的 information gain。

---

### 结论二：LLM-as-a-Judge 具有明显的任务与 Rubric 依赖性

当前实验显示，不同 Task / Benchmark 下 Judge accuracy 存在明显差异。

初步认为：

> Judge accuracy 可能是 Task、Rubric、Evidence、Trajectory 和 Domain Knowledge 等因素共同作用的结果。

因此后续重点将从单纯提高 Judge accuracy 转向：

> **建立 Judge Error Attribution 与影响因素模型。**

---

### 结论三：Benchmark、Rubric、Judge 与 Agent 可以形成评测自进化闭环

当前已经具备：

* 基础 LLM-as-a-Judge
* Rubric diagnostics
* 历史评测数据
* Bad case 分析
* Rubric Structural Features
* Capability abstraction

下一阶段重点验证：

> **评测系统能否利用历史数据自动发现低质量 Benchmark / Rubric，并通过迭代产生更高质量的评测数据，同时最终能够反向推动 Agent Capability 提升。**

---

# 14. 当前完成情况

目前项目已完成或正在推进以下工作：

| 模块                         | 当前状态      | 下一步                                |
| -------------------------- | --------- | ---------------------------------- |
| LLM-as-a-Judge             | 已完成基础实现   | Accuracy / Reliability 优化          |
| Runtime Evidence           | 已完成初步对比实验 | 控制变量实验                             |
| Rubric Diagnostics         | 已建立基础指标   | 扩展结构特征                             |
| Rubric Structural Features | 已形成初步框架   | 统计验证                               |
| Rubric Self-Evolution      | 已完成初步设计   | Bad Case 驱动迭代                      |
| Capability Layer           | 已建立初步抽象   | 验证跨 Benchmark 泛化                   |
| Benchmark Generation       | 方案设计阶段    | 知识库小规模实验                           |
| Benchmark Discrimination   | 指标设计阶段    | IRT / Information Gain 等方法验证       |
| Benchmark Self-Evolution   | 方案设计阶段    | Pilot Experiment                   |
| Agent Self-Evolution       | 概念设计阶段    | Capability → Agent Optimization 验证 |

---

# 15. 下一阶段计划

## 15.1 Benchmark Generation

开展基于 Knowledge Base 的 Benchmark Generation 小规模实验。

重点验证：

* Knowledge grounding 是否提高任务真实性；
* 是否提高任务覆盖范围；
* 是否减少环境不适配；
* 是否能够产生具有更好区分度的任务。

---

## 15.2 Benchmark Discrimination

建立 Task-level discrimination metrics。

优先验证：

* Agent score variance
* Agent ranking correlation
* Pairwise discrimination
* Information Gain
* IRT

最终形成：

> **Task Utility Score**

用于自动筛选 Benchmark Task。

---

## 15.3 LLM-as-a-Judge

针对当前观察到的任务敏感性开展控制变量实验：

```text
Task fixed
 ↓
改变 Rubric

Rubric fixed
 ↓
改变 Evidence

Evidence fixed
 ↓
改变 trajectory

Trajectory fixed
 ↓
改变 Domain
```

目标是建立：

> **Judge Accuracy Factor Model**

---

## 15.4 Rubric Self-Evolution

基于：

* Judge disagreement
* Human agreement
* Variance
* Discrimination
* Error taxonomy
* Rubric structural features

建立自动化 Rubric diagnostics pipeline。

进一步实现：

```text
Detect
 ↓
Diagnose
 ↓
Generate Revision
 ↓
A/B Test
 ↓
Accept / Reject
```

---

## 15.5 Capability Modeling

进一步完善 Capability 层，重点验证：

> Benchmark Performance → Capability → Unseen Task Performance

之间是否存在稳定关系。

如果成立，则进一步探索 Capability 是否可以作为 Agent 自进化的统一优化目标。

---

# 16. 长期研究方向

综合目前的调研与实验，长期目标并不是单纯构建一个“自动生成 Benchmark”的系统，而是进一步探索：

> **如何建立能够持续发现 Agent 能力边界、诊断评测误差并自动优化自身的 Evaluation System。**

理想状态下：

```text
                 ┌──────────────┐
                 │     Agent    │
                 └──────┬───────┘
                        ↓
                 ┌──────────────┐
                 │  Evaluation  │
                 └──────┬───────┘
                        ↓
                Capability Diagnosis
                        ↓
        ┌───────────────┼───────────────┐
        ↓               ↓               ↓
   Agent Update    Rubric Update   Benchmark Update
        │               │               │
        └───────────────┴───────────────┘
                        ↓
                    New Agent
                        ↓
                   New Evaluation
```

最终希望从传统的：

> **固定 Benchmark → 固定 Rubric → 固定 Score**

逐渐演化为：

> **动态 Benchmark → 可进化 Rubric → 自适应 Judge → Capability Diagnosis → Agent Optimization**

其核心目标可以概括为：

> **在有限评测成本下，提高对 Agent 真实能力的估计准确性，并持续缩小 Benchmark 表现与真实任务泛化能力之间的差距。**

---

# 17. 当前最关键的待验证问题

后续研究优先级暂定如下：

### P0：Judge

**不同 Task / Rubric / Evidence 对 Judge Accuracy 的影响到底有多大？**

---

### P0：Benchmark

**什么指标真正能够衡量一个 Benchmark Task 的区分能力？**

---

### P1：Rubric

**Rubric 的结构特征是否能够预测 Judge Reliability / Accuracy？**

---

### P1：Adaptive Benchmark

**根据 Agent 当前能力动态选择任务，是否能够在相同评测预算下获得更多 Capability Information？**

---

### P1：Capability

**从 Benchmark Score 提取的 Capability 是否能够预测未见任务表现？**

---

### P2：Self-Evolution

**Benchmark / Rubric 的自动迭代是否能够真正推动 Agent 在未见任务上的能力提升，而不是仅提高 Benchmark 内部得分？**

---

# 18. 总结

当前阶段已经从单纯的 Benchmark / Judge 调研逐步形成较完整的 Agent Evaluation Self-Evolution 思路。

目前最明确的三个方向是：

**第一，Benchmark：**

> 从“构造更多任务”转向“构造具有高信息量、高区分度且成本可控的任务”。

**第二，Rubric / Judge：**

> 从“提高 Judge accuracy”转向理解 Judge Error，并通过 Rubric、Evidence 与 Judge 的协同优化提高评价可靠性。

**第三，Agent：**

> 从“Benchmark Score”进一步抽象到“Capability”，探索评测结果是否能够真正预测 Agent 在未见场景中的表现，并最终驱动 Agent 自身进化。

因此，当前项目的核心研究问题逐渐收敛为：

> **如何通过 Benchmark、Rubric、Judge 与 Capability 的联合建模，使 Evaluation System 本身具备持续发现问题、诊断问题和优化评测的能力，并最终提高对 Agent 真实世界泛化能力的估计。**
