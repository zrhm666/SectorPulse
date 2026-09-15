# Contributing to aidynamic-agent

欢迎贡献代码！本仓库托管于阿里云 Codeup，遵循以下协作规范。

## 目录
- [开发环境](#开发环境)
- [开发流程](#开发流程)
- [代码规范](#代码规范)
- [提交信息规范](#提交信息规范)
- [合并请求流程](#合并请求流程)

## 开发环境

- Python ≥ 3.11，Git
- 安装开发依赖：

```bash
git clone <codeup-repo-url>
cd aidynamic-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

> 说明：除 `pre-commit` 阶段的钩子外，必须同时安装 `commit-msg` 阶段的钩子，Conventional Commits 提交信息校验才会生效。

## 开发流程

1. 从 `main` 切功能分支：`git checkout -b feat/my-feature`
2. 小步提交（见提交规范），频繁推送
3. 合并到 `main` 必须走 Codeup 合并请求（MR），至少 1 人评审，流水线检查须通过
4. 合并后删除功能分支

## 代码规范

- Lint/格式化：`ruff check .`、`ruff format .`（pre-commit 自动执行）
- 类型检查：`mypy aidynamic_agent`
- 测试：`pytest`（提交前本地跑通）

## 提交信息规范

使用 Conventional Commits：`<type>(<scope>): <subject>`
type ∈ feat/fix/docs/style/refactor/perf/test/build/ci/chore/revert。
提交信息不规范的 commit 会被 pre-commit 的提交信息钩子拦截。

## 合并请求流程

- 标题与内容按 `docs/MR_TEMPLATE.md` 填写
- 变更描述、关联 issue、测试情况必须写明
- 流水线 lint/test 全绿 + 至少 1 名评审通过后方可合并