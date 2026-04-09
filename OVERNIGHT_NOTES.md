# 夜间迭代笔记 - 2026-04-10

我趁你睡觉做了一轮大迭代。13 commits in Round 3，27 个 wave。下面是你早上需要知道的全部。

## 你最需要先看的 3 件事

### 1. 鼠标已恢复正常 + 文字页可读性修了
- 你之前讨厌的自定义光标已彻底移除（含防御性清理 CDN 缓存的旧版）
- 学习页 5 个文字页加了 `data-bg-mode="quiet"` —— 背景动画自动减半 + 内容卡更不透明 + serif 字体阅读

### 2. 全站新增功能（按 ⌘K / ? / ⌘, 体验）
- **⌘K** —— 命令面板（Linear/Raycast 风），全站任意页面打开
- **?** —— 键盘快捷键面板
- **⌘,** —— 设置抽屉（主题/背景模式/动效强度/语言）
- 顶部 nav 右侧自动注入 3 个图标按钮：🔍 ⌨️ ⚙
- 首次访问会弹一个 7s 引导 toast 介绍这些

### 3. 8 个核心页面统一了 hero 风格
每个页面都有：
- mono 字体 eyebrow + 脉冲色点
- 48-64px Manrope display 大字（白→70% 渐变）
- 15-18px sub 描述
- 部分页面有 CTA 按钮

页面：dashboard / trade / market(跳过,终端布局) / platforms / community / analysis / home / team

---

## 文件清单（新增）

### CSS（5 个，~40 KB）
| 文件 | 内容 |
|---|---|
| `tokens.css` | 多字体系统 + 4 级文字色 + 间距/圆角 token + 内容窗宽 |
| `base.css` | reset + body bg + serif 长文字体 + noise overlay + 文字页可读性 |
| `nav.css` | header/nav/sidebar/footer + 响应式 |
| `components.css` | panel/card/btn/badge/empty/skeleton + focus/microinteractions |
| `animations.css` | 18 keyframes + utility classes |

### JS（14 个文件，~228 KB raw）
| 文件 | 大小 | 功能 |
|---|---|---|
| `common.js` | 9.6 KB | sidebar/auth/nav/lucide/nav-tools/first-visit-hint |
| `motion.js` | 8.4 KB | cqAnimateNumber/cqUpdateNumber/cqSparkline/tilt/reveal |
| `ui-kit.js` | 11.8 KB | cqToast/cqDialog/cqConfirm/cqAlert |
| `command-palette.js` | 13 KB | ⌘K 全局命令面板 |
| `keyboard-shortcuts.js` | 8.3 KB | ? 快捷键面板 |
| `settings-drawer.js` | 14.8 KB | ⌘, 设置抽屉 |
| `footer.js` | 8.7 KB | 4 列 footer 自动注入 |
| `aurora.js` | 5.8 KB | 8 极光光团（z-index -3） |
| `grid-dots.js` | 6.7 KB | Linear 风点阵（z-index -2，移动端关） |
| `pixel-sand.js` | 6.6 KB | 像素流沙粒子（z-index -1，移动端关） |
| `view-transitions.js` | 3.1 KB | Chrome 平滑切页 |
| `magnet-cursor.js` | 2.8 KB | 仅磁吸效果（自定义光标已删） |
| `reading-progress.js` | 4.4 KB | 文字页顶部进度条 + 返回顶部 |

---

## Round 3 - 27 个 Wave 完整清单

