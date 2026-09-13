# 代表场景集与场景契约 v2 的差距评审

对象：`agent-octagon-representative-envs`（11 个场景，从 `agent-octagon-envs` 抽取，未改实现）
基准：[`scenario-spec.md`](scenario-spec.md) 草案
日期：2026-09-10

---

## 1. 总体结论

这 11 个场景选得好，覆盖了 PPT、Word、Excel、编程四类产物，每个都有真实来源和明确的"考什么"。但它们是按 v1 契约写的，和 v2 的差距不在场景质量，而在**评分逻辑的位置**：v1 把"评什么"和"怎么评"都放在场景的 Python 里，v2 要求"评什么"是数据、"怎么评"由评分层执行。

按迁移难度分三档：

| 档 | 场景 | 差距性质 |
|---|---|---|
| **A 直接可转** | odysseybench-revenue-report、gdpval-conflict-resolution-v2、swebench-django、swebench-pylint、airspace-monitoring | 已是 deterministic，检查项已经是二元断言，只缺结构化元数据和探针 |
| **B 需拆 judge** | gdpval-source-faithfulness-official、gdpval-prepaid-amortization-official、presentbench-education-official | rubric 已有且是人写的，但几十条塞进一次 judge 调用，且 judge 在沙箱里自己读文件 |
| **C 结构性不兼容** | ppt-visual-repair、visitor-appointment、document-review-formatting | judge 需要跑产品、点界面、看截图。v2 里 judge 只读证据，不执行 |

A 档五个场景改元数据就能进 v2。B 档三个需要把 rubric 分流并加渲染器。C 档三个需要上游先把"运行产品并采集截图、交互日志"变成证据采集步骤，judge 才能退回只读角色。

---

## 2. 逐项对照

契约十项要求，逐场景标记：✅ 符合、◐ 部分、✗ 不符、— 不适用。

| 要求 | odyssey | conflict | swe-django | swe-pylint | airspace | gdpval-sf | gdpval-pa | presentbench | ppt-repair | visitor | doc-review |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 维度十字段（question / criteria / anchors / evidence / method / version …） | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ◐ | ◐ |
| 二元断言或离散锚点 | ✅ 隐含在代码 | ✅ 隐含在代码 | ✅ 隐含在代码 | ✅ 隐含在代码 | ✅ 隐含在代码 | ✅ rubric 二元 | ✅ rubric 二元 | ✅ checklist yes/no | ◐ 0/1/2 无锚点描述 | ◐ 扣分码 | ◐ 扣分码 |
| method 按维度分离 | ✅ 全 det | ✅ 全 det | ✅ det + trace | ✅ det + trace | ◐ det，但 scorer 引用 judge | ✗ 单维度 judge 权重 100 | ✗ 同左 | ✗ 一个总分 + 五个 w=0 | ◐ 两个 det 门槛 + 一个 judge 80 | ✗ 六维全走 judge | ✗ 六维全走 judge |
| 场景内无 judge 实现 | ✅ | ✅ | ✅ | ✅ | ✅ | ✗ judge_local.py | ✗ judge_local.py | ◐ 共享 .presentbench_shared | ✗ judge_local.py | ✗ judge_local.py + 子包 | ✗ judge_local.py + 子包 |
| judge 只读确定性渲染后的证据 | — | — | — | — | — | ✗ 沙箱内自读 xlsx | ✗ 同左 | ✗ 自读 pptx/pdf | ◐ 先渲 PNG 再看图 | ✗ 跑产品、点浏览器 | ✗ 同左 |
| judge 不读 agent 自述 | — | — | ✅ 只读命令与退出码 | ✅ 同左 | — | ◐ 未声明 | ◐ 未声明 | ◐ 未声明 | ◐ 读 design_notes | ◐ 读 README 与源码 | ◐ 同左 |
| rubric 独立文件、judge 与 human 共用 | — | — | — | — | — | ◐ official_rubric.json | ◐ 同左 | ◐ judge_prompt.json | ✗ 写在 prompt 里 | ✅ product_judge_rubric.json | ✅ 同左 |
| `private/expected` 与 checker 分离 | ◐ expected 写死在 scorer | ✅ expected_state.json | ✗ 用例写死在 scorer | ✗ 同左 | ✗ 同左 | — | — | — | — | — | — |
| `probes/` 产物探针 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ◐ 有 draft/clean 对 | ✗ | ✗ |
| judge 维度经过认证 | — | — | — | — | — | ✗ | ✗ | ✗ | ✗ | ✗ 有 JUDGE_TRUSTWORTHINESS.md 但非认证 | ✗ |

