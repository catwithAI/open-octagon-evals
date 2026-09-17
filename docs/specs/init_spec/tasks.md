# init_spec tasks：MVP 评分层实现与单测

本文件是 `octagon-evals` 第一个 spec 的执行清单。它只讨论如何把现有文档中的 MVP
设计落实到代码和测试；需求背景、架构取舍分别以仓库根目录的 `README.md`、`agent.md`
和 `docs/*.md` 为准。

MVP 主链路（模型 → plan 校验 → 任务队列 → deterministic 评分 → 按 run 聚合 → FastAPI）
已实现并有测试覆盖；勾选状态以代码实际情况为准。实现时应保持模块职责清晰，
避免把 `open-agent-octagon` 的执行、调度或故障归因逻辑复制到本仓库。

## 1. 基础目录与公共模型

建议新增：

- `src/octagon_evals/models/`：Experiment、AgentRun、EvaluationInput、EvalPlan、Dimension、
  DimensionTask、DimensionScore、HumanTask 等模型。
- `src/octagon_evals/schemas/`：输入和评分输出的结构化 schema；统一校验错误类型。
- `src/octagon_evals/errors.py`：invalid input、invalid judge output、plan incompatibility、
  stale submission 等领域错误。
- `tests/unit/models/`、`tests/unit/schemas/`：公共模型和 schema 单测。

实现任务：

- [x] 为 `EvaluationInput` 建立不可变快照模型，覆盖 experiment/run/scenario/task、artifact、
  history 和 `run_status.upstream_completed`。
- [x] 明确必需字段、引用格式和 content/evidence hash 校验；缺失或损坏输入只能得到
  `invalid`，不能生成分数。
- [ ] 为 dimension 定义稳定 ID、版本、评价问题、观察标准、分值锚点、evidence contract、
  method、输出 schema 和 scorer version。
- [x] 为所有 normalized value 建立 `[0, 1]` 校验器，并保留 raw、reason、evidence refs。
- [x] 为 DimensionTask 定义唯一逻辑键：`run_id + plan_hash + dimension_id`。

单测：

- [ ] 合法/缺字段/坏引用/坏 hash 的 `EvaluationInput` 校验。
- [ ] value 为负数、超过 1、NaN、字符串、缺失时均被拒绝。
- [ ] 相同输入生成等价模型和稳定任务键；不同 run、plan 或 dimension 不冲突。
- [ ] 失败的上游 run（但 `upstream_completed=true`）仍可作为合法评分输入。

## 2. EvalPlan 加载、校验与冻结

建议新增：

- `src/octagon_evals/plan/loader.py`
- `src/octagon_evals/plan/validator.py`
- `src/octagon_evals/plan/hash.py`
- `tests/unit/plan/`

实现任务：

- [x] 从场景 `meta.yaml` 或独立 plan 文件读取 `schema_version`、plan version 和 dimensions。
- [x] 校验 dimension ID 存在且唯一、role 仅为 `scored`/`diagnostic`、weight 为有限非负数、
  scored 权重总和大于零，以及 method 与能力实现/输出 schema 匹配。
- [x] 将规范化后的 plan 序列化后计算稳定 `plan_hash`，并持久化 scenario/version、plan/version
  与 hash。
- [x] 在 Experiment 创建前完成加载和冻结；禁止同一 Experiment 使用不同 plan_hash
  （API 层校验，混入不同 hash 返回 409）。
- [ ] 计划或能力实现发生影响评分的变化时创建新版本，不修改历史计划。

单测：

- [x] 合法示例 plan 可加载并产生稳定 hash（hash 序列化 sort_keys，字段顺序无关）。
- [ ] 未知/重复 dimension、非法 role、负权重、非有限权重、全 diagnostic、method 不匹配均
  在 agent 执行前失败（校验逻辑已实现，测试只覆盖了全 diagnostic 一种）。
- [x] 相同 Experiment 接受相同 hash，混入不同 hash 被拒绝。
- [ ] plan 内容或版本改变会产生不同 hash，旧实例仍可读取。

## 3. DimensionTask 创建与可靠队列

建议新增：

- `src/octagon_evals/tasks/service.py`
- `src/octagon_evals/tasks/state.py`
- `src/octagon_evals/queue/lease.py`
- `src/octagon_evals/queue/idempotency.py`
- `tests/unit/tasks/`、`tests/unit/queue/`

实现任务：

- [x] 接收一个已校验的 EvaluationInput 和冻结的 EvalPlan，为每个适用 scored/human_required
  维度建立一个 DimensionTask；diagnostic 是否建任务按产品实现约定保存但不得计分。
