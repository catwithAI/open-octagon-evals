# pi Agent-as-a-Judge 使用与协议

本文说明如何安装、启动和调用基于 `pi` 的 Agent-as-a-Judge 服务，以及服务的 HTTP 输入、输出和错误协议。

## 当前验收状态

当前实现可作为**单机、单进程 MVP**验收：

- `pi` 以独立子进程运行；
- Judge 通过 `read`、`bash` 工具主动读取证据工作区；
- 输出经过 JSON 解析和 `[0,1]` 分值校验；
- eval API 可以通过 `method: agent_judge_agentic` 调用 Judge 服务；
- 自动化测试不需要真实模型，当前全量测试为 56 项；
- 已使用本机 `pi 0.84.1` 完成真实端到端冒烟测试。

以下能力**不在当前验收范围**：

- 多 worker 或多实例的跨进程幂等；
- Judge task 的持久化去重；
- 进程崩溃后的自动恢复；
- 工具沙箱或不可信多租户隔离；
- 模型/provider SLA；
- 自动重试和多次采样。

当前重复 `task_id` 的保护保存在 Judge 进程内存中，只保证同一进程内已成功请求的后续顺序调用会被拒绝。服务重启后会丢失，多 worker 之间不共享，并发请求也可能在写入前同时通过检查。因此生产多实例部署前，需要改成持久化、原子去重。

## 架构

```text
调用方 / octagon-evals API
        │ POST /judge
        ▼
octagon-judge-service (FastAPI)
        │ 创建临时工作区
        │ 写 evidence.json + evidence/*
        ▼
pi --mode json --print --no-session
        │ cwd = 临时工作区
        │ tools = read,bash
        ▼
pi NDJSON 事件流
        │ 提取最终 assistant text
        │ 解析 JSON + 校验 value
        ▼
JudgeResponse
```

旧的 `method: agent_judge` 仍是 OpenAI-compatible 的单次 LLM 调用。新的 Agent-as-a-Judge 必须使用：

```yaml
method: agent_judge_agentic
```

## 前置条件

### Python

需要 Python 3.11 或更高版本：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

### pi CLI

`pi` 不是本项目的 Python 依赖，必须单独安装。当前实现已在 `pi 0.84.1` 验证；建议使用 `0.84.1` 或更新兼容版本。

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

也可以使用 pi 官方安装器：

```bash
curl -fsSL https://pi.dev/install.sh | sh
```

如果 `pi` 不在 `PATH`：

```bash
export OCTAGON_JUDGE_PI_BIN=/absolute/path/to/pi
```

### 配置 provider 和认证

可以交互式启动 `pi`，使用 `/login` 和 `/model` 选择 provider、认证方式及默认模型。部署和验收时建议显式指定 provider/model，避免不同机器读取到不同的全局默认配置：

```bash
export OCTAGON_JUDGE_PROVIDER=llm3
export OCTAGON_JUDGE_MODEL=deepseek-4-flash

pi auth check \
  --provider "$OCTAGON_JUDGE_PROVIDER" \
  --model "$OCTAGON_JUDGE_MODEL" \
  --json
```

成功示例：

```json
{"status":"ready","provider":"llm3","authType":"api_key"}
```

不设置 `OCTAGON_JUDGE_PROVIDER` / `OCTAGON_JUDGE_MODEL` 时，服务不传 `--provider` 和 `--model`，由 pi 的当前默认配置决定。此时请先手工运行一次：

```bash
pi --mode json --print --no-session --thinking off "reply with exactly: OK"
```

模型/provider 属于外部服务，可能出现限流、长尾延迟或暂时不可用。Judge 有硬超时保护，但不自动重试，避免违反“每维度只采样一次”的评测约束。

## 启动

### 启动完整项目

```bash
./start.sh
```

默认启动：

| 服务 | 地址 |
|---|---|
| eval API | `http://127.0.0.1:8000` |
| pi Judge | `http://127.0.0.1:8001` |
| 控制台 | `http://127.0.0.1:5173` |

`start.sh` 会检查 Python 依赖、`pi` 是否存在，以及显式配置的 provider/model 是否已认证。如果端口被占用，会在附近选择空闲端口，并自动把实际 Judge 地址写入 `OCTAGON_JUDGE_SERVICE_URL` 后再启动 eval API。

### 只启动 Judge 服务

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn \
  octagon_evals.judge_service.app:judge_app \
  --host 127.0.0.1 \
  --port 8001
