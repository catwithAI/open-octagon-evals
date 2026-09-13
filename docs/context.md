# 背景与路线

## 为什么拆评分层

原先 `agent-octagon` 中每个 env 有自己的 `scorer.py`，带来三个问题：

1. 评测项硬编码在 Python 中，评什么和怎么评混在实现里；
2. 主观维度被源码关键字或正则替代，过程分可能很高，但没有真正评价最终产物；
3. 美学、交互手感和真实体验没有 human 的补位路径。

拆出 `octagon-evals` 后，场景、执行和评分可以独立演进，也可以单独替换 checker、judge、聚合或 human 适配器来做消融实验。评测系统本身也因此可以被评测。

## 核心立场

默认 agent 优先，human 只补足 agent 当前不擅长的少数感官或体验维度。MVP 中 human 只处理场景固定声明的 `human_required` 维度，不是每个实验的必经环节。

平台不主动向评分者提供 producer agent 的来源标签，但不把“评分者绝对无法猜到来源”当作公平性的必要条件。真正的横向可比性来自同一 Experiment 共用同一份 plan、证据契约和评分配置。

## 参考实现

[HarnessEval-W](https://github.com/MirroS-Lab/HarnessEval-W) 可作为后续 router 和能力模块设计的参考，尤其是：

- planner / plan validator 的两段式思路；
- 每个 skill 作为可插拔模块；
- 不同评分角色和证据处理。

本项目与它不同的重点是：

- 场景固定 EvalPlan 的跨仓库契约；
- 维度级异步队列；
- agent judge 与单人 human reviewer 的混合路径；
- 同一 Experiment 内多个 agent 的严格对比。

## 现有链路接缝

迁移旧链路时需要对齐：

- 原 scorer 契约：`score(...) -> [{dimension, value, detail}]`；
- 旧聚合：`evaluator._aggregate_total` 按 `meta.yaml` 的 `dimensions[*].weight` 加权；
- 旧异步队列：`backend/scoring_queue.py` 的 judge key、取消 hook 和执行/评分状态区分；
- 旧可追溯：`evaluator._scorer_manifest` 的 source hash。

新链路不直接覆盖旧 scorer 结果。旧结果标记为 `legacy`，新结果使用 `octagon-evals` 的 plan、dimension 和 scorer lineage。

## MVP 落地顺序

1. 场景固定 EvalPlan、schema 校验和 dimension 能力库；
2. `EvaluationInput` 接收与 DimensionTask 建立；
3. deterministic checker、单次 agent judge、单 reviewer human task；
4. DimensionScore lineage、幂等队列和加权平均；
5. 以 `frontend-vfx-volcano` 为首个样例，把源码正则评分迁移为成品/历史证据评分。

## 后续方向

待 MVP 运行并积累数据后，再考虑：

- task-specific plan variant 和 benchmark profile；
- observation cap；
- agent judge 校准、多人评审和 reviewer 一致性；
- 离线 replay、复杂统计报告和跨 Experiment 汇总；
- 更完整的 evidence contract、安全边界和来源泄漏审计。
