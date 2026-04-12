# 参数基础文件（Param Registry）

## 目的
- 提供跨策略统一变量命名的唯一来源。
- 你维护这份文件中的变量定义，AI 仅从中读取可用变量名。

## 文件位置
- Studio: `studio/api/data/param_registry.json`
- Freqtrade 镜像: `freqtrade/user_data/param_registry.json`

## 命名规范
- 标准: `<Factor>_<Indicator>_<Property>`
- 示例: `Matrix_baseEMA_len`
- 校验正则: `^[A-Z][A-Za-z0-9]*_[a-z][A-Za-z0-9]*_[a-z][A-Za-z0-9_]*$`

## 文件结构示例

```json
{
  "naming_standard": "<Factor>_<Indicator>_<Property> 例如 Matrix_baseEMA_len",
  "key_regex": "^[A-Z][A-Za-z0-9]*_[a-z][A-Za-z0-9]*_[a-z][A-Za-z0-9_]*$",
  "variables": {
    "Matrix_baseEMA_len": {
      "type": "int",
      "description": "基准EMA周期",
      "default": 144,
      "min": 1,
      "max": 2000
    }
  },
  "updated_at": "2026-04-12T00:00:00Z"
}
```

## 生效方式
- 模块生成和策略封装时，后端会把 registry 注入 AI prompt。
- AI 被约束为仅使用 registry 中定义的变量名。
- `pair_profiles.json` 保存时会校验变量名是否存在于 registry。
