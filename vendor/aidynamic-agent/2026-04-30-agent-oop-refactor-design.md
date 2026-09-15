# Agent OOP 重构与 OpenAI API 接入设计文档

**日期**: 2026-04-30
**版本**: 1.0
**状态**: 通过

---

## 1. 整体架构

采用**消息中心 + 插件化架构**，目录结构如下：

```
agent/
├── __init__.py                 # 包入口
├── config.py                   # 配置管理（Pydantic）
├── core/
│   ├── message.py              # 统一消息模型
│   ├── agent.py                # Agent 基类
│   └── context.py              # 上下文管理器
├── llm/
│   ├── base.py                 # LLMProvider 抽象基类
│   ├── provider.py             # Provider 实现基类
│   ├── factory.py              # Provider 工厂
│   ├── exceptions.py           # 统一异常体系
│   ├── providers/
│   │   ├── anthropic.py        # Anthropic Provider
│   │   └── openai.py           # OpenAI Provider
│   └── adapters/
│       ├── base.py             # 消息适配器基类
│       ├── anthropic_adapter.py
│       └── openai_adapter.py
├── tools/
│   ├── base.py                 # Tool 抽象基类
│   ├── registry.py             # 工具注册中心
│   ├── context.py              # 工具依赖注入容器
│   └── builtins/               # 内置工具实现
│       ├── bash.py
│       ├── file_ops.py
│       ├── glob.py
│       ├── todo.py
│       ├── skill.py
│       ├── task.py
│       └── history.py
├── managers/
│   ├── state.py                # 状态持久化
│   ├── skill.py                # 技能管理
│   ├── todo.py                 # 任务管理
│   └── history.py              # 工具历史存储
├── agents/
│   ├── factory.py              # Agent 工厂
│   ├── parent.py               # 主 Agent
│   └── sub.py                  # 子 Agent
├── hooks/
│   ├── base.py                 # 钩子系统
│   └── builtin.py              # 内置钩子
└── legacy/
    └── adapter.py              # 兼容层

tests/
├── unit/
│   ├── core/
│   │   ├── test_message.py     # 消息模型测试
│   │   └── test_context.py     # 上下文测试
│   ├── llm/
│   │   ├── test_adapters.py    # 消息适配器转换测试
│   │   └── test_exceptions.py  # 异常映射测试
│   ├── tools/
│   │   ├── test_registry.py    # 工具注册测试
│   │   └── test_validation.py  # 参数验证测试
│   └── agents/
│       ├── test_termination.py # 终止条件测试
│       └── test_retry.py       # 重试逻辑测试
├── integration/
│   ├── test_agent_loop.py      # 完整 Agent 循环测试
│   ├── test_tool_concurrent.py # 工具并发执行测试
│   ├── test_subagent.py        # 子代理调用测试
│   └── test_state_persist.py   # 状态持久化测试
├── e2e/
│   ├── test_provider_switch.py # Provider 切换测试
│   └── test_long_conversation.py # 长对话压缩测试
├── mocks/
│   ├── mock_llm.py             # MockLLMProvider 实现
│   └── mock_tools.py           # Mock 工具实现
│   └── fixtures.py             # 测试数据 fixtures
└── conftest.py                 # pytest 配置
```

---

## 2. 核心组件设计

### 2.1 统一消息模型

**文件**: `core/message.py`

处理 Anthropic/OpenAI 格式差异的核心抽象，采用**子类化设计**实现类型安全。

```python
class ContentType(Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ERROR = "error"  # 流式错误块

class FinishReason(Enum):
    """流式响应结束原因"""
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    STOP = "stop"
    ERROR = "error"
    MAX_TOKENS = "max_tokens"

# 基类 - 仅包含公共字段
@dataclass
class ContentBlock:
    """内容块基类"""
    type: ContentType
    metadata: dict = field(default_factory=dict)

# 子类化设计 - 每种类型有专属字段，静态类型检查可捕获错误
@dataclass
class TextBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TEXT, init=False)
    text: str

@dataclass
class ThinkingBlock(ContentBlock):
    type: ContentType = field(default=ContentType.THINKING, init=False)
    thinking: str

@dataclass
class ToolUseBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TOOL_USE, init=False)
    tool_call_id: str
    tool_name: str
    tool_input: dict

@dataclass
class ToolResultBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TOOL_RESULT, init=False)
    tool_call_id: str  # 关联到 ToolUseBlock
    tool_result_content: str
    is_error: bool = False
    history_key: str | None = None  # 关联到 ToolHistoryStore（反馈点 2）

@dataclass
class ErrorBlock(ContentBlock):
    """流式错误块"""
    type: ContentType = field(default=ContentType.ERROR, init=False)
    error_code: str
    error_message: str

# Union 类型 - 用于类型标注
ContentBlockUnion = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock | ErrorBlock

@dataclass
class Message:
    role: Role  # "user", "assistant", "system"
    content: list[ContentBlockUnion]  # 强制统一为列表
    provider: str | None = None
    raw_response: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_text(cls, role: Role, text: str) -> "Message":
        """从字符串创建（入口归一化）"""
        return cls(role=role, content=[TextBlock(text=text)])

@dataclass
class StreamChunk:
    """流式响应块，与 ContentBlock 类型对齐"""
    type: ContentType
    delta: str | dict | None = None
    tool_call_id: str | None = None
    index: int = 0
    finish_reason: FinishReason | None = None  # 使用枚举

@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict  # JSON Schema
    provider_config: dict = field(default_factory=dict)
```