| Wave | 内容 |
|---|---|
| 1 | Typography Revolution — Inter/Manrope/Source Serif/JetBrains Mono 多字体系统 + 4 级文字色 + 紫调深空 bg |
| 2 | UI Kit — toast/dialog/confirm/alert |
| 3 | UI Kit 全站接入 |
| 4 | 时间感知问候（早安/上午好/下午好/晚上好/夜深了 6 时段）|
| 5 | ⌘K 命令面板（Linear/Raycast 风，15 个命令，模糊匹配，键盘导航）|
| 6 | 移动端背景性能优化（grid-dots/pixel-sand 在 ≤768px 自动关）|
| 7 | empty state + skeleton screens 升级 |
| 8 | 数字 tabular nums + flash 效果 |
| 9 | qnav grid 响应式（4→2→1 列）|
| 10 | 修复 6 个页面 alert("即将上线") 链接（直接跳 learn_*.html）|
| 11 | reading-progress.js — 文字页顶部进度条 + 返回顶部按钮 |
| 12 | 全站统一新 footer（4 列布局 + 渐变线 + 状态点）|
| 13 | dashboard 离线/未登录态升级（带 CTA 的 empty state）|
| 14 | keyboard-shortcuts.js — 按 ? 弹出快捷键面板 |
| 15 | dashboard hero v4 — 左文 + 右 SVG 金融图表插画 |
| 16 | settings-drawer.js — 右滑设置 + nav 工具栏自动注入 |
| 17 | 首次访问引导 toast |
| 18 | trade.html hero（黄色脉冲 + 大字"三市场零风险练手"）|
| 19 | platforms + community hero |
| 20 | analysis.html hero（青色脉冲 + "MULTI-AGENT AI"）|
| 21 | home.html hero |
| 22 | team.html hero（暖橙脉冲）|
| 23 | dashboard KPI 数据条（4 个指标：3 市场 / 6 智能体 / 280K 资金 / 0% 风险）|
| 24 | qnav 4 卡按色彩主题独立 hover 发光（青/紫/橙/薄荷）|
| 25 | trade submitOrder 加 cqToast 反馈 |
| 26 | dashboard 替换浏览器 alert/confirm → cqDialog/cqConfirm |
| 27 | 字体加载优化 |

---

## 已部署到 HK 服务器

所有 commit 都已 push 到 main 分支并在 HK `/opt/CampusQuant-Agent` 部署。
最新 commit `2a304c5`。

## Cloudflare 缓存

如果你打开 https://campusquant.store 看到旧版本：
- **方式 A**：Cloudflare 控制台 → Caching → Configuration → **Purge Everything**
- **方式 B**：开 Development Mode 临时绕过 3 小时
- 浏览器一定要 Ctrl+Shift+R 强刷

## 已知问题 / 下一步建议

### 性能
- 14 个 JS 文件 = 14 个 HTTP 请求 = 首次加载偏慢
- 建议：用 esbuild 打包成 1 个 bundle.min.js（~50KB gzipped）
- 暂时没做因为不想引入构建步骤

### 还可以做
1. **明亮模式** —— 占位已做，需要全套色彩重写
2. **Trade 页 SSE 节点流光管道** —— 如果 trade.html 真有 SSE 流
3. **Real demo data** —— 未登录时显示一些"假"持仓让 dashboard 更生动
4. **市场页 bloomberg 化** —— 数据密度更高
5. **首页可点击 ⌘K 引导动画**

### 跳过的页面
- **market.html** — 终端定高布局，不能加 hero 段（会破坏）
- **resources.html / learn_*.html** — additive 模式，没有强制重构

---

## 你测试时建议的检查点

1. https://campusquant.store/dashboard.html → 大 hero + KPI 条 + qnav 4 色 + sparkline
2. 按 ⌘K → 命令面板
3. 按 ? → 键盘快捷键
4. 按 ⌘, → 设置抽屉
5. 点 nav 右侧 ⚙ 也能开设置
6. https://campusquant.store/learn_basics.html → serif 字体 + 顶部进度条 + 静背景
7. https://campusquant.store/auth.html → 大字 logo + 渐变描边卡
8. 任意页面滚到底 → 新 4 列 footer
9. 任意页面切换页面 → 平滑 fade（不再白屏）
10. trade.html 提交订单 → 右上角 toast + confetti

---

睡得好。
