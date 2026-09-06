# 前端开发工具链安全升级设计

日期：2026-09-06；基线：`main=bbafb17`。继续执行可靠性收尾计划剩余的开发依赖升级任务，按用户要求先写文档、当前会话连续执行，不逐阶段再次确认。

## 目标与边界

消除已知 Vite/esbuild 开发服务器告警，消除当前双 Vite 主版本与无效 esbuild peer dependency。页面、React 18、路由、业务接口、9000 端口代理、静态 `web/dist` 交付保持不变。不改业务数据库、`.env`、授权文件，不调用 Live，不恢复影子测试，不推送远端。

## 现状与方案

2026-09-06 新鲜审计返回 2 个受影响依赖节点：Vite 5.4.21 高危、esbuild 0.21.5 中危；此前历史报告节点数量不同，不修改历史扫描结果。`npm ls` 还发现 Vitest 4.1.10 的嵌套 Vite 8.2.1 解析到不符合 peer 范围的 esbuild 0.21.5。

采用方案 A：Vite 8.2.2 + `@vitejs/plugin-react` 6.1.1，与现有 Vitest 4.1.10 对齐，使用官方 Rolldown/Oxc 转换链。只改这两个直接开发依赖和必要配置，不升级 React、路由或其他无关包，不启用 React Compiler。包版本范围用 `^8.2.2`、`^6.1.1`，提交锁文件确保可复现。

备选 B 是升级到已修补的 Vite 6/7：跨版本跨度较小，但仍保留两套 Vite 和转换链，后续维护成本更高。备选 C 是仅覆盖 esbuild：无法修复 Vite 自身漏洞，且有 peer 不兼容风险，不采用。

## 兼容性与安全约束

- 现有 jsdom 30.0.1 要求 Node `^22.22.2 || ^24.15.0 || >=26.0.0`；将 package engines 和 README 对齐此实际约束。本机 24.17.0 符合，CI 和可选 Docker 继续使用 Node 22 最新补丁。
- 保留当前 JS 构建目标 `['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14']`，不因 Vite 默认值变化无意提高目标。目标转译不等同于对所有旧浏览器 API 和视觉行为的完整兼容承诺。
- 开发和预览默认绑定 `127.0.0.1`，不向局域网开放。保留 `/api → http://127.0.0.1:9000`；接口测试使用本机随机端口的受控响应服务，不触碰业务后端。
- 用项目真实 Vite 配置运行测试，验证 TSX 编译、HTTP 代理路径/参数传递、普通 `.env` 拒绝访问、Windows NTFS 路径变体不能泄露合成文件。只使用临时目录里的公开测试字符串，绝不请求真实 `.env`。
- 本地质量脚本和 CI 使用全量 `npm audit`，不再只检查 `--omit=dev`；另加 `npm ls --all` 检查无效依赖树，保留独立生产依赖审计结果用于验收说明。

## 验收与回退

先运行新增运行时测试和全量审计，记录旧版本失败；升级后必须通过新增工具链测试、前端全部单测、生产构建、40 项浏览器测试、实际 SQLite HTTP 流程、全量审计和依赖树检查，再执行完整非 Live 质量脚本。只修复本次变更引出的兼容问题，不通过跳过测试或过滤安全告警达标。

在已有 `codex/stage0-reliability` 隔离工作区实施。确认 main 干净后快进合入，主目录按锁文件重新安装、构建、验证；保留工作分支，不推送。失败时保留 main 现有可用构建并报告具体问题，不做强制依赖修复或数据库回滚。

## 核对来源

- [Vite 8 官方迁移](https://vite.dev/guide/migration)：转换链、CSS 压缩与默认浏览器目标变化。
- [Vite 6 迁移](https://v6.vite.dev/guide/migration)、[Vite 7 迁移](https://v7.vite.dev/guide/migration)：跨版本变化；本项目无 SSR、自定义 Babel、Sass 或 Rollup 插件配置。
- [React 插件官方说明](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md)。
- [Windows 文件拒绝规则绕过公告](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff)。
- npm 元数据确认 Vite 8.2.2、插件 6.1.1 为当前稳定版本；插件额外 Babel/Compiler peer 均为可选，本项目不安装。
