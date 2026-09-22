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
11. **比较式评分**：pairwise / listwise 是 pointwise 的平级方法，不是新的 HTTP 端点。方法语义（对偶构建、顺序随机、裁决校验、标量转换、原语持久化）留在主体；后端按 `score/compare/rank` 三入口注入，inline 与 agentic 对每个方法各自特化；judge service 收敛为单一通用执行器，不感知方法。详见 [`comparison-judging.md`](comparison-judging.md)。
12. **比较标量转换**：相对结果用确定性、版本化的转换函数回写每-run `[0,1]` 标量（pairwise：`win_count` 默认 / `bradley_terry`；listwise：`rank_interpolation`），输入是持久化的比较原语，禁止从重采样结果反推。缺失比较的 run 该维度无分数，总分保持 pending。
13. **比较原语持久化**：每个 pair/rank 裁决的完整输入（question、anchors、双方 evidence）与输出落 `comparisons` 表，作为派生标量的证据来源；按 `task_id` 幂等，同一 pair/rank 不重复采样。

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
- 在真实运行数据基础上决定成本预算、超时策略和统计报告。
