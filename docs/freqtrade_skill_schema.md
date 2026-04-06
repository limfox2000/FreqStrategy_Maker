# freqtrade-skill 接口与 Schema

## 1. 设计原则

1. Skill 只负责 freqtrade 相关能力，不做通用 Agent 执行。
2. 所有输入输出结构化，避免自由文本耦合。
3. 每次请求返回可追踪 `version_id` 或 `job_id`。

## 2. API 概览

1. `POST /api/module/generate`
2. `POST /api/strategy/compose`
3. `POST /api/backtest/run`
4. `GET /api/backtest/{job_id}/result`

## 3. Schema 细节

### 3.1 生成模块代码

`POST /api/module/generate`

Request:

```json
{
  "card_type": "indicator_factor",
  "requirement": "EMA20上穿EMA60且RSI从30向上回升时做多，允许做空",
  "context": {
    "timeframe": "5m",
    "pair": "XRP/USDT:USDT",
    "can_short": true
  }
}
```

Response:

```json
{
  "version_id": "mod_20260404_001",
  "card_type": "indicator_factor",
  "module_code": "def populate_indicators(...): ...",
  "params": {
    "ema_fast": 20,
    "ema_slow": 60,
    "rsi_threshold": 30
  },
  "explain": "基于均线趋势和RSI回升触发入场。"
}
```

### 3.2 合成策略

`POST /api/strategy/compose`

Request:

```json
{
  "strategy_name": "AssembleStrategyV1",
  "base": {
    "timeframe": "5m",
    "can_short": true
  },
  "modules": {
    "indicator_factor_version_id": "mod_20260404_001",
    "position_adjustment_version_id": "mod_20260404_002",
    "risk_system_version_id": "mod_20260404_003"
  }
}
```

Response:

```json
{
  "build_id": "build_20260404_001",
  "strategy_file": "g:/Trading/FreqStrategy_Maker/freqtrade/user_data/strategies/generated/AssembleStrategyV1.py",
  "lint_ok": true,
  "warnings": []
}
```

### 3.3 执行回测

`POST /api/backtest/run`

Request:

```json
{
  "build_id": "build_20260404_001",
  "pair": "XRP/USDT:USDT",
  "timeframe": "5m",
  "timerange": "20251220-20260306"
}
```

Response:

```json
{
  "job_id": "bt_20260404_001",
  "status": "queued"
}
```

### 3.4 获取回测结果

`GET /api/backtest/{job_id}/result`

Response:

```json
{
  "job_id": "bt_20260404_001",
  "status": "finished",
  "summary": {
    "trades": 211,
    "winrate": 34.6,
    "profit_total_pct": -7.389,
    "max_drawdown_pct": 9.299,
    "profit_factor": 0.425
  },
  "series": {
    "kline": [],
    "markers": [],
    "equity": [],
    "drawdown": []
  },
  "artifacts": {
    "strategy_file": "g:/Trading/FreqStrategy_Maker/freqtrade/user_data/strategies/generated/AssembleStrategyV1.py",
    "result_dir": "g:/Trading/FreqStrategy_Maker/freqtrade/user_data/backtest_results"
  }
}
```

## 4. 最小 JSON Schema（示例）

```json
{
  "$id": "module.generate.request",
  "type": "object",
  "required": ["card_type", "requirement", "context"],
  "properties": {
    "card_type": {
      "type": "string",
      "enum": ["indicator_factor", "position_adjustment", "risk_system"]
    },
    "requirement": {
      "type": "string",
      "minLength": 5
    },
    "context": {
      "type": "object",
      "required": ["timeframe", "pair", "can_short"],
      "properties": {
        "timeframe": { "type": "string" },
        "pair": { "type": "string" },
        "can_short": { "type": "boolean" }
      }
    }
  }
}
```

## 5. 约束建议

1. 策略代码生成后执行 AST 白名单检查。
2. 禁止危险导入和系统级执行调用。
3. 回测命令参数必须由后端组装，前端不可直接拼接命令。

