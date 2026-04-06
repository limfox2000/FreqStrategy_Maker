export type ModuleCardType = "indicator_factor" | "position_adjustment" | "risk_system";
export type CardType = ModuleCardType | "strategy";

export type CardZone = "workbench" | "vault";

export interface StrategyCard {
  id: string;
  cardType: CardType;
  title: string;
  requirement: string;
  zone: CardZone;
  workbenchX?: number;
  workbenchY?: number;
  createdAt: number;
  updatedAt: number;
  versionId?: string;
  moduleCode?: string;
  explain?: string;
  buildId?: string;
  strategyFile?: string;
  sourceCardIds?: Record<ModuleCardType, string>;
  sourceVersionIds?: Record<ModuleCardType, string>;
  optimizationNote?: string;
}

export interface ComposeResponse {
  build_id: string;
  strategy_file: string;
  lint_ok: boolean;
  warnings: string[];
  optimization_note: string;
  source_versions: Record<string, string>;
  strategy_code: string;
  validation_passed: boolean;
  validation_logs: string[];
  repair_rounds: number;
}

export interface BacktestSummary {
  trades: number;
  winrate: number;
  profit_total_pct: number;
  profit_total_abs: number;
  max_drawdown_pct: number;
  profit_factor: number | null;
  market_change_pct: number;
  starting_balance?: number;
  tradable_balance_ratio?: number;
}

export interface BacktestSeries {
  kline: Array<{ time: number; open: number; high: number; low: number; close: number }>;
  markers: Array<{
    time: number;
    position: "aboveBar" | "belowBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle";
    text: string;
  }>;
  equity: Array<{ time: number; value: number }>;
  drawdown: Array<{ time: number; value: number }>;
  indicators?: Array<{
    name: string;
    color?: string;
    points: Array<{ time: number; value: number }>;
  }>;
}

export interface BacktestResult {
  job_id: string;
  status: "queued" | "running" | "finished" | "failed";
  logs: string[];
  summary?: BacktestSummary;
  series?: BacktestSeries;
  artifacts?: Record<string, string>;
  ai_review?: string | null;
  repair_rounds?: number;
  error?: string | null;
}

export interface AiModelPreset {
  key: string;
  label: string;
  provider: "template" | "openai" | "deepseek" | "glm" | "claude";
  model: string;
  summary: string;
  api_key_configured: boolean;
}

export interface AiModelsResponse {
  active_model_key: string;
  secrets_file: string;
  models: AiModelPreset[];
}

export interface PersonaResponse {
  content: string;
  updated_at: string;
}
