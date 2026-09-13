# 集成契约

## EvaluationInput

OpenAgentOctagon 交给 eval 的最小逻辑 envelope：

```yaml
evaluation_input:
  experiment_id: exp-123
  run_id: run-agent-a-001
  scenario:
    id: frontend-vfx-volcano
    version: 1
  task:
    id: task-042
    spec_hash: ...
  artifact:
    snapshot_ref: ...
    content_hash: ...
  history:
    trajectory_ref: ...
    actions_ref: ...
    trace_ref: ...
  run_status:
    upstream_completed: true
```

`upstream_completed` 表示 Octagon 已完成采集并封口，不表示任务成功。任务失败、错误、重试和模型行为仍是评分证据的一部分。

eval 只接受满足契约的不可变快照。artifact 缺失、引用损坏或必需字段不存在时，输入为 `invalid`，不产生假分数。

## 来源与评分任务

平台内部可以保存 producer agent、harness 和 model 的 provenance，但评分 task payload 不主动提供这些来源字段。评分者可能从产物特征自行推测来源，MVP 不做复杂指纹清洗。

评分 task 只能引用本 run 的 evidence。不同 agent 的 run 不放入同一个评分 task；跨 agent 比较只在结果展示层进行。

## Evidence Contract

每个 dimension 声明它需要的 evidence：

- `final_state` / artifact；
- screenshot；
- interaction video；
- trajectory / actions / trace。

三方由上游使用同版本采集规则生成 evidence。缺失、无效、不适用和采集失败应分别表达；MVP 对完整证据契约可以逐场景补充，不允许 judge 凭空补全缺失材料。

## Human 与 Feishu

human task 是 eval 核心对象，飞书只是通知和提交适配器：

```text
eval core → 创建/分派 human task
Feishu    → 通知 reviewer，提供评审入口
eval core → 校验并保存评分
```

飞书不可用时 task 保持 pending，不产生错误分数。提交按 task_id 幂等；服务端根据 task_id 加载 run、dimension 和 evidence，不信任前端传入的来源字段。MVP 每个 human task 只分配一个 reviewer。

## 场景兼容性

场景 plan 引用的 dimension ID 必须存在于 eval 能力库。场景加载时校验 schema version、dimension ID、权重和 method；不兼容时在 agent 执行前失败，不生成半个 Experiment。
