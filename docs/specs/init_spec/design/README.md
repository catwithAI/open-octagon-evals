# 前端页面概念图（v2 · 对齐当前后端接口）

在线可编辑画布：https://claude.ai/code/artifact/9b82be57-f9ea-4a10-b78a-5eb23daa9f47

- `octagon-evals-console.html`：整合版画布，浏览器直接打开即可查看/导出 PNG、PDF（自包含，约 2.5 MB）。
- `Main.dc.html`：实验列表——`GET /experiments` + 逐实验 `GET /experiments/{id}/score`，每行展示 `runs{}` 各 run 独立总分（未 resolved 显示 null）。
- `ExperimentDetail.dc.html`：实验详情——run 聚合卡片 + per-run × per-dimension 对比矩阵（专用矩阵端点待实现，见 tasks.md §8）。
- `DimensionDetail.dc.html`：维度评分详情——`GET /tasks/{task_id}` 的 state / attempts / append-only `scores[]`，lineage 中未写入字段标「待补」。
- `HumanReview.dc.html`：Human 评审任务——`pending → assigned → completed` 状态机与 `POST /human-tasks/{id}/*` 端点，提交幂等语义标注在页内。
- `canvas.json`:画布布局与接口映射便签。

设计方向：内部工具式数据密集控制台；IBM Plex Sans/Mono，冷灰底 + 靛蓝强调色，状态语义色（final 绿 / pending 琥珀 / 失败红）。虚线、灰色元素表示后端尚未实现的能力（agent_judge、矩阵端点、lineage 补全）。
