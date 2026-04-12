import type {
  AiModelsResponse,
  BacktestResult,
  CardType,
  ModuleCardType,
  PairProfileResponse,
  ComposeResponse,
  PersonaResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`无法连接后端接口 (${API_BASE}${path})：${message}`);
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function generateModule(input: {
  cardType: ModuleCardType;
  requirement: string;
  timeframe: string;
  pair: string;
  canShort: boolean;
  optimizeTargetCode?: string;
  optimizeFromVersionId?: string;
}) {
  return request<{
    version_id: string;
    card_type: CardType;
    module_code: string;
    params: Record<string, string | number | boolean>;
    explain: string;
  }>("/api/module/generate", {
    method: "POST",
    body: JSON.stringify({
      card_type: input.cardType,
      requirement: input.requirement,
      context: {
        timeframe: input.timeframe,
        pair: input.pair,
        can_short: input.canShort,
      },
      optimize_target_code: input.optimizeTargetCode,
      optimize_from_version_id: input.optimizeFromVersionId,
    }),
  });
}

export async function composeStrategy(input: {
  strategyName: string;
  requirement: string;
  pair: string;
  timeframe: string;
  timerange: string;
  canShort: boolean;
  indicatorVersionId?: string;
  positionVersionId?: string;
  riskVersionId?: string;
  baseStrategyCode?: string;
  baseBuildId?: string;
}) {
  const hasAllModules = Boolean(input.indicatorVersionId && input.positionVersionId && input.riskVersionId);
  return request<ComposeResponse>("/api/strategy/compose", {
    method: "POST",
    body: JSON.stringify({
      strategy_name: input.strategyName,
      requirement: input.requirement,
      base: {
        timeframe: input.timeframe,
        can_short: input.canShort,
      },
      ...(hasAllModules
        ? {
            modules: {
              indicator_factor_version_id: input.indicatorVersionId,
              position_adjustment_version_id: input.positionVersionId,
              risk_system_version_id: input.riskVersionId,
            },
          }
        : {}),
      base_strategy_code: input.baseStrategyCode,
      base_build_id: input.baseBuildId,
      validation: {
        enable: true,
        pair: input.pair,
        timeframe: input.timeframe,
        timerange: input.timerange,
        max_repair_rounds: 2,
      },
    }),
  });
}

export async function syncStrategyFromFile(input: { buildId: string }) {
  return request<ComposeResponse>("/api/strategy/sync-file", {
    method: "POST",
    body: JSON.stringify({
      build_id: input.buildId,
    }),
  });
}

export async function runBacktest(input: {
  buildId: string;
  pair: string;
  timeframe: string;
  timerange: string;
}) {
  return request<{ job_id: string; status: string }>("/api/backtest/run", {
    method: "POST",
    body: JSON.stringify({
      build_id: input.buildId,
      pair: input.pair,
      timeframe: input.timeframe,
      timerange: input.timerange,
    }),
  });
}

export async function getBacktestResult(jobId: string) {
  return request<BacktestResult>(`/api/backtest/${jobId}/result`);
}

export async function getAiModels() {
  return request<AiModelsResponse>("/api/ai/models");
}

export async function setActiveAiModel(modelKey: string) {
  return request<AiModelsResponse>("/api/ai/models/active", {
    method: "PUT",
    body: JSON.stringify({ model_key: modelKey }),
  });
}

export async function getPersona() {
  return request<PersonaResponse>("/api/ai/persona");
}

export async function savePersona(content: string) {
  return request<PersonaResponse>("/api/ai/persona", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function getPairProfile() {
  return request<PairProfileResponse>("/api/pair-profile");
}

export async function savePairProfile(input: {
  defaults: Record<string, string | number | boolean>;
  pairs: Record<string, Record<string, string | number | boolean>>;
}) {
  return request<PairProfileResponse>("/api/pair-profile", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}
