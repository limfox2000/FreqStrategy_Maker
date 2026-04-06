# Freqtrade Strategy Studio MVP 目录结构与实施步骤

## 1. 推荐目录结构

```text
g:/Trading/FreqStrategy_Maker/
  docs/
    README.md
    freqtrade_strategy_studio_研发落地方案.md
    freqtrade_strategy_studio_MVP目录结构与实施步骤.md
    freqtrade_skill_schema.md
  studio/
    web/                               # React + R3F 前端
      src/
        pages/
          WorkbenchPage.tsx
          BacktestPage.tsx
        modules/
          cards/
            IndicatorCard.tsx
            PositionCard.tsx
            RiskCard.tsx
          workspace/
            StrategyScene.tsx
            ModuleNode.tsx
            ConnectorLine.tsx
          charts/
            KlineChart.tsx
            EquityChart.tsx
            DrawdownChart.tsx
        store/
          strategyStore.ts
        api/
          client.ts
    api/                               # FastAPI 后端
      app/
        main.py
        routers/
          module.py
          strategy.py
          backtest.py
        services/
          freqtrade_skill.py
          strategy_composer.py
          backtest_runner.py
          result_parser.py
        schemas/
          module.py
          strategy.py
          backtest.py
  freqtrade/
    user_data/
      strategies/
        generated/                     # 合成后的策略文件
      backtest_results/                # freqtrade 回测输出
```

## 2. 开发步骤（按依赖顺序）

### 第 1 步：初始化工程

1. 创建 `studio/web` 与 `studio/api`。
2. 前端初始化 React + TypeScript + Vite。
3. 后端初始化 FastAPI + Uvicorn。

### 第 2 步：打通前端卡片工作台

1. 实现三卡片基础 UI：`指标因子`、`仓位调整`、`风险系统`。
2. 接入 R3F 场景，支持卡片拖拽和选中。
3. 建立 Zustand 状态：卡片内容、版本、锁定状态。

### 第 3 步：实现 freqtrade-skill 核心接口

1. `POST /api/module/generate`
2. `POST /api/strategy/compose`
3. `POST /api/backtest/run`
4. `GET /api/backtest/{job_id}/result`

### 第 4 步：接入 freqtrade 回测执行

1. 策略文件落盘到 `freqtrade/user_data/strategies/generated`。
2. 调用 `freqtrade backtesting`。
3. 解析 `backtest_results` 产物并返回指标与序列。

### 第 5 步：可视化闭环

1. K 线 + 买卖点渲染。
2. 权益曲线与回撤曲线。
3. 交易明细表格与统计面板。

### 第 6 步：稳定性与体验优化

1. 回测任务日志流和失败重试。
2. 策略版本快照和一键回滚。
3. 常用参数模板和最近一次配置恢复。

## 3. MVP 完成定义（DoD）

1. 用户可以在单页中完成“写需求 -> 生成模块 -> 合成策略 -> 回测 -> 看图”。
2. 回测参数（交易对、timeframe、timerange）可配置且可重复执行。
3. 每次回测结果可追溯到对应的卡片版本组合。