**关键特性**:
- **子类化设计**: 每种内容类型有独立 dataclass，静态类型检查可捕获字段访问错误
- **强制列表格式**: `content` 必须是 `list[ContentBlockUnion]`
- **入口归一化**: `Message.from_text()` 和适配器负责将字符串输入转换为列表格式
- **FinishReason 枚举**: 避免 `finish_reason` 魔法字符串
- **ToolResultBlock**: 工具结果定义统一在消息模型中，避免分散

### 2.2 LLM Provider 抽象层

**文件**: `llm/base.py`, `llm/provider.py`

统一异步接口，**Provider 仅负责纯粹调用，不含重试逻辑**（反馈点 6）。

```python
class LLMProvider(ABC):
    """LLM Provider 抽象基类 - 仅异步接口，不含重试"""

    @abstractmethod
    async def create(self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs) -> LLMResponse:
        """非流式调用"""
        pass

    @abstractmethod
    async def stream(self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs) -> AsyncIterator[StreamChunk]:
        """流式调用 - 返回异步迭代器，需支持异常时资源清理"""
        pass

    async def close(self):
        """关闭底层连接，释放资源"""
        pass

@dataclass
class LLMResponse:
    content: list[ContentBlockUnion]
    stop_reason: FinishReason  # 使用枚举
    model: str
    usage: dict

    def get_tool_calls(self) -> list[ToolUseBlock]:
        """返回工具调用块列表（具体类型）"""
        return [block for block in self.content if isinstance(block, ToolUseBlock)]

    @property
    def has_tool_calls(self) -> bool:
        return len(self.get_tool_calls()) > 0
```

**异常体系** (`llm/exceptions.py`):
```python
class LLMError(Exception):
    """LLM 错误基类"""
    recoverable: bool = False  # 是否可重试

class RateLimitError(LLMError):
    recoverable: True
    retry_after: int | None = None  # 建议等待秒数

class ContextWindowExceededError(LLMError):
    recoverable: False

class AuthenticationError(LLMError):
    recoverable: False

class ProviderUnavailableError(LLMError):
    recoverable: True
```

**适配器职责**:
- `to_provider()` - 统一格式 → Provider 格式
- `from_provider_response()` - Provider 响应 → 统一格式
- `from_provider_chunk()` - 流式块解析
- `map_exception()` - 异常转换（保留 `recoverable` 标记）

**流式调用上下文管理（反馈点 8）**:
```python
# Provider 实现需确保异常时清理资源
async def stream(self, ...) -> AsyncIterator[StreamChunk]:
    connection = await self._create_connection()
    try:
        for chunk in connection.stream():
            yield self._parse_chunk(chunk)
    except Exception as e:
        await connection.close()
        raise self._map_exception(e)
    finally:
        await connection.close()

# 使用方需正确处理迭代器
async with provider:  # 或在结束时调用 close()
    async for chunk in provider.stream(...):
        ...
```

**重试责任边界（反馈点 6）**:
- **Agent 层**: 根据 `LLMError.recoverable` 和 `AgentConfig.max_retries` 控制重试
- **Provider 层**: 仅负责纯粹调用，抛出带 `recoverable` 标记的异常

### 2.3 工具系统

**文件**: `tools/base.py`, `tools/registry.py`, `core/message.py`

插件化 + 依赖注入 + 自动验证 + 安全策略。

