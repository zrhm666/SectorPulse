# LLM 系统提示词

这里存放程序实际发送给模型的指令。参考 CAG 的安全 YAML 读取方式，使用本项目 PromptRegistry 统一递归加载。

| 目录 / 文件 | 用途 |
| --- | --- |
| application/writing/attribution.yaml | 工作流模式归因 |
| application/writing/attribution_agent.yaml | Agent 角色、查证与工具决策规则 |
| application/writing/agent_validation_feedback.yaml | 结论未通过校验后的纠正指令 |
| application/writing/editorial.yaml | 编辑与大纲 |
| application/writing/writing.yaml | 文章写作 |
| application/writing/review.yaml | 自动审核 |
| application/writing/revision.yaml | 按审核意见修订 |
| infrastructure/llm/structured_output.yaml | 系统指令与 JSON Schema 的协议组装 |

修改对应 YAML 的 `system`，更新 `version`，然后重启后端。`prompt_id` 是已有程序的内部查找标识，文件移动时保留原值。加载器检查嵌套目录中的重复 ID、缺少字段和未声明变量；配置错误会明确报错。

```yaml
prompt_id: example
version: "1.0.0"
variables: [subject]
system: |-
  请分析 ${subject}，仅依据提供的数据。
```

运行时使用 `registry.get("example").render(subject="文化传媒")`。变量必须与 `variables` 完全一致。JSON 花括号无需转义，字面美元符号写成 `$$`；插入值不会再次被当成模板解析。

业务指令先由阶段读取；模型适配器再用 structured_output 模板代入业务系统指令和程序生成的 Schema。Agent 纠错指令从单独 YAML 读取，作为下一轮反馈。动态行情、证据 ID、工具定义、剩余次数和验证规则由 Python 管理。

现有六份业务提示词保持静态文本；不要仅在 YAML 新增变量就期望自动获得运行数据。新增动态变量时，必须同时让对应调用代码通过 `render(...)` 明确传入。当前模板插值主要用于 structured_output 的系统指令与 Schema 组装。

原六份模板的内容哈希算法保持不变，移动目录不改变哈希；修改文本会改变模板哈希。现有调用审计仍记录阶段 ID/版本与输入数据哈希，本次没有将其改成最终 HTTP 请求全文哈希。
