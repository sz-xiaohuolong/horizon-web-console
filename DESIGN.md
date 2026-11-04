---
name: "Horizon 控制台设计系统"
description: "以真实流水线、条目检查与日志排错为中心的个人本地操作台。"
colors:
  accent: "oklch(82% 0.15 80)"
  accent-ink: "oklch(18% 0.04 75)"
  accent-hover: "oklch(88% 0.13 80)"
  accent-soft: "oklch(29% 0.05 80)"
  accent-border: "oklch(43% 0.06 80)"
  cool: "oklch(77% 0.12 245)"
  cool-soft: "oklch(29% 0.05 245)"
  paper: "oklch(17% 0.008 250)"
  paper-2: "oklch(21% 0.009 250)"
  paper-3: "oklch(13.5% 0.007 250)"
  header: "oklch(18.5% 0.008 250)"
  ink: "oklch(95% 0.005 250)"
  ink-2: "oklch(83% 0.008 250)"
  muted: "oklch(71% 0.01 250)"
  rule: "oklch(31% 0.01 250)"
  rule-2: "oklch(42% 0.012 250)"
  focus: "oklch(82% 0.15 80)"
  ok: "oklch(76% 0.15 150)"
  ok-soft: "oklch(24.5% 0.03 150)"
  ok-border: "oklch(36% 0.045 150)"
  bad: "oklch(70% 0.17 25)"
  bad-soft: "oklch(24.5% 0.035 25)"
  bad-border: "oklch(38% 0.055 25)"
  qr-paper: "oklch(99% 0.005 85)"
typography:
  display:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.728rem"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  section:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "-0.01em"
  body:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  caption:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "normal"
  metric:
    fontFamily: "\"SFMono-Regular\", Consolas, \"Liberation Mono\", ui-monospace, monospace"
    fontSize: "36px"
    fontWeight: 400
    lineHeight: 1.25
    letterSpacing: "normal"
  log:
    fontFamily: "\"SFMono-Regular\", Consolas, \"Liberation Mono\", ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.8
    letterSpacing: "normal"
  reading:
    fontFamily: "\"Host Grotesk\", \"PingFang SC\", \"Microsoft YaHei\", ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.9
    letterSpacing: "normal"
rounded:
  badge: "4px"
  pill: "6px"
  card: "10px"
spacing:
  3xs: "2px"
  2xs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "40px"
  2xl: "64px"
  20: "20px"
  28: "28px"
  32: "32px"
  36: "36px"
  44: "44px"
  48: "48px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  button-secondary:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  input-field:
    backgroundColor: "{colors.paper-3}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "8px 12px"
    width: "100%"
  navigation:
    backgroundColor: "{colors.header}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    padding: "0 16px"
  badge:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.badge}"
    padding: "2px 8px"
  pipeline-stage:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    padding: "16px 24px"
  pipeline-panel:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "24px 24px 0"
---

# Horizon 控制台设计系统

## 概述

**设计主张：“可检查的流水线，克制的操作台”**

石墨灰表面、细线分区、琥珀色操作和冷蓝色数据，共同构成面向日常观测的 Console 界面。采集、评分、筛选、补充四个阶段串联真实工件，条目列表和日志帮助用户追查结果与失败原因。

本规范约束个人本地 Horizon 控制台，沿用 Hallmark 2.0.0 Console 主题（第 2/3 个候选）与 Impeccable Operate 方向。产品上下文见 [PRODUCT.md](PRODUCT.md)，实现 token 以 `web/src/tokens.css` 为事实源；本次提取记录实际组件与最终覆盖值，后续修改须同步更新。

**主要特征：**

- 可选择的流水线阶段是核心识别特征，检查真实条目及评分原因。
- 平面表面与细线建立层次，数据表优先于重复指标卡。
- 颜色、文字、图标共同表达状态，缺失数据保留为未知。
- 桌面检查与手机速览使用同一套中文控件与信息顺序。

## 颜色

前置 token 保留项目实际使用的 OKLCH 值。页面和次级表面带有轻微冷色，文字从正文、次级正文到辅助文字逐级减弱；边界分为区域细线和更清晰的控件描边。二维码保留独立的浅色纸面，以便扫码。

| 颜色角色 | token | 使用位置 |
|---|---|---|
| 主信号 | `accent`、`accent-ink`、`accent-hover` | 主按钮、当前阶段、悬停反馈 |
| 次级信号 | `cool`、`cool-soft` | 评分、日志级别与数据强调 |
| 中性表面 | `paper`、`paper-2`、`paper-3`、`header` | 页面、面板、输入或日志、顶部导航 |
| 文字与边界 | `ink`、`ink-2`、`muted`、`rule`、`rule-2` | 正文层级、区域边界与表单轮廓 |
| 语义状态 | `ok`、`bad` 及对应浅底与边界 | 完成、失败及错误提示 |
| 特殊用途 | `focus`、`qr-paper` | 键盘焦点、二维码纸面 |

**单一信号规则。** 琥珀色留给主动作、当前阶段和键盘焦点；冷蓝色用于评分与日志级别。成功、错误均同时提供明确文字，不能只靠颜色判断。

## 字体