```python
class Tool(ABC):
    name: str
    description: str
    max_output_length: int = 10000

    def __init__(self, context: ToolContext)

    @abstractmethod
    def get_definition(self) -> ToolDefinition

    @abstractmethod
    async def _execute_impl(self, **params) -> str:
        """实际执行逻辑 - 子类实现"""
        pass

    # 模板方法 - 自动验证 + 执行 + 截断
    async def execute(self, **params) -> ToolResult:
        """模板方法：验证 → 执行 → 截断 → 存历史 → 生成 summary"""
        # 1. 自动验证（反馈点 9）
        is_valid, error_msg = self.validate_params(params)
        if not is_valid:
            return ToolResult(
                success=False,
                content="",
                error=error_msg,
                error_type=ErrorType.VALIDATION_ERROR
            )

        # 2. 安全检查（反馈点 11）
        blocked = self._check_blocked(params)
        if blocked:
            return ToolResult(
                success=False,
                content="",
                error=f"Blocked: {blocked}",
                error_type=ErrorType.PERMISSION_ERROR
            )

        # 3. 执行
        try:
            raw_content = await self._execute_impl(**params)
        except TimeoutError:
            return ToolResult(success=False, error_type=ErrorType.TIMEOUT_ERROR, ...)
        except Exception as e:
            return ToolResult(success=False, error=str(e), error_type=ErrorType.EXECUTION_ERROR, ...)

        # 4. 截断处理（反馈点 10）
        if len(raw_content) > self.max_output_length:
            truncated_content = raw_content[:self.max_output_length]
            summary = self._generate_summary(raw_content)
            history_key = await self._store_full_result(raw_content)  # 存储并获取 key

            return ToolResult(
                success=True,
                content=truncated_content,
                truncated=True,
                summary=summary,
                original_length=len(raw_content),
                history_key=history_key  # 传递到 ToolResult（反馈点 2）
            )

        # 未截断时也可能存储历史（可选）
        history_key = None
        if self.context.history_store and self._should_store_history():
            history_key = await self._store_full_result(raw_content)

        return ToolResult(
            success=True,
            content=raw_content,
            history_key=history_key  # 传递到 ToolResult（反馈点 2）
        )

    def validate_params(self, params: dict) -> tuple[bool, str | None]:
        """使用 jsonschema 自动验证"""
        schema = self.get_definition().input_schema
        try:
            jsonschema.validate(params, schema)
            return True, None
        except jsonschema.ValidationError as e:
            return False, str(e)

    def _check_blocked(self, params: dict) -> str | None:
        """安全策略检查（反馈点 11）"""
        # 由具体工具实现，如 BashTool 检查 blocked_commands
        return None

    def _generate_summary(self, content: str) -> str:
        """生成截断内容的摘要"""
        return f"[Truncated, {len(content)} chars total]"

    async def _store_full_result(self, content: str) -> str | None:
        """存储完整结果到 ToolHistoryStore"""
        if self.context.history_store:
            key = await self.context.history_store.store(self.name, content)
            return key
        return None
```

**ToolResult** 设计（统一在 `core/message.py` 中，反馈点 3）:
```python
class ErrorType(Enum):
    SYSTEM_ERROR = "system_error"
    EXECUTION_ERROR = "execution_error"
    VALIDATION_ERROR = "validation_error"
    PERMISSION_ERROR = "permission_error"
    TIMEOUT_ERROR = "timeout_error"
    NOT_FOUND_ERROR = "not_found_error"

@dataclass
class ToolResult:
    """工具执行结果 - 用于内部流转，最终转为 ToolResultBlock"""
    success: bool
    content: str
    tool_call_id: str | None = None  # Agent 核心在构建 ToolResultBlock 时填充
    error: str | None = None
    error_type: ErrorType | None = None

    # Token 管理
    truncated: bool = False
    summary: str | None = None
    original_length: int | None = None
    history_key: str | None = None  # 关联到 ToolHistoryStore

    def to_result_block(self, tool_call_id: str) -> ToolResultBlock:
        """转换为 ToolResultBlock 用于消息，传递 history_key（反馈点 2）"""
        return ToolResultBlock(
            tool_call_id=tool_call_id,
            tool_result_content=self.content if self.success else self.error,
            is_error=not self.success,
            history_key=self.history_key  # 从 ToolResult 传递到 ToolResultBlock
        )
```

**ToolContext** 依赖注入:
```python
@dataclass
class ToolContext:
    workdir: str
    skill_manager: SkillManager | None = None
    todo_manager: TodoManager | None = None
    history_store: ToolHistoryStore | None = None

    # 安全策略（反馈点 11 - 由 SafetyCheckHook 或工具内部检查）
    blocked_commands: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    timeout: int = 120
```

**安全策略实现（反馈点 11）**:
- **方案**: 在 `Tool.execute()` 模板方法中调用 `_check_blocked()`，由具体工具实现检查逻辑
- **不可绕过**: 模板方法保证所有执行路径都经过检查，子类只实现 `_execute_impl()`
- **示例**: `BashTool._check_blocked()` 检查命令是否在 `blocked_commands` 列表中

**权限标签系统**:
```python
# 注册时标记
registry.register(TaskTool, tags=["parent_only"])

# 获取时过滤
tools = registry.get_definitions(tags=["all", "parent_only"])
```

### 2.4 Agent 核心类

**文件**: `core/agent.py`, `agents/parent.py`, `agents/sub.py`

全异步循环 + 多重终止条件 + 错误追踪 + 子代理通信。

```python
@dataclass
class AgentError:
    """单次错误记录"""
    error_type: str  # "llm_error", "tool_error", "validation_error", "timeout"
    message: str
    loop_iteration: int
    tool_name: str | None = None
    recoverable: bool = False

@dataclass
class AgentConfig:
    max_loops: int = 30
    max_tokens: int = 8000
    system_prompt: str = ""  # 启动时转为 Message 插入头部

    # 终止控制
    total_timeout: int = 300
    token_budget: int = 100000

    # 工具权限
    allowed_tool_tags: list[str] = field(default_factory=list)

    # 重试配置
    max_retries: int = 3

@dataclass
class AgentResult:
    text: str
    termination_reason: TerminationReason
    loops_used: int
    tokens_used: int
    time_elapsed: float
    error: str | None = None
    error_detail: list[AgentError] = field(default_factory=list)
```

