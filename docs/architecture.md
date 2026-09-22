# 架构与生命周期

## 组件边界

```text
agent-octagon-envs
  场景、任务、固定 EvalPlan
          │
          ▼
open-agent-octagon
  调度 agent、执行任务、采集历史、封口 run
          │ EvaluationInput
          ▼
octagon-evals
  建 DimensionTask → 评分 → 聚合 → 输出
```

场景定义评什么，eval 实现怎么评，上游提供一次运行的证据。eval 不负责上游执行故障归因。

## 对象层级

```text
Experiment：同一个 task 的一次对比实验
├── AgentRun A：agent A 跑一次
│   ├── artifact
│   ├── trajectory / actions / trace
│   └── DimensionTask × M
├── AgentRun B
│   └── DimensionTask × M
├── AgentRun C
│   └── DimensionTask × M
└── ComparisonTask（可选，只用于 pairwise_* / listwise_* 比较维度）
    └── comparisons 原语 × P（每 pair/rank 一次裁决）
```

一个 DimensionTask 只包含一个 AgentRun 和一个 dimension。它可以引用该 run 的 artifact、history 或两者，但不能包含其他 agent run，也不能在一个 task 中评价多个维度。

一个 ComparisonTask 属于一个 Experiment 和一个比较维度，横跨多个 AgentRun。它不直接产生 DimensionScore；它的相对裁决经确定性转换（`win_count` / `bradley_terry` / `rank_interpolation`）回写每-run 的 `DimensionScore`，再参与聚合。详细协议见 [`comparison-judging.md`](comparison-judging.md)。

## 生命周期

```text
加载场景
  → 校验固定 EvalPlan
  → 生成 plan_hash
  → 上游创建 N 个 AgentRun
  → 接收 EvaluationInput
  → 为每个 scored/human_required 维度建 task
    （pairwise_* / listwise_* 比较维度不建 per-run task）
  → deterministic / agent judge / human 评分
  → （可选）比较维度：对偶采样 → judge 裁决 → 持久化原语 → 转换派生标量
  → 所有计分维度 resolved
  → 加权平均并生成 final total_score
```

EvalPlan 必须在任何 agent 开始执行前冻结。同一 Experiment 的所有 AgentRun 共享同一个 plan_hash。

## DimensionTask 状态

```text
queued → claimed → completed
                 ↘ retrying → claimed
                 ↘ failed
                 ↘ cancelled
```

评测结果层面使用：

- `pending`：仍有计分维度未 resolved；`total_score = null`；
- `final`：所有计分维度已 resolved，产生总分；
- `incomplete`：到期或重试耗尽，无法完成必要维度；不进正式排名；
- `invalid`：输入不满足 EvaluationInput 契约；
- `eval_failed`：评分系统自身失败；
- `cancelled`：实验或 task 被取消。

上游任务最终未完成不等于 `eval_failed`。只要 run 已封口并交付，失败过程和产物就是正常评分证据。

## 队列可靠性

MVP 采用至少一次投递、幂等写入：

- 逻辑任务键为 `run_id + plan_hash + dimension_id`；
- worker 领取任务获得有期限 lease；
- lease 过期可重新入队；
- 重复提交不得覆盖已 resolved 的结果；
- 技术失败可有限重试；
- 迟到结果不能写入已取消或已封口的评分；
- human task 超时后可重新分派，但不自动改用 agent。

## 可比性范围

同一 Experiment 内的 AgentRun 共享完整 plan，因此总分可直接比较。跨 Experiment 允许场景适配，但不同 plan 的总分默认不直接混排。跨任务综合 benchmark 另行设计。