- [x] 实现 `queued → claimed → completed` 及 `retrying/failed/cancelled` 状态迁移，并拒绝
  非法迁移。
- [x] claim 返回带过期时间的 lease；lease 过期可重新入队，技术失败按有限次数重试。
- [x] 所有写入按逻辑任务键幂等；已 resolved 的结果不可被重复或迟到提交覆盖
  （内存 setdefault + SQLite `one_resolved_score` 唯一索引）。
- [x] 取消或评分封口后拒绝迟到结果（`StaleSubmission`）；上游 run 失败不自动转成 eval_failed。

单测：

- [ ] N 个 AgentRun 各自生成 M 个维度任务，任务不跨 run、不跨 dimension。
- [x] 重复创建/重复提交只保留一个逻辑任务和一个 resolved 结果。
- [ ] lease 未过期不可重复 claim，过期后可重新 claim；重试耗尽进入 failed/incomplete。
- [ ] 取消、封口、迟到结果和非法状态迁移均有明确失败断言。

## 4. Scorer 执行器与结果血统

建议新增：

- `src/octagon_evals/scorers/base.py`
- `src/octagon_evals/scorers/deterministic.py`
- `src/octagon_evals/scorers/agent_judge.py`
- `src/octagon_evals/scorers/human.py`
- `src/octagon_evals/scores/service.py`
- `tests/unit/scorers/`、`tests/unit/scores/`

实现任务：

- [x] 通过 dimension method 路由到 deterministic checker、单次 agent judge 或 human task。
- [x] `agent_judge_agentic` 通过独立 HTTP 服务驱动 pi，provider/model 可配置，默认沿用 pi 当前默认；每个维度只调用一次；confidence 只
  作为诊断字段，不触发 human 升级。
- [x] 校验 judge/human 的结构化输出；invalid output 进入 invalid-output/eval-failed 流程，
  不猜分、不补零。
- [x] 分离保存 proposal、reviews、resolved；MVP human task 只允许一个 reviewer。
- [ ] 写入 scorer version、source hash、prompt/model、scenario/plan/dimension version 和
  evidence hashes，禁止覆盖旧结果。

单测：

- [ ] 三种 method 都能生成正确任务/结果类型；diagnostic 结果可保存但不进入总分。
- [x] scorer 调用次数严格为一次；重复 worker 不重复采样（runner 层通用保证，handler
  技术失败未采样时可重试；agent judge 本身待实现）。
- [ ] 合法结构化输出被归一化保存；缺失、越界、不可解析输出不会产生 DimensionScore。
- [ ] human 提交按 task_id 幂等，前端伪造 run/dimension/evidence 来源字段会被忽略或拒绝。
- [ ] 新 scorer/prompt/model/plan 生成新 lineage，旧结果仍可查询且标记为 legacy（如适用）。

## 5. Human task 与 Feishu 适配器

建议新增：

- `src/octagon_evals/human/service.py`
- `src/octagon_evals/human/ports.py`
- `src/octagon_evals/adapters/feishu.py`
- `tests/unit/human/`、`tests/unit/adapters/`

实现任务：

- [x] 创建、分派、超时和重新分派 human task；每个 task 暂时只绑定一个 reviewer。
- [ ] 将 evidence contract 和评分表单传给 reviewer，但服务端根据 task_id 加载真实 run、
  dimension 与 evidence，不信任客户端来源字段。
- [ ] Feishu 仅实现通知/提交端口；不可用时 human task 保持 pending，不产生错误分数。

单测：

- [ ] 创建和一次提交成功；重复提交保持幂等。
- [ ] 超时后可重新分派；不自动改用 agent judge。
- [ ] Feishu 发送失败不改变评分结果状态；伪造 task payload 被拒绝。

## 6. 聚合与评分状态

建议新增：

- `src/octagon_evals/aggregation/service.py`
- `src/octagon_evals/aggregation/status.py`
- `tests/unit/aggregation/`

实现任务：

- [x] 仅使用 resolved 的 scored DimensionScore 计算
  `Σ(value × weight) / Σ(scored_weight)`。
- [x] 任一 scored 维度未 resolved 时返回 `total_score=null` 和 pending。
- [ ] 全部 resolved 后返回 final 和 `[0,1]` 总分；incomplete、invalid、eval_failed、cancelled
  不进入正式排名（pending/final 已实现，其余四个结果状态缺失）。
- [ ] 聚合使用的 plan_hash、score IDs 和计算时间写入结果快照；重新聚合不覆盖原评分。

单测：