**系统提示与 Message 的关系（反馈点 4）**:
- `AgentConfig.system_prompt` 仅是配置存储
- Agent 启动时，将 `system_prompt` 转为 `Message(role=Role.SYSTEM, content=[TextBlock(system_prompt)])`
- 该 Message 插入到 `AgentContext.messages` 头部，作为第一条消息
- 避免两套机制，统一通过 Message 管理

**核心方法（全部异步）**:
```python
class BaseAgent(ABC):
    async def run(self, initial_input: str) -> AgentResult:
        """主入口"""
        # 1. 初始化上下文，插入系统提示
        self.context = AgentContext(messages=[])
        if self.config.system_prompt:
            await self.context.add_message(
                Message.from_text(Role.SYSTEM, self.config.system_prompt)
            )
        await self.context.add_message(
            Message.from_text(Role.USER, initial_input)
        )

        # 2. 主循环
        for iteration in range(self.config.max_loops):
            # 终止检查 - 每次迭代开始（反馈点 13）
            reason = await self._check_termination_conditions(iteration)
            if reason:
                return self._build_result(reason, iteration)

            # LLM 调用（带重试）
            response = await self._call_llm_with_retry()

            # 终止检查 - LLM 返回后检查 stop_reason（反馈点 13）
            if response.stop_reason in [FinishReason.END_TURN, FinishReason.STOP]:
                return self._build_result(response.stop_reason, iteration)

            # 执行工具
            if response.has_tool_calls:
                await self._execute_tools(response.get_tool_calls())

        return self._build_result(TerminationReason.MAX_LOOPS, self.config.max_loops)

    async def _check_termination_conditions(self, iteration: int) -> TerminationReason | None:
        """每次迭代开始检查（反馈点 13）"""
        # 检查时间
        elapsed = time.time() - self.start_time
        if elapsed > self.config.total_timeout:
            return TerminationReason.TIMEOUT

        # 检查 Token
        if self.tokens_used > self.config.token_budget:
            return TerminationReason.TOKEN_BUDGET

        return None

    async def _call_llm_with_retry(self) -> LLMResponse:
        """Agent 层控制重试（反馈点 6）"""
        for attempt in range(self.config.max_retries):
            try:
                return await self.provider.create(self.context.messages, ...)
            except LLMError as e:
                if not e.recoverable or attempt == self.config.max_retries - 1:
                    self._record_error(e, attempt)
                    raise
                await asyncio.sleep(2 ** attempt)  # 指数退避
```

**子代理通信协议（反馈点 12）**:
```python
@dataclass
class SubAgentRequest:
    """主 Agent 发送给子 Agent 的请求"""
    task_description: str  # 子任务的描述
    context_files: list[str] | None = None  # 相关文件列表
    constraints: dict | None = None  # 约束条件（超时、工具限制）

@dataclass
class SubAgentResponse:
    """子 Agent 返回给主 Agent 的结果"""
    success: bool
    result_text: str
    termination_reason: TerminationReason
    error: str | None = None

# TaskTool 实现
class TaskTool(Tool):
    async def _execute_impl(self, task_description: str, **kwargs) -> str:
        request = SubAgentRequest(task_description=task_description, ...)

        # 创建子 Agent
        sub_agent = SubAgent(
            config=self._build_sub_config(request),
            provider=self.provider  # 共享 Provider
        )

        # 运行子 Agent
        result = await sub_agent.run(request.task_description)

        # 转换结果为工具输出
        response = SubAgentResponse(
            success=result.termination_reason != TerminationReason.ERROR,
            result_text=result.text,
            termination_reason=result.termination_reason,
            error=result.error
        )
        return json.dumps(dataclasses.asdict(response))
```

**父子 Agent 区别**:
- `ParentAgent`: 权限 `["all", "parent_only"]`，可调用 `TaskTool`
- `SubAgent`: 权限 `["all", "sub_only"]`，独立上下文，更短超时，不可调用 `TaskTool`

### 2.5 上下文管理器

**文件**: `core/context.py`

消息管理 + 微压缩 + Token 计数 + 历史存储。

