# SectorPulse Design System

## Direction

SectorPulse 使用面向高频运营与研究工作的柔和蓝白视觉世界。界面像一张清洁、校准良好的工作台：暖白背景降低疲劳，白色表面承载任务，清透蓝色只标记交互和当前状态，细蓝灰描边承担主要层级。用户已经明确选择这一方向，它优先于概念随机化结果。

## Mode and Density

- Surface mode: `Operate`。
- 总览、新建流程和空状态采用 `comfortable` 密度。
- 行情、新闻、证据、运行详情、审核和管理表格采用 `compact` 密度。
- 不通过堆叠卡片制造层级；摘要优先使用连续分栏带，长列表优先使用表格或结构化行。

## Palette

- Page background: `#f5f8fd`，柔和蓝白。
- Surface: `#ffffff`。
- Subtle surface: `#f8faff`。
- Primary: `#1768f2`。
- Primary hover: `#0e5de0`。
- Primary soft: `#eaf2ff`。
- Text: `#10213d`。
- Secondary text: `#455873`。
- Muted text: `#596b85`（普通辅助文字在页面背景上至少 4.5:1）。
- Border: `#dbe5f3`。
- Strong border: `#cbd9ed`。
- Success: `#159a63`；Warning: `#d98200`；Danger: `#bf3345`。成功/警告色用于图标与语义背景；小号正文优先深色文字，不能仅靠颜色表达状态。

状态色只承担语义，不替代文本标签。除状态色外，全站只有蓝色作为交互强调色。

## Typography

使用系统无衬线字体栈，不依赖网络字体。正文 14px/1.6；辅助信息 12–13px；面板标题 16–18px；页面标题 28–32px。数字、短 ID 和技术状态可使用系统等宽字体。标题近黑且紧凑，正文保持舒适行长，数据区域不使用营销式超大字号。

## Shape and Depth

- Inputs and small controls: 10–12px radius。
- Panels and cards: 16px radius；comfortable 内边距 24px，compact 18px。
- Dialogs: 22px radius。
- Status badges: pill radius。
- Cards rely on 1px borders; shadow is optional and always blue-tinted, never heavy black.
- Buttons are 40px high on desktop and at least 44px on narrow screens.

## Application Shell

Desktop sidebar is 232px with grouped navigation and one consistent outline icon family. Top bar is 68px and does not repeat unnecessary brand content. Retain the existing independent navigation/content scroll regions and responsive shell.

## Components

- `PageHeader`: title, concise description, optional timestamp and one primary action.
- `Panel`: comfortable or compact density, named region semantics.
- `MetricCard`: one icon, label, dominant value, supporting sentence and optional progress.
- `SummaryStrip`: 4–6 metadata cells in one continuous bordered surface.
- `StatusBadge`: Chinese label plus stable semantic tone.
- `InlineAlert`: object, reason and recovery action in one alert region.
- `InlineAlert` uses a 20px icon column, flexible text column and semantic tinted background; recovery actions stay next to the message.
- Runtime values distinguish recorded zero, missing data, inapplicable metrics and pending metrics. Unknown provider/status/error codes remain inspectable; never invent a successful result.
- Recent-run filters live in the URL, with explicit loaded-record scope. Finished data collection details default closed while warnings remain outside. Review focus mode hides panes without unmounting the editor; chapter navigation and return-reason disclosure preserve draft safeguards.
- Tables: light header, horizontal separators, 44–56px rows and horizontal scrolling on narrow screens.
- Tabs: real `tablist`/`tab`/`tabpanel` semantics and visible selected/focus states.

## Motion

Motion is limited to 140–240ms state transitions for navigation, dialogs and feedback. Animate opacity and transform only. Long-running operations communicate through text, timestamps and progress state rather than decorative animation. Respect `prefers-reduced-motion`.

## Responsive Behavior

- `>=1280px`: full sidebar and multi-column layouts.
- `960–1279px`: reduced gutters and two-column metrics.
- `720–959px`: off-canvas navigation and stacked review workspace.
- `<720px`: one-column layouts, 44px controls and horizontally scrollable wide tables.

## Accessibility

Every control has a visible focus ring and accessible name. Status never relies only on color. Dialogs restore focus and close with Escape. Live updates avoid interruptive announcements. Keyboard order follows visual order.

## Prohibited Patterns

No mascot, cartoon, flowers, clouds, Emoji, glassmorphism, decorative gradients, dark-theme section flips, heavy shadows, hidden field labels, three-level nested cards, multiple primary actions in one region, or invented financial claims.

## Source of Truth

Detailed reusable tokens and patterns live in `docs/design/soft-blue-operations-ui-system.md`. Project page structure and acceptance boundaries live in `docs/superpowers/specs/2026-08-26-sectorpulse-soft-blue-ui-redesign-design.md`. This file is the concise visual authority future UI work must inherit.