- [x] 加权平均数值正确，diagnostic 永不影响结果。
- [x] 缺失维度不被当成零分，也不临时重归一化。
- [ ] 从 pending 到 final 的状态转换，以及 incomplete/invalid/eval_failed/cancelled 的边界。
- [ ] 重复聚合幂等；更换 plan 或 score 版本产生新聚合记录。

## 7. 端到端验收与首个迁移样例

建议新增：

- `tests/integration/test_evaluation_pipeline.py`
- `tests/fixtures/evaluation_input/`
- `tests/fixtures/plans/frontend-vfx-volcano.yaml`

实现任务：

- [x] 用固定 plan 和一个成功封口的 EvaluationInput 跑通：加载 plan → 建任务 → 评分 → 聚合。
- [x] 用 `frontend-vfx-volcano` fixture 覆盖 artifact/history evidence；不使用跨 run evidence。
- [x] 使用 49 上真实已完成 attempt（`run_b655bde479aa`/`att_77d42647a079`）验证上游封口 run 的 EvaluationInput 映射与本地 deterministic 评分。
- [ ] 补齐上游 task 失败但已封口、缺 artifact、judge invalid、human pending、重复投递和取消的 fixture。
- [ ] 为旧 `scorer.py`/`_aggregate_total`/`_scorer_manifest` 的迁移保留 legacy 对照 fixture，
  新结果使用 octagon-evals lineage 且不覆盖旧结果。

完成标准：上述单元测试和端到端测试通过；同一 Experiment 的所有 run 共享 plan_hash，
总分只在全部 scored 维度 resolved 后产生，并且每个结果均可追溯到 scenario、plan、
dimension、scorer/judge 和 evidence 版本。

## 8. 读取 API 与前端对接

评分数据已可写入，但前端页面（实验列表、AgentRun 对比、维度评分详情、human 评审）
需要的读取端点尚未提供；`create_app` 里的 experiment→plan 映射也只存在内存字典，
重启即丢。建议新增：

- `src/octagon_evals/api.py` 读取端点扩展；
- `src/octagon_evals/db/sqlite.py` 增加 experiments 关联与按实验/run 查询；
- `tests/integration/test_api_read.py`。

实现任务：

- [x] `GET /experiments`：实验列表——基础状态、run 数、plan hash、创建时间。
- [ ] `GET /experiments`：补齐状态、维度进度、每 run 总分（未完成为
  null）、plan version/hash、创建时间。
- [ ] `GET /experiments/{id}`：实验详情——per-run × per-dimension 矩阵（resolved value、
  weight、method、diagnostic 标记）与每 run 聚合结果。
- [x] `GET /tasks/{task_id}`：返回任务状态、attempts 和已保存评分记录。
- [ ] `GET /tasks/{task_id}`：补齐 proposal/reviews/resolved、raw、reason、
  evidence refs、完整 lineage、任务状态与 attempts。
- [x] human task HTTP 端点：创建、分派、提交、超时；提交按 task_id/reviewer 校验并幂等。
  evidence，不信任客户端来源字段）、超时重新分派；与 Feishu 通知端口打通。
- [x] experiment→plan/run 映射持久化到 SQLite，服务重启后 score/task 读取端点仍可用。

单测：

- [ ] 列表/详情/维度详情端点的响应形状；未完成实验 `total_score = null`。
- [ ] human 提交端点幂等；reviewer 不匹配、任务已完成、任务不存在的错误路径。
- [ ] 重启进程后仍能通过 API 读取历史实验与分数。

## 9. 当前实现进度

- [x] SQLite schema 与事务封装：plans、dimension_tasks、dimension_scores、human_tasks。
- [x] SQLite 重启后读取 task/score 的集成测试。
- [x] TaskStore、ScoreStore 支持注入 SQLiteStore。
- [x] HumanTaskStore 接入 SQLiteStore，覆盖创建、分派、提交和超时状态。
- [x] Feishu 客户端适配器骨架；凭据从 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 运行时读取。
- [x] 增加首批 deterministic 能力库（task completion、functional requirements、dangerous action confirmation）。
- [x] 增加 EvaluationService 编排层和 deterministic worker。
- [x] FastAPI MVP API：启动 run、提交 deterministic evidence、查询 experiment score。
- [x] OpenAgentOctagon 只读 client：实验、run、attempt 查询及 EvaluationInput 映射。
- [x] 聚合按 run 拆分：experiment score 返回每个 run 独立的聚合结果（修复跨 run 分数混淆）。
- [x] API 拒绝同一实验混入不同 plan_hash 的 run（409）。
- [x] scorer 重试解锁：handler 技术失败未采样时可重跑，成功采样仍严格一次。
- [ ] 并发压力测试和独立 worker 进程化。