说明：

- "隐含在代码"指检查项确实是二元的，例如 odyssey 的 `Check(dimension, weight, passed, label)` 九条、conflict 的 15 条事实、swebench 的 6 正 6 反用例，只是没有以数据形式暴露。这类改起来最便宜。
- 三个 `user-programming` 场景 meta 里的 `mutations: {allowed: [baseline], forbidden: [...]}` 指的是**题面扰动**（同形字、空格、大小写、指令位置），和契约 v2 的 `probes/`（**产物探针**）是两个概念。契约已按第 5 节改名，`mutations` 字段在 v2 中保留原语义。

---

## 3. 按档说明

### A 档：改元数据即可

五个场景的共同特点是 scorer 已经把评分写成了"一组二元检查按维度加权"，正是契约 3.1 的二元判据形态。缺的是：

1. 把检查项从 Python 提到 `meta.yaml` 的 `anchors[]`，把期望值提到 `private/expected/`。odyssey 的 10 行期望表、swebench 的 12 个用例、airspace 的固定航迹和基地用例现在都硬编码在 scorer 里。
2. 补 `question / criteria / evidence / version`。
3. 造探针：拿一份正确产物改一处，例如 odyssey 多留一行低于阈值的年份、conflict 把一个该填 NULL 的事实填了数、swebench 把修复改成只特判样例。
4. 权重从 0 到 100 改为任意非负数，评分层归一。

两个 swebench 场景有一个值得注意的做法：`validation` 维度读 trace 里的命令和退出码，判断 agent 是否真的跑过 pytest。这是一个**确定性的轨迹检查器**，只看工具调用不看自述。契约 v2 应当把这种写法明确列为 `evidence: [trajectory]` 的 deterministic 用法，见第 5 节。

airspace-monitoring 的 scorer 引用了 judge 但实际六个维度全是隔离子进程调 `evaluate`，属于 A 档，只需清理引用。

### B 档：rubric 已有，需要分流和渲染

三个场景都带人写的、粒度到单条事实的 rubric（59 条、56 条、五组共 76 条），这是整个仓库里最贵的资产。差距有三处：

1. **一次调用评几十条。** 杨雨晨 9/1 的实验显示多条 rubric 一起给 judge 会让 judge 变严，9/2 复测又说差异不显著、依赖数据集。无论哪种结论，把 59 条捆成一个维度都让认证无法做，因为没法知道哪条不稳。v2 要求按维度拆开，至少拆成"结构、数值、格式"三组。
2. **大半条目可以不用 judge。** gdpval-sf 的 59 条里，"London 行 Combined Gross = 230,754"这类数值核对约四十条，可以走 deterministic checker；只有"formatting is clean and professional"这类留给 judge。presentbench 的"页数 21 到 35"、"每页子弹点不超过 6"也是程序能数的。
3. **judge 自己读文件。** `judge_local.py` 让 judge 在沙箱里用 openpyxl 读 xlsx、用 LibreOffice 渲 pptx。读文件的稳定性和评判能力无关，却混进了分数。v2 要求评分层用带版本的渲染器先转成文本。

迁移后，B 档三个场景会变成"deterministic 权重 0.6 以上、judge 权重 0.4 以下"的形态，和 [`scenarios/doc-tour-pl-memo/meta.yaml`](scenarios/doc-tour-pl-memo/meta.yaml) 一致。gdpval-sf 就是那个样例的原型，可以直接对照。

### C 档：judge 在执行，不在评判

三个场景的 judge 要做的事包括：按 README 启动产品、在浏览器里点提交和审核、截图、对比 draft 和 candidate 的渲染图。这在 v1 里是合理的，因为没有别的组件干这件事。在 v2 里这些是**证据采集**，属于上游 `open-agent-octagon` 的职责，judge 只读采集结果。

visitor-appointment 和 document-review-formatting 的 `product_judge_rubric.json` 其实已经把这一点想清楚了：`evidence_policy` 区分了 `source_review_required_for`、`runtime_required_for`、`browser_required_for`，`logic_check_policy` 给每个检查四种状态 `passed / failed / unavailable / not_attempted`，还写了"基础设施不可用不得覆盖源码证据"。这些是 v2 契约第 4.3 节"缺失与不适用分别表达"的具体实现，比契约草案写得细。

差距在于执行位置。迁移方案：

