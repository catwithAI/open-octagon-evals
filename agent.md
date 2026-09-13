# Agent 工作说明

## 仓库定位

`octagon-evals` 是评分层，不是 agent 执行框架，也不是场景仓库。它消费来自 `open-agent-octagon` 的已完成运行快照，并依据 `agent-octagon-envs` 提供的固定 EvalPlan 评分。

## 交付边界

上游负责：

- 场景加载与任务调度；
- agent、harness、model 的执行；
- artifact、trajectory、actions、trace 的采集；
- 运行是否已封口、是否可以交付给 eval。

本仓库负责：

- 加载场景固定 EvalPlan；
- 为一个 AgentRun 的每个计分维度创建一个 DimensionTask；
- 执行 deterministic checker 或 agent judge；
- 创建和管理显式 `human_required` task；
- 按权重聚合 DimensionScore；
- 保存评分版本、证据引用和决策血统。

不要在 eval 中重新判断失败来自场景、Octagon 调度、agent、harness 还是 model。上游已完成的 run 即使最终任务失败，也应作为评分证据交付。

## MVP 硬约束

- EvalPlan 由场景固定定义，不使用 AI planner 动态选择维度和权重。
- EvalPlan 在 agent 开始执行前加载、校验并冻结。
- 一个 Experiment = 一个 task + N 个 AgentRun。
- 一个 DimensionTask = 一个 AgentRun + 一个 dimension。
- Agent judge 每个维度只打一次；失败只按技术失败处理，不重复采样取中位数。
- 不做 agent judge 到 human 的自动升级。
- human 每个 task 暂时只分配一个 reviewer。
- `scored` 维度按权重平均；`diagnostic` 维度不进总分。
- 只要有计分维度未 resolved，`total_score` 为 null，界面显示待定。
- scorer、prompt、model、plan、scenario 的版本变化不得覆盖旧结果。
- 平台不主动把 producer agent 来源传给评分者，但不承诺评分者无法从产物特征自行推测来源。

## 实现时的默认判断

- 所有聚合分数归一到 `[0, 1]`；百分制只是展示层转换。
- raw result、reason 和 evidence refs 与 normalized value 一起保存。
- invalid judge output 不能猜分或当作零分。
- 旧 scorer 结果可以保留，但不能和新 pipeline 的结果静默混排。
- 飞书只是 human task 的通知/提交适配器，不能成为评分核心依赖。

## 不要提前实现

以下内容明确延期：

- 多人评审、一致性和仲裁；
- agent 低置信度升级 human；
- observation cap；
- agent judge 校准和复杂统计显著性；
- 离线 replay 工具；
- prompt injection 的完整防护体系；
- 跨多个 Experiment 的综合 leaderboard；
- 根据运行结果动态改变适用维度。
