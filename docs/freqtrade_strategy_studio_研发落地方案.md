# Freqtrade Strategy Studio 研发落地方案

## 1. 目标

构建一个轻量化的策略开发系统，满足以下核心诉求：

1. 前端以 `React + Three.js (R3F)` 为中心，提供卡片式策略构建体验。
2. 策略底座固定为 `freqtrade`，策略生成与回测全部围绕 freqtrade 执行。
3. AI 通过单一 `freqtrade-skill` 生成策略模块代码并完成合成。
4. 回测结果可视化采用 `TradingView Lightweight Charts`。

## 2. 需求边界

### 包含

1. 三类策略模块卡片：`指标因子`、`仓位调整`、`风险系统`。
2. 模块需求输入、AI 代码生成、模块版本管理。
3. 三卡合成为完整 freqtrade 策略文件。
4. 指定交易对、timeframe、回测区间的一键回测。
5. 回测可视化（K 线、买卖点、权益曲线、回撤曲线、交易明细）。

### 不包含

1. 实盘交易执行与风控审批流程。
2. 分布式多机回测调度。
3. 跨交易所策略统一编排。

## 3. 总体技术架构

```text
React App (UI Shell + R3F Workspace + Charts)
    -> FastAPI (Module/Strategy/Backtest APIs)
        -> freqtrade-skill (生成模块/合成策略/执行回测/解析结果)
            -> freqtrade runtime (docker or local)
Storage: SQLite + local files
```

## 4. 前端架构（重点）

1. `UI Shell (DOM)`：顶部工具栏、右侧参数与代码面板、底部任务日志。
2. `R3F Workspace`：模块卡拖拽、吸附、连线、状态可视化。
3. `State`：`Zustand + Immer` 管理卡片状态、版本、任务、图表数据。
4. `Charts`：`Lightweight Charts` 展示 K 线、买卖点、权益、回撤。

设计原则：

1. 单页闭环，减少页面跳转。
2. 3D 只承载“模块装配”，复杂表单仍使用 DOM。
3. 低干扰视觉，重点突出“模块职责”和“测试反馈”。

## 5. 后端与 Skill 设计

后端采用单体 `FastAPI`，核心由 `freqtrade-skill` 驱动：

1. `generate_module`：按卡片类型生成代码片段。
2. `compose_strategy`：将三卡合成为完整策略类。
3. `run_backtest`：执行 `freqtrade backtesting`。
4. `parse_backtest`：解析回测结果并输出图表序列数据。

## 6. 关键流程

1. 用户编辑三类卡片需求。
2. AI 逐卡生成代码，用户可锁定版本。
3. 点击“合成策略”，生成策略文件到 `user_data/strategies/generated/`。
4. 用户填写回测参数后点击“测试”。
5. 后端异步执行回测并通过 WebSocket 推送日志。
6. 前端接收结果并渲染图表与统计指标。

## 7. 研发阶段计划

1. 阶段 A：前后端基础工程与目录搭建。
2. 阶段 B：R3F 装配台 MVP（拖拽、选中、连线、状态）。
3. 阶段 C：freqtrade-skill（模块生成 + 策略合成）。
4. 阶段 D：回测执行、日志流、结果解析。
5. 阶段 E：图表可视化与联动交互。
6. 阶段 F：稳定性优化、文档与验收。

## 8. 验收标准（MVP）

1. 三张卡可独立生成可用模块代码。
2. 三卡可合成有效的 freqtrade 策略文件。
3. 可按指定 `pair + timeframe + timerange` 成功回测。
4. 图表完整展示 K 线、买卖点、权益与回撤。
5. 支持卡片版本回退与历史策略快照复现。

## 9. 风险与控制

1. AI 代码不稳定：采用模板化生成 + AST 校验 + 失败回退。
2. 回测耗时影响体验：采用异步任务 + 日志流 + 结果缓存。
3. 3D 复杂度过高：限制 3D 职责，只做装配表达，不承载复杂输入。

