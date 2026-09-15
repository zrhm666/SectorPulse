# SectorPulse 内置框架说明

来源目录 D:/work/project/agent；Git 5abc18c906c806f9efa6956e6a4362870f4b1c6c；上游版本 0.3.0。UPSTREAM_MANIFEST.json 保存复制前 112 个受控文件的 SHA256；复制时逐文件比较一致。源项目保持未修改，未复制其 .git 和运行环境。此目录保留上游文档、示例、工具和测试，不代表这些工具会向业务 Agent 开放。

## 本地补丁

- 父子 Agent 的工具标签在执行层授权，不只过滤发给模型的工具描述。
- 子注册表只能继承父配置允许的工具；新增 allowed_tool_names 白名单，空列表不允许工具。
- TaskTool 的 toolsets 参数实际筛选工具；委派工具标记 parent_only，保留子 Agent 原有 task 禁令。
- 子配置继承父配置并缩紧默认轮次、时间和 token 上限；子 LLM usage 计入 tokens_used。
- 模型响应耗尽预算后不再执行其请求的工具副作用。
- 总超时覆盖正在等待的模型、重试和工具，调用者取消向上传播。
- 子任务错误、超时、超预算或耗尽轮次不再伪装为成功结果。
- 上游 TaskTool 单测使用真实 AgentResult/TerminationReason，替代不符合运行时类型的 MagicMock 枚举。

## 安装和测试

从 SectorPulse 根目录安装 `.venv/Scripts/python.exe -m pip install -r requirements-agent.txt`，仍使用项目 .venv，不新建 conda 环境。上游依赖约束文件未改，SectorPulse 的额外 constraints 固定本次验证的三个直接依赖版本。

从本目录运行 `D:/work/SectorPulse/.venv/Scripts/python.exe -m pytest tests --ignore=tests/unit/tools/test_bash.py -q -p no:cacheprovider`。更换设备时改为对应虚拟环境路径。框架测试与 SectorPulse 测试分开运行，避免两个 tests 包的名字冲突。

原始基线：626 passed，5 failed。五个失败均在 BashTool 测试，依赖 pwd/grep/rm/sleep 或 Unix 换行，在当前 Windows shell 不兼容。运行核心验收明确排除整份 test_bash.py（14 项），未删除文件或把失败改成成功。业务 Agent 不注册 BashTool；如未来需要通用命令执行，必须单独设计 Windows 支持及安全隔离。

这批补丁是单 Agent/委派边界基础，不是父子共享预算、持久化任务树或业务切换的完成证明。共享预算、角色实例隔离、受限 Skill 资源、业务工具和唯一入口见总计划 Phase 2–4。

补丁验收（2026-09-12）：新增 10 个运行回归用例在修改前 8 failed、2 passed，修改后全部通过。排除上述 Bash 测试文件后框架 627 passed；SectorPulse 非实时回归 519 passed、5 skipped、24 deselected；pip check 通过。没有调用真实 LLM，也没有修改数据库。
