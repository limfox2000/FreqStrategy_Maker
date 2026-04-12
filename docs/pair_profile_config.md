# Pair Profile 配置说明

## 目标
- 将参数从策略类内迁移到交易对配置文件。
- 策略读取顺序:
  1. 完整交易对键，例如 `XRP/USDT:USDT`
  2. 去结算后缀键，例如 `XRP/USDT`
  3. 基础币种键，例如 `XRP`
  4. `defaults`
  5. 策略代码中的硬编码默认值

## 配置文件
- Studio 存储: `studio/api/data/pair_profiles.json`
- Freqtrade 运行时镜像: `freqtrade/user_data/pair_profiles.json`

文件结构:

```json
{
  "defaults": {
    "base_ema_len": 169
  },
  "pairs": {
    "XRP": {
      "base_ema_len": 144
    },
    "XLM": {
      "base_ema_len": 444
    }
  },
  "updated_at": "2026-04-12T00:00:00Z"
}
```

## 后端 API
- `GET /api/pair-profile`
- `PUT /api/pair-profile`

注意:
- `pair-profile` 的变量键会校验 `param_registry.json`。
- 如果报错 `undefined variables`，请先在参数基础文件中声明对应变量。

请求体:

```json
{
  "defaults": {
    "base_ema_len": 169
  },
  "pairs": {
    "XRP": {
      "base_ema_len": 144
    }
  }
}
```

## 策略侧读取
- helper 文件:
  - `freqtrade/user_data/strategies/pair_profile_helper.py`
  - `freqtrade/user_data/strategies/generated/pair_profile_helper.py`
- 常用函数:
  - `get_pair_value(pair, key, default)`
  - `get_pair_int(pair, key, default)`
  - `get_pair_float(pair, key, default)`

## Studio 前端
- 顶部工具栏新增: `交易对属性配置`
- 支持:
  - 编辑默认属性 JSON
  - 新增/删除交易对条目
  - 为每个交易对编辑属性 JSON
  - 保存后自动同步到 Freqtrade 镜像文件