```

健康检查：

```bash
curl -sS http://127.0.0.1:8001/health
```

```json
{"status":"ok","pi_version":"0.84.1"}
```

`status: ok` 表示 FastAPI 服务可用，不代表 provider 当前一定能完成推理。provider readiness 应使用 `pi auth check` 验证。

## 配置

### Judge 服务

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `OCTAGON_JUDGE_PI_BIN` | `pi` | pi 可执行文件路径 |
| `OCTAGON_JUDGE_PROVIDER` | 未设置 | 传给 `pi --provider`；未设置时使用 pi 默认值 |
| `OCTAGON_JUDGE_MODEL` | 未设置 | 传给 `pi --model`；未设置时使用 pi 默认值 |
| `OCTAGON_JUDGE_PROMPT_VERSION` | `agentic-1` | 写入 score lineage 的 prompt 版本 |
| `OCTAGON_JUDGE_TIMEOUT` | `300` | 单次 pi 子进程硬超时，单位秒 |
| `OCTAGON_JUDGE_TOOLS` | `read,bash` | pi 工具白名单，逗号分隔 |
| `OCTAGON_JUDGE_THINKING` | `off` | 传给 `pi --thinking` |
| `OCTAGON_JUDGE_WORKSPACE_BASE` | 系统临时目录 | Judge 临时工作区父目录 |
| `OCTAGON_JUDGE_HOST` | `127.0.0.1` | `start.sh` 中 Judge 监听地址 |
| `OCTAGON_JUDGE_PORT` | `8001` | `start.sh` 中 Judge 监听端口 |

### eval API 到 Judge 服务

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `OCTAGON_JUDGE_SERVICE_URL` | `http://127.0.0.1:8001` | eval API 调用的 Judge 基地址 |
| `OCTAGON_JUDGE_CLIENT_TIMEOUT` | `330` | HTTP 客户端超时，必须大于 Judge 子进程超时 |

如果修改 `OCTAGON_JUDGE_TIMEOUT`，应同时保证：

```text
OCTAGON_JUDGE_CLIENT_TIMEOUT > OCTAGON_JUDGE_TIMEOUT
```

建议至少保留 30 秒网络和清理余量。

## HTTP 协议

### `POST /judge`

请求体：

```json
{
  "task_id": "run-1:plan-hash:quality",
  "dimension_question": "Does the evidence support that hello.txt was created?",
  "anchors": [
    {
      "id": "created",
      "pass_if": "clear evidence shows hello.txt was created",
      "fail_if": "evidence is missing or shows it was not created"
    }
  ],
  "output_schema": {
    "type": "object",
    "required": ["value", "reason", "raw"],
    "value_range": [0, 1]
  },
  "evidence": {
    "workspace_log": "10:00 create file hello.txt; 10:01 wrote 'hi'",
    "final_state": {
      "hello.txt": {"exists": true, "content": "hi"}
    }
  },
  "lineage": {
    "plan_hash": "sha256:...",
    "dimension_version": 1
  }
}
```

字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | string | 是 | Judge 去重键；一次成功后同进程内不可再次评分 |
| `dimension_question` | string | 是 | 单一评分问题 |
| `anchors` | array<object> | 否 | 评分锚点，默认空数组 |
| `output_schema` | object | 否 | 期望输出约束；默认要求 `value/reason/raw` |
| `evidence` | object | 是 | 将被物化到临时工作区的证据 |
| `lineage` | object | 否 | 调用方血统字段，服务会追加/覆盖 Judge 自身字段 |

成功响应：

```json
{
  "task_id": "run-1:plan-hash:quality",
  "value": 1.0,
  "reason": "The workspace log and final state both show hello.txt was created.",
  "raw": {
    "workspace_log": "pass",
    "final_state": "pass"
  },
  "source": "agent_judge_agentic",
  "lineage": {
    "plan_hash": "sha256:...",
    "dimension_version": 1,
    "provider": "llm3",
    "model": "deepseek-4-flash",
    "prompt_version": "agentic-1",
    "judge_service_version": "0.1.0",
    "pi_version": "0.84.1"
  }
}
```

输出约束：

- `value` 是唯一强制解析和范围校验的 Judge 内容字段，必须是有限数字且位于 `[0,1]`；
- `reason` 和 `raw` 在协议中推荐提供，但当前响应模型允许为 `null`；
- `source` 固定为 `agent_judge_agentic`；
- 服务字段 `provider`、`model`、`prompt_version`、`judge_service_version`、`pi_version` 会覆盖请求 lineage 中的同名字段；
- 未显式配置 provider/model 时，lineage 记录 `pi-default`，表示使用 pi 默认配置，不代表实际模型名就是该字符串。

调用示例：

```bash
curl -sS -X POST http://127.0.0.1:8001/judge \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "demo-quality-1",
    "dimension_question": "Does the evidence support that hello.txt was created?",
    "anchors": [{
      "id": "created",
      "pass_if": "clear evidence shows hello.txt was created",
      "fail_if": "no evidence or contrary evidence"
    }],
    "evidence": {
      "workspace_log": "created hello.txt",
      "final_state": {"hello.txt": {"exists": true}}
    }
  }'
```

### 错误响应

| 状态码 | 场景 |
|---:|---|
| `200` | 评分成功 |
| `409` | 当前 Judge 进程已成功处理过相同 `task_id` |
| `422` | 请求 schema 非法、pi 超时/启动失败/非零退出、没有最终 assistant 文本、Judge 输出无法解析或 `value` 非法 |
| `500` | 未归类的服务端错误，例如临时目录或文件系统失败 |

失败不会把 `task_id` 写入已评分集合，因此技术故障后可以由上层重试；成功后重复调用返回 409。

### `GET /health`

