# Phase 1：框架内置与安全补丁实施计划

> **For agentic workers:** 使用 executing-plans 当前会话执行，遵循 test-driven-development。

**Goal:** 完整引入可追踪的框架源码并修复可复现运行缺陷，不改变业务入口。

**Architecture:** vendor 内源码独立安装与测试；通用运行补丁仅修改框架，不引入业务依赖。

**Tech Stack:** Python 3.12、pytest、现有虚拟环境。

**Spec:** docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md

## Global Constraints

- 源码复制包含测试、示例及文档；不含 .git 或未跟踪环境。
- 不修改来源目录，不改变现有生产数据库或业务运行器。
- 每个行为补丁先运行失败测试，后实现并回归。

## Task 1：可复现内置

文件：vendor/aidynamic-agent（上游受控文件）、vendor/aidynamic-agent/LOCAL_CHANGES.md、vendor/aidynamic-agent/UPSTREAM_MANIFEST.json。

- [x] 通过 git ls-files 枚举源文件；Copy-Item 复制并逐项 Get-FileHash 比较；manifest 保存来源提交、相对路径和原始 SHA256。
- [x] 使用项目虚拟环境安装本地框架，再执行其 tests；安装不能覆盖项目配置或 .env。
- [x] 保留所有已存在失败的输出，单独评估环境与代码原因。

## Task 2：权限与委派

修改：aidynamic_agent/agents/{factory,parent,sub}.py、tools/builtins/task.py。测试：tests/unit/agents/test_sectorpulse_hardening.py。

- [x] 写失败用例：子 Agent allowed_tool_tags=['news'] 时模型强行请求 market 工具，实际副作用列表必须仍为 []；父 Agent 同样验证。
- [x] 写失败用例：通过 task(toolsets=['news']) 委派时，子任务不能调用 market，且不能扩大父 Agent 的权限。
- [x] 工厂物理筛选子注册表；父子执行层重复权限检查；保持禁止子 task。
- [x] 以真实 ParentAgent/SubAgent + 外部模型替身运行工具循环，断言工具副作用与返回错误，不仅检查方法调用次数。

## Task 3：超时、计费与终态

修改：aidynamic_agent/core/agent.py、agents/sub.py、tools/builtins/task.py。测试：同上。

- [x] 写失败用例：子 Agent usage 超过 token_budget 后不得执行下一轮工具；tokens_used 必须包含子模型返回 usage。
- [x] 写失败用例：模型等待 asyncio.Event，total_timeout=0.02 时通过框架本身在期限结束，返回 TIMEOUT 而非等待下一轮。
- [x] 用 asyncio.timeout 包围完整运行；取消继续向上传播；终态错误/超预算/超时不能由 TaskTool 标记 success=True。
- [x] 工厂继承父配置并缩紧子限制，调用者显式配置仍由后续业务角色工厂限制。

## Task 4：验收与交接

- [x] 框架全部测试运行并记录准确结果；再跑 SectorPulse 非 live/non-postgres 回归。
- [x] LOCAL_CHANGES 记录实际补丁与未覆盖项；总计划标注 Phase 1 完成度。
后续交接：Phase 2 尚未开始，先细化数据库和适配接口，不把本阶段测试当作全平台验收。