Host Grotesk 的常规与中等字重由前端本地依赖载入；中文依次回退到苹方、微软雅黑和系统无衬线字体。页面标题、正文、标签与辅助文字保持清晰级差，中文页面不使用字母式全大写标签。

页面标题使用 `display`，分区标题使用 `section`；普通正文使用 `body`，控件标签使用 `label`。流水线数量使用 `metric`，日志使用 `log`；速递长文使用 `reading`，行长上限为 75ch。手机页面标题调整为 26px，输入字号至少 16px。

**数据字形规则。** 通用界面使用无衬线字体；日志、时间、编号与实测数值使用等宽字体和等宽数字。缺失指标显示“未记录”或“—”，不将缺失替换为零。

## 布局

内容居中，最大宽度为 1440px。常用间距以 4/8px 节奏组织，信息块之间使用 24px、32px 或 40px 的已用尺度。默认桌面外侧留白为 64px；宽度不大于 1200px 时为 32px，手机不大于 640px 时为 18px；不小于 1600px 时采用实现中的 48px 留白。

顶部提供观测台、运行记录、历史速递、配置、微信连接五个目的地。观测台以四阶段流水线为首要区域；运行记录采用列表与检查器并列，日志区域独立滚动。视口不大于 960px 时，顶部导航独占一行并可横向滚动，检查区按阅读顺序堆叠。手机流水线变为两列，导航保留文字并隐藏辅助图标；数据表独立横向滚动，页面本身不出现横向溢出。

当前页面、运行、阶段、搜索和筛选使用 URL 参数保持上下文。配置采用先修改、再保存的顺序，明确未保存、校验失败与冲突恢复；扫码连接按主动开始、扫码确认、发送首条消息的顺序组织。

## 层次与深度

**平面层次规则。** 默认无阴影。页面、操作面与输入或日志面依靠表面明度、间距和一像素边界区分，不增加发光或浮起效果。

独立面板使用操作面，中性底色围绕内容。日志和输入使用更深的表面；状态提示使用语义色的浅底与边界。高亮只表达选择、操作或状态，不承担装饰性的视觉重量。

## 形状

控件使用轻微圆角（6px），独立面板使用更宽的圆角（10px），状态标记使用紧凑圆角（4px）。区域边界为一像素细线。流水线采用直线分段与短下划线，当前阶段通过文字色、下划线和选择语义共同表达。

桌面常规按钮和输入最小高度为 40px；手机常规按钮、图标按钮与输入最小高度为 44px。流水线阶段保留完整数据选择区域，随信息内容增长，不压缩成普通按钮的高度。

## 组件

- **按钮：** 主按钮使用琥珀色底与深色文字，次按钮使用操作面与清晰描边；悬停改变表面，按下仅下移一像素。禁用时降低透明度并使用不可用光标，处理中保留文字与忙碌语义。
- **输入：** 深色表面、清晰边界与显式标签。悬停提升边界对比，焦点使用即时两像素轮廓，内偏移三像素；验证错误与对应输入关联。手机输入保持易读字号。
- **顶部导航：** 当前页使用正文色和琥珀色下边界，同时设置 `aria-current`。桌面保持五个文字目的地，窄屏通过独立一行与横向滚动维持可达性。
- **状态标记：** 采用紧凑的文字与语义色组合。完成、运行中、失败和未记录各有明确文字；标记本身不承担点击行为，不添加悬停或按压反馈。
- **流水线：** 四个阶段都是原生按钮，可用时检查对应工件；缺少工件且非当前阶段时禁用。选择通过 `aria-pressed`、文字与短下划线呈现，数量与耗时均来自实际记录。
- **面板与内容：** 分区标题与边界先建立层次，再放置流水线、表格或阅读内容。空态说明缺少什么以及下一操作，加载占位保留区域形状，错误区提供重试。

所有交互都有显式键盘焦点；按钮和链接的轮廓外偏移三像素，焦点不做过渡。常规状态变化使用 120ms 的颜色或边界过渡；支持减少动态效果设置。组件预览见 `.impeccable/design.json`，为从实现提取的静态 HTML/CSS，不模拟 API 行为。

## 建议与禁忌

**建议：**

- 沿用现有 token，新增页面保持同一套字体、边界与状态语言。
- 保留加载、空、错误和完整状态；错误提供重试，配置草稿在失败后继续保留。
- 使用显式标签、即时焦点和原生禁用语义；长标题、ID 与 URL 允许换行。
- 以真实工件和实际验证记录支持完成声明，视觉检查证据统一维护在 `docs/web-console/VERIFICATION.md`。

**禁忌：**

- 不添加营销首屏、装饰性图表或虚构的运行指标。
- 不使用渐变、发光、浮动或加载入场动画强化操作台。
- 不把推断的筛除原因、估算额度或缺失的历史状态显示成确定事实。
- 不在 Markdown 中执行 HTML；不接受危险协议链接。

## 报告推送交互

历史正文上方提供“推送到微信”。预览在原位展开，列出完整报告的分段数、估算额度和确认/取消按钮；取消不发送，确认后显示发送结果。新版报告或切换报告会清除旧预览，失败不自动重试。沿用现有按钮、提示和表面 token，手机按钮保持至少 44px 高，操作组允许换行。
