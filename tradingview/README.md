# TradingView Workspace (Pine Script)

## Purpose

This folder is dedicated to **TradingView Pine Script** strategy/indicator experiments.
It is used for quick validation of ideas on TradingView.

## Scope Boundary

1. This folder is **independent** from the `freqtrade` strategy system in this repository.
2. Files here should not be imported by, coupled with, or treated as part of `freqtrade` runtime.
3. `freqtrade/` and `studio/` changes are not required when only working on TradingView scripts.

## AI Collaboration Rules

1. When asked to generate Pine Script, prefer writing files under `tradingview/`.
2. Do not assume Pine Script logic must map to `IStrategy` or Python code.
3. Do not modify `freqtrade` or `studio` unless the user explicitly asks for cross-system integration.

## Suggested Naming

- Strategy files: `*.strategy.pine`
- Indicator files: `*.indicator.pine`
- Notes: `*.md`