```python
@dataclass
class CompactConfig:
    """压缩配置"""
    trigger_token_threshold: int = 80000  # 触发压缩的 Token 阈值
    preserve_recent_count: int = 5  # 保留最近 N 个工具结果完整内容

@dataclass
class AgentContext:
    """上下文管理器 - 单写者模型（反馈点 15）"""
    messages: list[Message]
    recent_files: list[str]

    # Token 计数器（反馈点 14）
    total_tokens: int = 0

    # 压缩状态
    has_compacted: bool = False
    last_summary: str = ""

    # 配置
    compact_config: CompactConfig
    history_store: ToolHistoryStore | None = None

    # 单写者模型说明（反馈点 15）
    # Agent 循环内顺序执行：add_message → check_compact → continue
    # 无并发写入风险，不需要锁机制

    async def add_message(self, message: Message):
        """添加消息，更新 Token 计数"""
        self.messages.append(message)
        # 更新 Token 计数（从 message.metadata 或 LLMResponse.usage）
        if message.raw_response and "usage" in message.raw_response:
            self.total_tokens += message.raw_response["usage"].get("total_tokens", 0)

    async def compact_if_needed(self) -> bool:
        """根据 Token 计数触发压缩（反馈点 14）"""
        if self.total_tokens < self.compact_config.trigger_token_threshold:
            return False

        # 压缩逻辑
        await self._do_compact()
        self.has_compacted = True
        return True

    async def _do_compact(self):
        """执行压缩"""
        # 1. 保留最近 N 个工具结果
        preserved = []
        tool_results_to_compact = []

        for msg in self.messages:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    preserved.append(block)
                    if len(preserved) > self.compact_config.preserve_recent_count:
                        tool_results_to_compact.append(preserved.pop(0))

        # 2. 生成摘要
        for block in tool_results_to_compact:
            summary = ToolResultSummary(
                tool_name=block.metadata.get("tool_name", "unknown"),
                tool_call_id=block.tool_call_id,
                success=not block.is_error,
                brief=f"[Result: {len(block.tool_result_content)} chars]",
                history_key=block.metadata.get("history_key")
            )
            # 替换为摘要文本块
            # ... 实现细节
```

**微压缩策略**:
- **触发条件**: `total_tokens >= trigger_token_threshold`（基于 Token 计数）
- 保留最近 N 个工具结果完整内容
- 生成 `ToolResultSummary` 保留调用意图
- 使用 `ToolHistoryStore` 保存完整历史

```python
@dataclass
class ToolResultSummary:
    tool_name: str
    tool_call_id: str
    success: bool
    brief: str
    history_key: str | None = None

    def to_compact_string(self) -> str:
        return f"[Tool: {self.tool_name}, Success: {self.success}, Brief: {self.brief}]"
```

### 2.6 钩子系统

**文件**: `hooks/base.py`, `hooks/builtin.py`

事件驱动扩展点，支持故障容错 + 阻断行为定义。

```python
class HookEvent(Enum):
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    ON_RATE_LIMIT = "on_rate_limit"
    BEFORE_TOOL_EXECUTION = "before_tool_execution"
    AFTER_TOOL_EXECUTION = "after_tool_execution"
    ON_MESSAGE_ADDED = "on_message_added"
    BEFORE_COMPACT = "before_compact"
    ON_AGENT_START = "on_agent_start"
    ON_AGENT_END = "on_agent_end"
    ON_ERROR = "on_error"

class TerminationReason(Enum):
    END_TURN = "end_turn"
    MAX_LOOPS = "max_loops"
    TIMEOUT = "timeout"
    TOKEN_BUDGET = "token_budget"
    ERROR = "error"
    HOOK_BLOCKED = "hook_blocked"  # 钩子阻断终止（反馈点 1）
```

**HookEvent 阻断行为定义（反馈点 1）**:

| HookEvent | 返回 False 时的行为 |
|-----------|---------------------|
| `BEFORE_LLM_CALL` | 跳过本次 LLM 调用，结束循环，返回 `TerminationReason.HOOK_BLOCKED`，`AgentResult.text` 为空或上次文本 |
| `BEFORE_TOOL_EXECUTION` | 跳过该工具执行，向 LLM 返回固定错误消息：`ToolResultBlock(tool_result_content="[Tool blocked by safety hook]", is_error=True)`，LLM 可根据此调整策略 |
| `BEFORE_COMPACT` | 取消本次压缩，继续循环（不影响流程，仅跳过压缩操作） |
| `ON_AGENT_START` | 阻断 Agent 启动，直接返回 `TerminationReason.HOOK_BLOCKED` |
| 其他事件 | 不支持阻断（`AFTER_*`, `ON_*` 事件返回值不影响流程） |

