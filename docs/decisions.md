# 设计决策记录

## 已确认

1. **评分粒度**：一个评分任务 = 一个 AgentRun + 一个维度。
2. **实验结构**：一个 Experiment 包含 N 个 agent 分别运行同一个 task。
3. **Plan 时机**：EvalPlan 在 agent 执行前确定并冻结。
4. **Plan 来源**：MVP 由场景固定定义，不使用 AI planner 动态选择。
5. **Judge 路径**：`agent_judge` 保留 OpenAI-compatible 单次 LLM 调用；`agent_judge_agentic` 通过独立 HTTP 服务驱动 pi，以 `read,bash` 工具读取临时工作区证据。provider/model 可配置，默认沿用 pi 当前默认。每个维度只调用一次。
6. **Human 路径**：只处理场景预先声明的 `human_required` 维度；不做 agent 低置信度升级；每个 task 一个 reviewer。
7. **聚合**：scored 维度直接加权平均；diagnostic 不进总分；所有计分维度完成前总分待定。
8. **来源**：平台不主动向评分者提供 producer agent 来源，但不承诺评分者无法推测来源。
9. **上游边界**：执行、调度、场景和 model 故障归因属于 OpenAgentOctagon，不属于 eval。
10. **版本**：scenario、plan、dimension、scorer、prompt、model 和 evidence 都要可追溯；旧分数不可覆盖。

## 明确延期

- AI planner 和动态维度选择；
- observation evidence cap；
- agent 低置信度自动升级 human；
- 多人评审、一致性和仲裁；
- agent judge 校准、复杂统计检验和跨 Experiment leaderboard；
- 离线 replay 工具；
- prompt injection 的完整防护；
- 复杂的来源指纹清洗；
- 旧 scorer 的自动迁移。

## 后续设计方向

- 在场景固定 plan 之上增加 task-specific plan variant；
- 用维度族和 benchmark profile 约束跨实验的近似可比性；
- 增加更多 evidence 类型和标准化采集参数；
- 评估是否需要多人 reviewer、judge calibration 或比较式评分；
- 在真实运行数据基础上决定成本预算、超时策略和统计报告。