- 上游增加一个 `runtime_probe` 采集步骤：按 README 启动、执行固定的 16 项或 14 项 OBJ 检查脚本、保存截图和 HTTP 日志。这个脚本可以从现在的 judge 子包里抽出来。
- 采集结果作为 `evidence: [runtime_probe, screenshot, workspace_tree]` 交给评分层。
- OBJ 检查的 passed/failed 直接变成 deterministic 维度；judge 只处理 `ui_interface_quality` 这一个主观维度，输入是截图。
- ppt-visual-repair 同理：LibreOffice 渲染进上游采集，judge 只看三张 PNG，且 `draft / clean / candidate` 三元组天然就是探针，可以直接进 `probes/`。

不做这一步，C 档的 judge 分数里混着"产品能不能起来"、"浏览器工具有没有挂"、"judge 有没有点对按钮"三种和 agent 能力无关的噪声，认证不可能通过。

---

## 4. 同事做得好、契约应当吸收的地方

评审的目的不只是找差距。这 11 个场景里有几处设计比契约草案成熟，应当反向修订契约：

| 来源 | 做法 | 契约应吸收为 |
|---|---|---|
| visitor / doc-review | `allowed_deductions` 扣分码，judge 只报缺陷，本地按严重度扣分 | 离散锚点之外的第二种 judge 输出形式：`deduction_codes`，judge 输出缺陷列表，分值由评分层按码表计算。比让 judge 直接选 0/0.5/1 更可审计 |
| visitor / doc-review | 检查状态四态 `passed / failed / unavailable / not_attempted`，且 `infrastructure_unavailable_does_not_override_source` | 契约 4.3 的"缺失、无效、不适用、采集失败分别表达"落成具体枚举 |
| visitor / doc-review | `evidence_policy` 按维度声明需要源码、运行时还是浏览器 | 契约 3 的 `evidence` 字段已有，但应补"必需 / 优先 / 佐证"三级 |
| ppt-visual-repair | 封顶规则：图片没修好总分最高 79，几乎没改最高 59 | 契约 3.3 `aggregation` 增加 `gate` 类型，允许某维度失败对总分封顶，而不只是加权平均 |
| swebench ×2 | `validation` 维度只读 trace 中命令与退出码 | 契约 4.1 明确 `trajectory` 证据可用于 deterministic checker，并给出"命令 + 退出码"的结构化格式要求 |
| odyssey | `Check(dimension, weight, passed, label)` 数据结构 | 就是契约 3.1 二元判据的最小实现，可作为 checker 返回格式的标准 |
| gdpval-official ×2 | rubric 条目带分值 1/2/5，"全过才得分" | 契约允许二元判据带权重，不必每条等权 |
| presentbench | judge 实现放共享目录，场景只放 rubric 和 weights | 这是 v2"场景不自带 judge"的半成品，说明方向可行 |
| 三个 user-programming | 题面扰动声明 `allowed / forbidden / scorer_invariant` | 契约应保留这个概念，但改名，见下 |

---

## 5. 契约草案需要修订的点

评审暴露出契约草案本身的四个问题：

1. **`mutations` 命名冲突。** 已处理：v2 产物变体改名 `probes/`，`mutations` 保留 v1 题面扰动语义。
2. **judge 输出只允许离散锚点太窄。** 已处理：契约 3.1 增加 `deduction_codes`。
3. **聚合只有加权平均。** 已处理：契约 3.5 增加 `aggregation.gates`。
4. **证据类型缺 `runtime_probe`。** 未处理。 C 档三个场景的迁移依赖它，需要和上游一起定义采集格式。

---

## 6. 建议的迁移顺序

不建议一次性迁 11 个。按"每一步都产生可认证的 judge 维度"排：

1. **gdpval-source-faithfulness-official** 转成 doc-tour-pl-memo。rubric 现成，探针最好造，是契约的第一个完整实例。
2. **odyssey 和 conflict-resolution** 作为 A 档样板，验证"改元数据即可"这句话是否成立，顺便产出 checker 返回格式标准。
3. **presentbench-education** 作为 B 档第二个，验证非文本产物的渲染器方案。
4. **visitor-appointment** 作为 C 档样板，和上游一起定义 `runtime_probe`。它的 rubric 是三个 C 档场景里最完整的。
5. 其余按需。

每迁一个，`certification/` 下要有认证报告；没有报告的 judge 维度按契约只能是 diagnostic。

---

## 7. 未评审的部分

- 没有运行任何 scorer 或 judge，所有判断基于代码和文档阅读。
- 没有核对 `private/expected` 和官方 rubric 的正确性。
- 两个 swebench 场景带完整仓库（六千和两千六百个文件），没有检查仓库快照是否与 issue commit 一致。
- `_octagon_backend.py` 依赖主仓库 `backend`，这个耦合在 v2 里是否保留未讨论。