```python
@dataclass
class HookConfig:
    """钩子配置"""
    fail_mode: str = "skip"  # "skip" | "raise" - 钩子失败时的行为（反馈点 16）

class Hook(ABC):
    name: str
    priority: int = 100
    _registration_order: int = 0  # 内部记录注册顺序（反馈点 17）

    @abstractmethod
    async def execute(self, ctx: HookContext) -> bool:
        """返回 False 可阻断流程（行为见上表）"""
        pass

    def can_handle(self, event: HookEvent) -> bool:
        return True  # 默认处理所有事件

class HookExecutor:
    """钩子执行器 - 处理排序、异常、容错"""

    def __init__(self, config: HookConfig):
        self.config = config
        self.hooks: list[Hook] = []
        self._next_order = 0

    def register(self, hook: Hook):
        """注册钩子，记录注册顺序"""
        hook._registration_order = self._next_order
        self._next_order += 1
        self.hooks.append(hook)

    def _sort_hooks(self) -> list[Hook]:
        """稳定排序：priority 升序，同优先级按注册顺序（反馈点 17）"""
        return sorted(self.hooks, key=lambda h: (h.priority, h._registration_order))

    async def execute_event(self, event: HookEvent, ctx: HookContext) -> bool:
        """执行事件钩子，处理异常（反馈点 16）"""
        for hook in self._sort_hooks():
            if not hook.can_handle(event):
                continue

            try:
                result = await hook.execute(ctx)
                if not result:  # 钩子阻断流程
                    return False
            except Exception as e:
                if self.config.fail_mode == "raise":
                    raise
                # skip 模式：记录错误，继续执行
                logger.warning(f"Hook {hook.name} failed: {e}")
                continue

        return True
```

**内置钩子**:
- `LoggingHook` - 日志记录（见下方日志规范）
- `MetricsHook` - 指标收集
- `SafetyCheckHook` - 安全检查（可阻断）
- `DebugHook` - 调试输出
- `RateLimitHandlerHook` - 速率限制处理

**日志规范（反馈点 19）**:
```python
class LogLevel(Enum):
    DEBUG = "debug"    # 流式块、详细内部状态
    INFO = "info"      # 循环迭代、工具调用、压缩触发
    WARNING = "warning"  # 钩子失败、重试触发
    ERROR = "error"    # 工具失败、LLM 错误、终止异常

class LoggingHook(Hook):
    priority = 10  # 最早执行

    async def execute(self, ctx: HookContext) -> bool:
        event = ctx.event

        # 日志级别映射
        if event == HookEvent.ON_AGENT_START:
            logger.info(f"Agent started: {ctx.agent_config}")
        elif event == HookEvent.BEFORE_LLM_CALL:
            logger.info(f"LLM call #{ctx.loop_iteration}")
        elif event == HookEvent.AFTER_LLM_CALL:
            logger.debug(f"LLM response: {ctx.response.stop_reason}")
        elif event == HookEvent.BEFORE_TOOL_EXECUTION:
            logger.info(f"Tool call: {ctx.tool_name}")
        elif event == HookEvent.AFTER_TOOL_EXECUTION:
            if ctx.tool_result.success:
                logger.debug(f"Tool result: {ctx.tool_name} success")
            else:
                logger.error(f"Tool failed: {ctx.tool_name} - {ctx.tool_result.error}")
        elif event == HookEvent.ON_ERROR:
            logger.error(f"Error: {ctx.error.message}")
        elif event == HookEvent.BEFORE_COMPACT:
            logger.info(f"Compaction triggered: {ctx.token_count} tokens")

        return True  # 不阻断
```

**MetricsHook 字段定义**:
```python
@dataclass
class MetricsData:
    """MetricsHook 收集的指标"""
    total_loops: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_errors: int = 0

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0

    start_time: float = 0.0
    end_time: float = 0.0
    total_duration: float = 0.0
    llm_duration: float = 0.0
    tool_duration: float = 0.0

    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_error_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
```

### 2.7 管理器模块

**SkillManager** (`managers/skill.py`):
- 扫描 `skills/` 目录
- 解析 YAML frontmatter
- 提供 `describe_available()` 和 `load_full_text()`

**TodoManager** (`managers/todo.py`):
- 唯一 ID 生成
- 批量事件处理
- 状态查询（pending/in_progress/completed）
- 持久化支持

**StateManager** (`managers/state.py`):
- JSON 格式保存/加载上下文
- 兼容旧 JSONL 格式

**ToolHistoryStore** (`managers/history.py`):
- 按会话保存完整工具结果
- 支持按 `tool_call_id` 查询

### 2.8 配置与兼容层

**AppConfig** (`config.py`):
- Pydantic 自动加载 `.env`
- 分层配置：`ProviderConfig`, `AgentConfig`, `ToolConfig`
- `use_legacy` 控制新旧切换

**LegacyAdapter** (`legacy/adapter.py`):
- `run_agent()` - 同步入口，智能检测事件循环（反馈点 18）
- `async run_agent_async()` - 异步入口
- `_run_new()` / `_run_legacy()` - 内部切换
- `_convert_legacy_history()` - 格式转换
- 全局单例：`get_adapter()`

