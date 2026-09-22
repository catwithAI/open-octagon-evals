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
14. **Judge 校准**：校准是测量 harness，不是评分方法。目标锁定 **LLM-as-judge**（`agent_judge`，OpenAI-compatible 单次调用）——RubricBench 两个 response 内联在 prompt 里、无证据检索，本质是单次 LLM 比较，不走 agentic/pi 的 agent 循环。用官方协议（人工 gold + 官方原子 rubric + 论文 Appendix F prompt）直连 judge transport，裁决 `[[A]]`/`[[B]]` 解析，不改方法层 prompt 与 judge service 协议。默认**抽样校准**（分层、固定种子、ACC 带 Wilson 置信区间），裁决按 `(case_id, prompt_version)` 幂等落 JSONL 可续跑。详见 [`calibration.md`](calibration.md)。
15. **JEV 实验性方法**：新增 `jev_judge`（pointwise，实验性）接入评分体系——plan 显式声明结构化 `jev_questions`（choice/score/noul + criteria + 可选 expected），`JevJudge` 后端调内网 System One API（`POST /v1/systemone`），确定性转 `[0,1]` 值。**纯增量**：不触碰 `agent_judge` / `agent_judge_agentic` / pairwise / listwise 的任何代码路径；不进入现有场景 plan；评分默认路径不变。详见 [`jev-judge.md`](jev-judge.md)。
16. **自动归因**：归因是评分后的**分析角色**，不是 scoring Method、不进总分。agentic（pi + `read,bash`）驱动：给定行为证据 + rubric 维度 + 分数/judge 理由，输出候选归因（现象 / 根因 / 修改建议，`status: "candidate"`）。继承 agent-eval 纪律：**candidate-only**（供人工复核，不自动应用）、**无对照数据不强行归因**（证据不足写 `insufficient_evidence`）、根因区分 agent_behavior / rubric / evidence / workflow。触发为 API 端点（`POST /tasks/{id}/attribute`、`POST /runs/{id}/attribute`）。详见 [`attribution.md`](attribution.md)。

## 明确延期

- AI planner 和动态维度选择；
- observation evidence cap；
- agent 低置信度自动升级 human；
- 多人评审、一致性和仲裁；
- 复杂统计检验和跨 Experiment leaderboard；
- 离线 replay 工具；
- prompt injection 的完整防护；
- 复杂的来源指纹清洗；
- 旧 scorer 的自动迁移。

## 后续设计方向

- 在场景固定 plan 之上增加 task-specific plan variant；
- 用维度族和 benchmark profile 约束跨实验的近似可比性；
- 增加更多 evidence 类型和标准化采集参数；
- 在真实运行数据基础上决定成本预算、超时策略和统计报告。
