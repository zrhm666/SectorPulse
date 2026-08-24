# 运行时间线失败语义修复设计

## 目标

修复 Phase 1B 运行详情页对阶段结果的错误表达：写作失败不得显示为“写作完成”，已经实际执行的启动、归因和编辑阶段不得因 SSE 事件缺失显示为“等待中”。

## 事件契约

- `writing.done` 仅表示系统已经生成有效 `ArticleDraft`。
- 写作模型未返回有效结构化草稿时发送 `writing.failed`，随后运行终态为 `DRAFT_GENERATION_FAILED`。
- 编辑模型输出无效但系统成功建立确定性备用提纲时发送 `editorial.fallback`；这表示编辑阶段以降级方式完成，不表示模型输出成功。
- 已有成功路径继续发送 `phase1b.start`、`attribution.start`、`attribution.done`、`editorial.done`、`writing.done` 和 `review.done`，保持兼容。

## 前端时间线

时间线为每个阶段计算 `complete`、`failed`、`skipped` 或 `pending`，不再用一个布尔值代表所有状态。

对于 `DRAFT_GENERATION_FAILED`：

- 启动、归因开始、归因完成：已完成。
- 编辑：收到 `editorial.fallback` 时显示“已降级完成”，否则根据终态补全为“已完成”。
- 写作：显示“失败”。
- 审核：显示“未执行”。

实时 SSE 事件优先；终态运行在刷新或晚进入页面时，以持久化的运行状态补全可确定的阶段。补全只描述确定事实，不把未执行阶段推断成成功。

## 样式与兼容

- 成功节点沿用绿色。
- 失败节点使用现有危险色。
- 未执行节点保留中性色，但文案改为“未执行”。
- 不修改现有 API 响应结构、数据库表或历史运行记录。

## 测试

- 后端失败用例断言无有效草稿时包含 `writing.failed`，且不包含 `writing.done`。
- 后端成功用例继续断言 `writing.done`。
- 前端组件用例断言 `DRAFT_GENERATION_FAILED` 的启动、归因、编辑、写作和审核状态文案。
- 前端组件用例断言实时 `editorial.fallback` 的降级文案。

## 非目标

- 本次不持久化完整 SSE 事件流。
- 本次不调整第三方 LLM Prompt、JSON 修复策略或重试次数。
- 本次不改变运行终态枚举。