```python
class LegacyAdapter:
    """兼容旧代码的适配器，提供同步和异步两种入口"""

    def run_agent(self, prompt: str, history: list | None = None) -> str:
        """同步入口 - 智能检测事件循环（反馈点 18）"""
        try:
            # 检测是否存在运行中的事件循环
            loop = asyncio.get_running_loop()
            # 存在循环 - 在当前循环中同步等待
            future = asyncio.ensure_future(self.run_agent_async(prompt, history))
            return loop.run_until_complete(future)
        except RuntimeError:
            # 无运行循环 - 使用 asyncio.run()
            return asyncio.run(self.run_agent_async(prompt, history))

    async def run_agent_async(self, prompt: str, history: list | None = None) -> str:
        """异步入口 - 调用新架构"""
        if self.config.use_legacy:
            return await self._run_legacy(prompt, history)
        return await self._run_new(prompt, history)

# 便捷函数
def run_agent(prompt: str, history: list | None = None) -> str:
    return get_adapter().run_agent(prompt, history)
```

---

## 3. 数据流

```
用户输入
    │
    ▼
┌─────────────────┐
│  LegacyAdapter  │ ← 兼容入口
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   ParentAgent   │
│   ┌───────────  │
│   │ Context    │ ← 消息历史
│   └───────────  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LLMProvider    │ ← Anthropic/OpenAI
│  ┌────────────  │
│  │ Adapter      │ ← 格式转换
│  └────────────  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LLMResponse    │
│  - content      │
│  - tool_calls   │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐ ┌───────┐
│ TEXT  │ │ TOOL  │
│ 输出  │ │ 执行  │
└───────┘ └───┬───┘
              │
              ▼
        ┌───────────┐
        │ ToolRegistry │
        │ - BashTool   │
        │ - FileTool   │
        │ - TaskTool   │
        └────────┬─────┘
                 │
                 ▼
           ┌──────────┐
           │ ToolResult│
           └──────────┘
                 │
                 ▼
           ┌──────────┐
           │ Context  │ ← 添加工具结果
           └──────────┘
                 │
                 ▼
           ┌──────────┐
           │ 压缩检查 │ ← CompactConfig
           └──────────┘
                 │
                 ▼
           ┌──────────┐
           │ 继续循环 │
           └──────────┘
```

---

## 4. 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Provider 架构 | 统一抽象层 + 保留各自特性 | 支持多 Provider，不丢失原生功能 |
| Agent 架构 | 完整分层（7 个模块） | 职责清晰，便于扩展和测试 |
| ContentBlock 设计 | 子类化（TextBlock, ToolUseBlock 等） | 类型安全，静态检查可捕获字段错误 |
| 消息格式 | 强制 `list[ContentBlockUnion]` + 入口归一化 | 统一处理，避免类型分支 |
| 流式块格式 | StreamChunk 与 ContentBlock 类型对齐 + FinishReason 枚举 | 一致性，避免魔法字符串 |
| 接口设计 | 核心全异步，LegacyAdapter 桥接同步 | 降低维护成本，避免双 API |
| 重试责任 | Agent 层控制，Provider 仅抛出 recoverable 标记 | 职责清晰，便于策略定制 |
| 工具系统 | 插件化 + 模板方法 + 权限标签 | 灵活注册，安全检查不可绕过 |
| 截断流程 | execute → 截断 → 存历史 → 生成 summary | 流程明确，保留意图 |
| 压缩触发 | 基于 Token 计数，阈值参数化 | 精确控制，避免超限 |
| 上下文模型 | 单写者（Agent 循环内顺序） | 无竞态，不需要锁 |
| 钩子容错 | try/except + fail_mode 配置 | 灵活处理，避免级联失败 |
| 钩子排序 | priority + 注册顺序稳定排序 | 确定性强，便于调试 |
| 事件循环兼容 | 检测运行循环，智能桥接 | 支持嵌套调用场景 |
| 日志规范 | DEBUG/INFO/WARNING/Error 级别映射 | 避免噪音，便于排查 |
| 测试 Mock | MockLLMProvider 可配置响应序列 | 完整控制，覆盖各种场景 |
| 迁移策略 | 并行运行 | 安全验证，平滑迁移 |

---

## 5. 依赖关系

```
外部依赖:
- anthropic (SDK)
- openai (SDK)
- pydantic (配置)
- jsonschema (验证)
- yaml (提示词)
- asyncio (异步)

内部依赖:
- core/ → 无外部依赖（纯抽象）
- llm/ → core/, 外部 SDK
- tools/ → core/, managers/
- agents/ → core/, llm/, tools/, hooks/
- managers/ → core/
- hooks/ → core/
- legacy/ → 所有模块
```

---

## 6. 验证方案

### 6.1 单元测试

- 消息适配器转换测试（Anthropic ↔ OpenAI）
- 工具参数验证测试（jsonschema）
- Agent 终止条件测试（循环/超时/Token）
- 压缩策略测试（保留意图、历史恢复）
- **钩子阻断测试（反馈点 3）**: 验证 `BEFORE_LLM_CALL` 返回 False 后 Agent 未调用 LLM

### 6.2 集成测试

- 完整 Agent 循环测试（使用 MockLLMProvider）
- 工具并发执行测试
- 子代理调用测试
- 状态持久化测试
- **工具并发冲突测试（反馈点 3）**: 模拟两个工具同时写入同一文件，验证执行顺序或冲突处理
- **压缩恢复测试（反馈点 3）**: 压缩后通过 `history_key` 恢复完整结果，验证 LLM 能正确获取