```json
{"status":"ok","pi_version":"0.84.1"}
```

## Agent 实际收到什么

### System prompt

```text
You are an evaluation judge. Read the evidence files in the current directory if you need to, then answer with a single JSON object with keys value, reason, raw. value is a finite number in [0,1]. Do not explore further than necessary.
```

### User prompt

服务将请求转换为 JSON 文本：

```json
{
  "instruction": "The evidence files are in the current directory (evidence.json and the evidence/ folder). Read them if you need to, then reply with the JSON verdict.",
  "question": "Does the evidence support that hello.txt was created?",
  "anchors": [],
  "output_schema": {
    "type": "object",
    "required": ["value", "reason", "raw"],
    "value_range": [0, 1]
  },
  "evidence_location": "evidence.json (full) and evidence/ (per-key files)"
}
```

### 工作区

`evidence` 被写成：

```text
/tmp/octagon-judge-XXXXXX/
├── evidence.json
└── evidence/
    ├── workspace_log
    └── final_state
```

`evidence.json` 保留完整结构；`evidence/` 下每个顶层键单独写一个文件，便于 Judge 按需读取。文件名只保留字母、数字和 `-_.`，其余字符替换为 `_`；清洗后重名时追加 `_2`、`_3` 后缀。请求结束后工作区在 `finally` 中删除。

### pi 命令

默认形态：

```bash
pi --mode json --print --no-session \
  --thinking off \
  --tools read,bash \
  --system-prompt '<system prompt>' \
  '<user prompt JSON>'
```

pi 的 cwd 是临时工作区。服务解析 pi 的 NDJSON stdout：优先从最后一个 `agent_end` 事件中取最后一条 assistant 文本；缺少 `agent_end` 时退回最后一个 `turn_end`。thinking、tool call 和中间消息不会被当作最终裁决。

## 在 eval API 中使用

创建 EvalPlan 时把维度声明为：

```json
{
  "id": "quality",
  "role": "scored",
  "weight": 1.0,
  "method": "agent_judge_agentic",
  "question": "Does the evidence support the required outcome?",
  "anchors": [
    {
      "id": "complete",
      "pass_if": "direct evidence proves the outcome",
      "fail_if": "evidence is missing or contradictory"
    }
  ],
  "output_schema": {
    "type": "object",
    "required": ["value", "reason", "raw"]
  }
}
```

之后仍使用统一的评分入口：

```bash
curl -sS -X POST "$API/tasks/$TASK_ID/score" \
  -H 'Content-Type: application/json' \
  -d '{"evidence":{"artifact":"...","final_state":{"ok":true}}}'
```

eval API 会调用 `OCTAGON_JUDGE_SERVICE_URL/judge`，保存 `DimensionScore`，再参与总分聚合。

## 测试与验收

安装开发依赖并运行：

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

当前 pi Judge 新模块的行覆盖率为 96%（219 statements，9 missed）：`config.py`、`models.py`、`workspace.py`、`agent_judge_client.py` 为 100%，`app.py` 为 96%，`pi_runner.py` 为 91%。覆盖率用于识别未执行代码，不等价于真实 provider 的可靠性或评分准确率。

当前覆盖：

- pi 命令参数：JSON 模式、非交互、无 session、工具白名单、provider/model/thinking；
- NDJSON：`agent_end`、`turn_end` 回退、多轮工具调用后的最终 assistant 文本；
- pi 空输出、非零退出、超时；
- Judge 纯 JSON、markdown fence、不可解析输出；
- `/judge` 成功、重复 task、临时工作区清理、`/health`；
- eval API → AgentJudgeClient → score 存储 → total score 的集成链路；
- 每维度只调用一次。

当前未覆盖：

- 外部 provider 的稳定性、限流和 SLA；
- 真实网络下 eval API 到 Judge 的连接超时/断连；
- `pi` 缺失、认证失败的自动化启动脚本测试；
- 多进程并发提交同一 `task_id`；
- 重启后的幂等；
- `bash` 工具的操作系统级隔离；
- 不同 pi 版本的 NDJSON 兼容矩阵。

验收建议：

```bash
pi --version
pi auth check --provider "$OCTAGON_JUDGE_PROVIDER" --model "$OCTAGON_JUDGE_MODEL" --json
.venv/bin/python -m pytest -q
./start.sh
curl -sS http://127.0.0.1:8001/health
```

再使用唯一 `task_id` 调一次 `POST /judge`。由于真实 provider 可能出现长尾延迟，验收应分别记录代码测试结果和外部 provider 冒烟结果，不能把 provider 波动误判为协议或解析代码失败。

## 安全边界

默认工具是 `read,bash`。`bash` 不是沙箱：虽然 cwd 指向临时工作区，但子进程仍以 Judge 服务用户身份运行，理论上可以读取工作区外可访问的宿主机文件。当前配置只适合受信任环境和受控证据。

对不可信多租户开放前，应把 Judge 放入容器或受限 sandbox，并限制：

- 文件系统挂载；
- 网络访问；
- 环境变量和凭据；
- 进程权限与资源上限；
- 可用工具集合。
