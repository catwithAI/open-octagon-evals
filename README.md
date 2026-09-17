# open-octagon-evals

Agent Octagon 的评分层独立仓库。Python 包名保持为 `octagon-evals`，导入名为 `octagon_evals`。

本仓库接收 `open-agent-octagon` 已完成采集的单次 agent run（最终产物、trajectory、actions 等历史），把它拆成维度级评分任务，交给 deterministic checker、agent judge 或 human reviewer，最后生成该 run 的总分。

它不负责运行 agent、调度场景、判断模型/agent/环境故障归因，也不负责创建场景。相关职责属于上游仓库：

| 仓库 | 职责 |
|---|---|
| [`open-agent-octagon`](https://github.com/catwithAI/open-agent-octagon) | 场景调度、agent 执行、观测和运行历史采集 |
| [`agent-octagon-envs`](https://github.com/blade-hq/agent-octagon-envs) | 场景、任务和固定 EvalPlan |
| `octagon-evals` | 维度评分、human task、聚合和评分血统 |

## 当前状态

单次评分 MVP 已可运行（公共模型、固定 EvalPlan 校验、SQLite 持久化、任务幂等存储、
deterministic/agent-judge/human 评分入口、评分解析和聚合均已接通）；独立持久化 worker、
重复评分可靠性统计和更完整的外部适配器仍在后续任务中。MVP 的
关键取舍已经确定：

- 一个 Experiment 包含 N 个 agent 分别跑同一个 task；
- 一个评分任务只对应一个 AgentRun 和一个维度；
- 同一 Experiment 的所有 AgentRun 共享场景固定的 EvalPlan；
- 每个 agent judge 维度只调用一次；
- human 只处理场景预先声明的 `human_required` 维度，不做 agent 低置信度升级；
- 所有 scored 维度直接按权重加权平均，未完成前总分显示待定；
- scorer、prompt、model、plan 和 scenario 都必须可版本化，旧结果不可覆盖；
- 跨 Experiment 不要求 plan 完全一致，但跨实验综合排名暂不属于 MVP。

## 快速开始

### 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

如果要使用 `method: agent_judge_agentic`，还需单独安装并认证 `pi` CLI（当前验证版本：`0.84.1`）：

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
pi  # 首次运行时使用 /login 和 /model 配置 provider/model
```

详细配置、直接调用示例和 HTTP 协议见 [`docs/pi-judge.md`](docs/pi-judge.md)。

### 启动 API 和控制台

```bash
./start.sh
```

默认会启动 API（`http://127.0.0.1:8000`）、pi Judge（`http://127.0.0.1:8001`）、静态控制台（`http://127.0.0.1:5173`）和 SQLite 数据库（`data/octagon-evals.db`）。如果默认端口被占用，脚本会自动选择附近的空闲端口，并打印实际访问地址。

```bash
OCTAGON_EVALS_PORT=8030 \
OCTAGON_EVALS_WEB_PORT=5180 \
OCTAGON_EVALS_DB=./data/local.db \
./start.sh
```

### 配置 Judge

本仓库有两条 Judge 路径：

- `agent_judge`：旧的单次 OpenAI-compatible Chat Completions 调用；
- `agent_judge_agentic`：独立 pi Agent-as-a-Judge 服务，Judge 使用工具读取工作区证据。

旧的 `agent_judge` 配置如下。不要把 key 写入仓库或提交到 Git：

```bash
export OCTAGON_JUDGE_ENDPOINT="https://your-llm-endpoint/v1/chat/completions"
export OCTAGON_JUDGE_MODEL="your-judge-model"
export OCTAGON_JUDGE_API_KEY="your-api-key"
export OCTAGON_JUDGE_PROMPT_VERSION="1"
./start.sh
```

Judge 必须返回 JSON，且 `value` 必须是 `[0, 1]` 内的数字：

```json
{
  "value": 0.75,
  "reason": "主要流程完成，但缺少一个必要反馈",
  "raw": {"checks": {"feedback": "pass", "error_copy": "fail"}}
}
```

每个 `(run_id, dimension_id)` 评分任务最多调用一次 Judge。

pi Agent-as-a-Judge 推荐显式配置 provider/model，并保证客户端超时大于 Judge 子进程超时：

```bash
export OCTAGON_JUDGE_PROVIDER=llm3
export OCTAGON_JUDGE_MODEL=deepseek-4-flash
export OCTAGON_JUDGE_TIMEOUT=300
export OCTAGON_JUDGE_CLIENT_TIMEOUT=330
pi auth check --provider "$OCTAGON_JUDGE_PROVIDER" --model "$OCTAGON_JUDGE_MODEL" --json
./start.sh
```

完整安装、配置、安全边界及 `POST /judge` 输入输出协议见 [`docs/pi-judge.md`](docs/pi-judge.md)。

## 执行一次评分

一次评分由三个步骤组成：创建 run（同时创建维度任务）、逐个提交 evidence 评分、读取聚合结果。

### 1. 创建 run 和 EvalPlan

同一 Experiment 的所有 run 必须使用同一个 EvalPlan。第一次创建时，服务会校验并生成 `plan_hash`；后续 run 使用不同 plan 会被拒绝。

```bash
API=http://127.0.0.1:8000

curl -sS -X POST "$API/experiments/demo-e1/runs" \
  -H 'Content-Type: application/json' \
  -d '{
    "run_id": "run-agent-a-001",
    "producer": {
      "agent_id": "agent-a",
      "agent_version": "v1",
      "model_id": "model-x",
      "skill_set": "skills-v2"
    },
    "scenario": {"id": "checkout", "version": 1},
    "task": {"id": "checkout-001", "prompt": "完成结账流程"},
    "artifact": {
      "snapshot_ref": "s3://runs/run-agent-a-001/final.json",
      "content_hash": "sha256:replace-with-real-hash"
    },
    "history": {"trajectory_ref": "s3://runs/run-agent-a-001/trajectory.jsonl"},
    "dimensions": [
      {
        "id": "task_completion",
        "role": "scored",
        "weight": 0.6,
        "method": "deterministic"
      },
      {
        "id": "interaction_quality",
        "role": "scored",
        "weight": 0.4,
        "method": "agent_judge_agentic",
        "question": "最终产物是否清晰、完整、无误导？",
        "anchors": [
          {"id": "clarity", "pass_if": "有清晰状态反馈", "fail_if": "状态不可理解"},
          {"id": "error_guidance", "pass_if": "错误时提供可执行引导", "fail_if": "只有错误标记而无引导"}
        ],
        "output_schema": {
          "type": "object",
          "required": ["value", "reason", "raw"]
        }
      }
    ]
  }'
```

响应中的 `task_ids` 是接下来评分时使用的唯一 ID。

### 2. 提交 evidence 并评分

```bash
TASK_ID='把上一步响应中的 task_id 放在这里'

curl -sS -X POST "$API/tasks/$TASK_ID/score" \
  -H 'Content-Type: application/json' \
  -d '{
    "evidence": {
      "artifact": {"snapshot_ref": "s3://runs/run-agent-a-001/final.json"},
      "candidate_output": "上游 agent 的最终产物或摘要",
      "trajectory": "s3://runs/run-agent-a-001/trajectory.jsonl"
    }
  }'
```

`deterministic`、`agent_judge` 和 `agent_judge_agentic` 都使用这个入口；`human_required` 任务会返回需要人工评审的冲突提示，不会自动改走 Judge。

### 3. 查看评分和实验状态

```bash
curl -sS "$API/experiments"
curl -sS "$API/experiments/demo-e1"
curl -sS "$API/experiments/demo-e1/score"
curl -sS "$API/tasks/$TASK_ID"
```

只有所有 `scored` 维度都完成后，run 才会变成 `final` 并生成 `total_score`：

```text
total_score = Σ(dimension_score × weight) / Σ(weight)
```

`diagnostic` 维度会保存但不参与总分。

## 文档

- [`agent.md`](agent.md)：给参与实现的 agent/开发者看的仓库工作约定和 MVP 边界。
- [`docs/architecture.md`](docs/architecture.md)：组件边界、对象层级、评分生命周期和任务状态。
- [`docs/scoring.md`](docs/scoring.md)：能力库、维度定义、输出格式、聚合和评分血统。
- [`docs/integration.md`](docs/integration.md)：与上游仓库的交付边界、EvaluationInput 和 human/Feishu 接口原则。
- [`docs/decisions.md`](docs/decisions.md)：已确认的设计决策与明确延期的事项。
- [`docs/context.md`](docs/context.md)：拆分背景、参考实现、现有链路接缝和落地路线。
- [`docs/glossary.md`](docs/glossary.md)：术语说明表，统一评测讨论中的对象、证据、rubric、judge、Gold、benchmark 与闭环用词。
- [`docs/pi-judge.md`](docs/pi-judge.md)：pi Agent-as-a-Judge 的安装、启动、配置、HTTP 输入输出协议、测试和安全边界。
- [`docs/scenario-spec.md`](docs/scenario-spec.md)：场景契约 v2 草案，定义新建场景的目录、维度字段、扣分码、封顶、证据契约、探针与认证要求；样例见 [`docs/scenarios/doc-tour-pl-memo/meta.yaml`](docs/scenarios/doc-tour-pl-memo/meta.yaml)。
- [`docs/review-representative-envs.md`](docs/review-representative-envs.md)：11 个代表场景与契约 v2 的逐项差距、迁移分档和契约需修订点。
- [`web/`](web/)：基于 `docs/specs/init_spec/design/` 原型图的静态控制台前端。

## 设计原则

1. **先保证同一 Experiment 内可比。** 同一 task 的所有 agent 使用同一份固定 plan、证据契约和评分配置。
2. **评分以维度分为本源。** total score 是派生值；每个维度保留 raw result、resolved value、证据和 scorer lineage。
3. **评分层不归因上游故障。** eval 只接受上游封口的历史快照；产物完成得差是评分结果，不是 eval 的故障分类。
4. **组件通过契约交互。** 场景定义评什么，eval 实现怎么评，上游提供评测输入。

## 重复评估同一个产物

为了测量 Judge 自一致性，不要复用 `run_id`。对同一个 artifact 创建多个 run，并保持以下内容不变：

- `scenario` 和 `EvalPlan`；
- artifact 的 `content_hash`；
- dimension 的 question、anchors、权重和 scorer 版本；
- Judge model、prompt version 和请求参数。

每个 run 使用新的 `run_id`，完成后从 `/experiments/{experiment_id}/score` 收集总分，计算均值、总体标准差、范围和中位数。当前 MVP 保存每个维度的原始 Judge 输出，统计汇总暂由调用方计算。

## Human 评审

对于 plan 中声明为 `human_required` 的维度：

```bash
curl -X POST "$API/human-tasks/$TASK_ID"
curl -X POST "$API/human-tasks/$TASK_ID/assign?reviewer_id=reviewer-1"
curl -X POST "$API/human-tasks/$TASK_ID/submit" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer_id":"reviewer-1","value":0.75,"reason":"主流程完成，错误引导不足"}'
```

提交按 `task_id` 幂等；同一个任务重复提交不会覆盖已经 resolved 的分数。

## Feishu demo

`demo/feishu_chat_eval/` 包含一个使用合成聊天上下文的完整样例，不包含真实聊天记录或用户信息；样例中的数值仅用于演示：

- `cases.json`：任务、gold 要求和聊天上下文；
- `outputs_good.json` / `outputs_bad.json`：待评估的候选方案；
- `octagon_plan.json`：结构化 Judge rubric（anchors、pass/fail 标准和输出 schema）；
- `feishu_chat_case.py`：AgentEval 的确定性 RuleSkill 版本。

如果本机同时有 `../AgentEval`，可以运行确定性对照：

```bash
PYTHONPATH=../AgentEval/src:demo/feishu_chat_eval \
python -m agenteval.cli eval \
  --cases demo/feishu_chat_eval/cases.json \
  --outputs demo/feishu_chat_eval/outputs_good.json \
  --case-package feishu_chat_case \
  --run-root demo/feishu_chat_eval/runs/good
```

真正的 `agent_judge` 评估应通过上面的 HTTP API 提交 `method=agent_judge` 的 EvalPlan，并为每个重复 run 提交同一份 evidence。

## 开发和测试

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

当前测试覆盖 plan 校验、SQLite 持久化、任务状态、评分幂等、Judge 结构化输出、Human task 和控制台跨端口 CORS。