### 6.3 端到端测试

- Provider 切换测试（Anthropic ↔ OpenAI）
- 长对话压缩测试

### 6.4 Mock 基础设施（反馈点 20）

**MockLLMProvider** (`tests/mocks/mock_llm.py`):
```python
@dataclass
class MockResponseConfig:
    """配置单个 Mock 响应"""
    content: list[ContentBlockUnion]
    stop_reason: FinishReason = FinishReason.END_TURN
    usage: dict = field(default_factory=lambda: {"total_tokens": 100})

class MockLLMProvider(LLMProvider):
    """用于测试的 Mock Provider"""

    def __init__(self):
        self.response_sequence: list[MockResponseConfig] = []
        self.call_count: int = 0
        self.recorded_calls: list[tuple[list[Message], list[ToolDefinition]]] = []

    def set_responses(self, responses: list[MockResponseConfig]):
        """设置响应序列 - 按调用顺序返回"""
        self.response_sequence = responses
        self.call_count = 0

    async def create(self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs) -> LLMResponse:
        """返回预设响应，记录调用"""
        self.recorded_calls.append((messages, tools or []))

        if self.call_count < len(self.response_sequence):
            config = self.response_sequence[self.call_count]
            self.call_count += 1
            return LLMResponse(
                content=config.content,
                stop_reason=config.stop_reason,
                model="mock-model",
                usage=config.usage
            )

        # 默认响应：文本结束
        return LLMResponse(
            content=[TextBlock(text="Mock default response")],
            stop_reason=FinishReason.END_TURN,
            model="mock-model",
            usage={"total_tokens": 50}
        )

    async def stream(self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs) -> AsyncIterator[StreamChunk]:
        """流式 Mock - 逐块返回"""
        response = await self.create(messages, tools, **kwargs)
        for i, block in enumerate(response.content):
            if isinstance(block, TextBlock):
                # 模拟流式文本
                for j, char in enumerate(block.text):
                    yield StreamChunk(
                        type=ContentType.TEXT,
                        delta=char,
                        index=j
                    )
            elif isinstance(block, ToolUseBlock):
                yield StreamChunk(
                    type=ContentType.TOOL_USE,
                    delta={"name": block.tool_name, "input": block.tool_input},
                    tool_call_id=block.tool_call_id,
                    index=i
                )
        yield StreamChunk(type=ContentType.TEXT, finish_reason=response.stop_reason)

# pytest fixture
@pytest.fixture
def mock_provider():
    """测试 fixture：提供 MockLLMProvider"""
    return MockLLMProvider()
```

**使用示例**:
```python
def test_agent_tool_call(mock_provider):
    # 配置 Mock：先返回工具调用，再返回最终文本
    mock_provider.set_responses([
        MockResponseConfig(
            content=[ToolUseBlock(tool_call_id="call_1", tool_name="bash", tool_input={"command": "ls"})],
            stop_reason=FinishReason.TOOL_USE
        ),
        MockResponseConfig(
            content=[TextBlock(text="Task completed")],
            stop_reason=FinishReason.END_TURN
        )
    ])

    agent = ParentAgent(provider=mock_provider, config=AgentConfig())
    result = await agent.run("List files")

    assert result.termination_reason == TerminationReason.END_TURN
    assert len(mock_provider.recorded_calls) == 2  # 两次 LLM 调用
```

- 新旧代码对比测试（相同输入，相同输出）
- Provider 切换测试（Anthropic ↔ OpenAI）
- 长对话压缩测试

---

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| API 格式差异导致转换错误 | 完整的适配器测试，保留原始响应 |
| 异步代码复杂度 | 同步/异步分离，渐进迁移 |
| 性能下降（抽象层开销） | 钩子可选，适配器轻量 |

---

## 8. 后续扩展

1. **更多 Provider** - 添加 Gemini、Azure 等
2. **流式响应** - 实现 `stream()` 方法
3. **多模态支持** - 扩展 `ContentType.IMAGE`
4. **分布式执行** - 工具远程执行
5. **可视化监控** - 基于 MetricsHook 的 Dashboard

---

## 附录 A: 配置示例

```env
# .env
LLM_PROVIDER=anthropic
API_KEY=sk-xxx
BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic
MODEL_ID=qwen3.6-plus

USE_LEGACY=false
DEBUG_MODE=true
WORKDIR=.

AGENT_MAX_LOOPS=30
AGENT_TIMEOUT=300
AGENT_TOKEN_BUDGET=100000
```

---

## 附录 B: 使用示例

```python
# 新代码方式
from agent import AppConfig, AgentFactory, ProviderFactory

config = AppConfig.load()
provider = ProviderFactory.create(config.provider)
agent = AgentFactory(...).create_parent_agent("你是一个助手")
result = await agent.run("帮我分析这个文件")
print(result.text)

```