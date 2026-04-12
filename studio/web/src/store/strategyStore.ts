import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type {
  BacktestScenario,
  BacktestResult,
  CardType,
  CardZone,
  ModuleCardType,
  StrategyCard,
} from "../types";

type EquippedCardIds = Record<ModuleCardType, string | undefined>;

type WorkbenchPosition = {
  x: number;
  y: number;
};

type Store = {
  selectedCardId?: string;
  cards: Record<string, StrategyCard>;
  zoneCardIds: Record<CardZone, string[]>;
  equippedCardIds: EquippedCardIds;
  strategyName: string;
  canShort: boolean;
  pair: string;
  timeframe: string;
  timerange: string;
  backtestScenarios: BacktestScenario[];
  buildId?: string;
  strategyFile?: string;
  lintWarnings: string[];
  jobId?: string;
  backtestResult?: BacktestResult;
  createCard: (cardType: ModuleCardType) => string;
  createStrategyCard: (title?: string) => string;
  setStrategyCardComposed: (
    cardId: string,
    payload: {
      buildId: string;
      strategyFile: string;
      strategyCode: string;
      explain: string;
      sourceCardIds?: Record<ModuleCardType, string>;
      sourceVersionIds?: Record<ModuleCardType, string>;
      optimizationNote: string;
    },
  ) => void;
  duplicateCard: (cardId: string) => void;
  deleteCard: (cardId: string) => boolean;
  selectCard: (cardId?: string) => void;
  updateCardTitle: (cardId: string, title: string) => void;
  updateCardRequirement: (cardId: string, requirement: string) => void;
  setCardGenerated: (cardId: string, payload: { versionId: string; code: string; explain: string }) => void;
  moveCard: (cardId: string, zone: CardZone, workbenchPosition?: WorkbenchPosition) => boolean;
  setCardWorkbenchPosition: (cardId: string, position: WorkbenchPosition) => boolean;
  equipCard: (cardId: string) => void;
  unequipCard: (cardType: ModuleCardType) => void;
  setStrategyMeta: (name: string) => void;
  setCanShort: (canShort: boolean) => void;
  setBacktestConfig: (key: "pair" | "timeframe" | "timerange", value: string) => void;
  addBacktestScenario: () => void;
  updateBacktestScenario: (id: string, key: "name" | "pair" | "timeframe" | "timerange", value: string) => void;
  toggleBacktestScenario: (id: string) => void;
  removeBacktestScenario: (id: string) => void;
  applyBacktestScenario: (id: string) => void;
  setComposeResult: (payload: { buildId: string; strategyFile: string; warnings: string[] }) => void;
  setJob: (jobId: string) => void;
  setBacktestResult: (result: BacktestResult) => void;
};

type PersistedState = Pick<
  Store,
  | "selectedCardId"
  | "cards"
  | "zoneCardIds"
  | "equippedCardIds"
  | "strategyName"
  | "canShort"
  | "pair"
  | "timeframe"
  | "timerange"
  | "backtestScenarios"
  | "buildId"
  | "strategyFile"
  | "lintWarnings"
  | "jobId"
  | "backtestResult"
>;

const STORE_STORAGE_KEY = "freqtrade-strategy-studio-store-v2";

const WORKBENCH_GRID = 24;
const WORKBENCH_PADDING = 12;
const CARD_WIDTH = 220;
const CARD_HEIGHT = 170;
const MAX_SCAN_WIDTH = 1600;
const MAX_SCAN_HEIGHT = 1600;

function uniqueId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function titleByType(cardType: CardType): string {
  if (cardType === "indicator_factor") return "指标因子卡";
  if (cardType === "position_adjustment") return "仓位调整卡";
  if (cardType === "strategy") return "策略卡";
  return "风险系统卡";
}

function requirementByType(cardType: CardType): string {
  if (cardType === "indicator_factor") return "EMA20 上穿 EMA60 且 RSI 回升做多，趋势转弱离场。";
  if (cardType === "position_adjustment") return "首次轻仓，浮亏后仅允许一次加仓，盈利分批减仓。";
  if (cardType === "strategy") return "由三个模块卡组合封装成完整策略。";
  return "单笔 8% 止损，并启用移动止损。";
}

function optimizeRequirementByType(cardType: CardType): string {
  if (cardType === "indicator_factor") return "优化指标因子代码：提高信号质量，减少震荡误触发。";
  if (cardType === "position_adjustment") return "优化仓位调整代码：控制回撤并提升加减仓稳定性。";
  if (cardType === "strategy") return "优化完整策略：保持核心逻辑前提下提升稳健性。";
  return "优化风险系统代码：平衡收益、回撤与止损效率。";
}

function snapToWorkbench(value: number): number {
  return WORKBENCH_PADDING + Math.round((value - WORKBENCH_PADDING) / WORKBENCH_GRID) * WORKBENCH_GRID;
}

function normalizeCardPosition(card?: StrategyCard): WorkbenchPosition {
  return {
    x: snapToWorkbench(card?.workbenchX ?? WORKBENCH_PADDING),
    y: snapToWorkbench(card?.workbenchY ?? WORKBENCH_PADDING),
  };
}

function rectsOverlap(a: WorkbenchPosition, b: WorkbenchPosition): boolean {
  return !(
    a.x + CARD_WIDTH <= b.x ||
    b.x + CARD_WIDTH <= a.x ||
    a.y + CARD_HEIGHT <= b.y ||
    b.y + CARD_HEIGHT <= a.y
  );
}

function isWorkbenchPositionFree(
  cards: Record<string, StrategyCard>,
  workbenchCardIds: string[],
  targetCardId: string,
  position: WorkbenchPosition,
): boolean {
  return workbenchCardIds.every((id) => {
    if (id === targetCardId) return true;
    const other = cards[id];
    if (!other) return true;
    return !rectsOverlap(position, normalizeCardPosition(other));
  });
}

function findAvailableWorkbenchPosition(
  cards: Record<string, StrategyCard>,
  workbenchCardIds: string[],
  targetCardId: string,
): WorkbenchPosition {
  for (let y = WORKBENCH_PADDING; y <= MAX_SCAN_HEIGHT; y += WORKBENCH_GRID) {
    for (let x = WORKBENCH_PADDING; x <= MAX_SCAN_WIDTH; x += WORKBENCH_GRID) {
      const pos = { x, y };
      if (isWorkbenchPositionFree(cards, workbenchCardIds, targetCardId, pos)) {
        return pos;
      }
    }
  }
  return { x: WORKBENCH_PADDING, y: WORKBENCH_PADDING };
}

function createNewCard(
  cardType: CardType,
  zone: CardZone,
  requirement?: string,
  position?: WorkbenchPosition,
): StrategyCard {
  const now = Date.now();
  const workbenchPosition = zone === "workbench" ? position ?? { x: WORKBENCH_PADDING, y: WORKBENCH_PADDING } : undefined;
  return {
    id: uniqueId("card"),
    cardType,
    zone,
    title: titleByType(cardType),
    requirement: requirement ?? requirementByType(cardType),
    workbenchX: workbenchPosition?.x,
    workbenchY: workbenchPosition?.y,
    createdAt: now,
    updatedAt: now,
  };
}

function removeId(list: string[], id: string): string[] {
  return list.filter((item) => item !== id);
}

function createBacktestScenario(seed: {
  name?: string;
  pair: string;
  timeframe: string;
  timerange: string;
  checked?: boolean;
  id?: string;
  createdAt?: number;
  updatedAt?: number;
}): BacktestScenario {
  const now = Date.now();
  return {
    id: seed.id ?? uniqueId("btsc"),
    name: seed.name?.trim() || "回测场景",
    pair: seed.pair.trim(),
    timeframe: seed.timeframe.trim(),
    timerange: seed.timerange.trim(),
    checked: Boolean(seed.checked),
    createdAt: seed.createdAt ?? now,
    updatedAt: seed.updatedAt ?? now,
  };
}

function defaultPersistedState(): PersistedState {
  const indicatorCard = createNewCard("indicator_factor", "workbench", undefined, { x: 12, y: 12 });
  const positionCard = createNewCard("position_adjustment", "workbench", undefined, { x: 252, y: 12 });
  const riskCard = createNewCard("risk_system", "workbench", undefined, { x: 492, y: 12 });
  const defaultPair = "XRP/USDT:USDT";
  const defaultTimeframe = "1m";
  const defaultTimerange = "20251220-20260306";

  const cards: Record<string, StrategyCard> = {
    [indicatorCard.id]: indicatorCard,
    [positionCard.id]: positionCard,
    [riskCard.id]: riskCard,
  };

  return {
    selectedCardId: indicatorCard.id,
    cards,
    zoneCardIds: {
      workbench: [indicatorCard.id, positionCard.id, riskCard.id],
      vault: [],
    },
    equippedCardIds: {
      indicator_factor: indicatorCard.id,
      position_adjustment: positionCard.id,
      risk_system: riskCard.id,
    },
    strategyName: "AssembleStrategyMVP",
    canShort: true,
    pair: defaultPair,
    timeframe: defaultTimeframe,
    timerange: defaultTimerange,
    backtestScenarios: [
      createBacktestScenario({
        name: "默认场景",
        pair: defaultPair,
        timeframe: defaultTimeframe,
        timerange: defaultTimerange,
        checked: false,
      }),
    ],
    lintWarnings: [],
    buildId: undefined,
    strategyFile: undefined,
    jobId: undefined,
    backtestResult: undefined,
  };
}

function normalizePersistedState(input: Partial<PersistedState>): PersistedState {
  const fallback = defaultPersistedState();
  const cards = input.cards && Object.keys(input.cards).length > 0 ? { ...input.cards } : { ...fallback.cards };

  const workbenchSeed = input.zoneCardIds?.workbench ?? [];
  const vaultSeed = input.zoneCardIds?.vault ?? [];

  const seen = new Set<string>();
  const workbench = workbenchSeed.filter((id) => {
    if (!cards[id] || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  const vault = vaultSeed.filter((id) => {
    if (!cards[id] || seen.has(id)) return false;
    seen.add(id);
    return true;
  });

  Object.keys(cards).forEach((id) => {
    if (!seen.has(id)) workbench.push(id);
  });

  workbench.forEach((id) => {
    const card = cards[id];
    cards[id] = {
      ...card,
      zone: "workbench",
      workbenchX: snapToWorkbench(card.workbenchX ?? WORKBENCH_PADDING),
      workbenchY: snapToWorkbench(card.workbenchY ?? WORKBENCH_PADDING),
    };
  });
  vault.forEach((id) => {
    const card = cards[id];
    cards[id] = {
      ...card,
      zone: "vault",
    };
  });

  const allCardIds = [...workbench, ...vault];
  const buildEquipped = (cardType: ModuleCardType): string | undefined => {
    const candidate = input.equippedCardIds?.[cardType];
    if (candidate && cards[candidate]?.cardType === cardType) return candidate;
    return allCardIds.find((id) => cards[id]?.cardType === cardType);
  };

  const selectedCardId = input.selectedCardId && cards[input.selectedCardId]
    ? input.selectedCardId
    : workbench[0] ?? vault[0];
  const pair = input.pair?.trim() || fallback.pair;
  const timeframe = input.timeframe?.trim() || fallback.timeframe;
  const timerange = input.timerange?.trim() || fallback.timerange;
  const scenarioSeeds = Array.isArray(input.backtestScenarios) ? input.backtestScenarios : [];
  const normalizedScenarios = scenarioSeeds
    .map((item) =>
      createBacktestScenario({
        id: item?.id,
        name: item?.name,
        pair: String(item?.pair ?? pair),
        timeframe: String(item?.timeframe ?? timeframe),
        timerange: String(item?.timerange ?? timerange),
        checked: Boolean(item?.checked),
        createdAt: typeof item?.createdAt === "number" ? item.createdAt : undefined,
        updatedAt: typeof item?.updatedAt === "number" ? item.updatedAt : undefined,
      }),
    )
    .filter((item) => item.pair && item.timeframe && item.timerange);

  const backtestScenarios = normalizedScenarios.length > 0
    ? normalizedScenarios
    : [
        createBacktestScenario({
          name: "默认场景",
          pair,
          timeframe,
          timerange,
          checked: false,
        }),
      ];
  const firstCheckedIndex = backtestScenarios.findIndex((item) => item.checked);
  if (firstCheckedIndex >= 0) {
    backtestScenarios.forEach((item, idx) => {
      item.checked = idx === firstCheckedIndex;
    });
  }

  return {
    selectedCardId,
    cards,
    zoneCardIds: {
      workbench,
      vault,
    },
    equippedCardIds: {
      indicator_factor: buildEquipped("indicator_factor"),
      position_adjustment: buildEquipped("position_adjustment"),
      risk_system: buildEquipped("risk_system"),
    },
    strategyName: input.strategyName?.trim() || fallback.strategyName,
    canShort: typeof input.canShort === "boolean" ? input.canShort : fallback.canShort,
    pair,
    timeframe,
    timerange,
    backtestScenarios,
    lintWarnings: Array.isArray(input.lintWarnings) ? input.lintWarnings : [],
    buildId: input.buildId,
    strategyFile: input.strategyFile,
    jobId: input.jobId,
    backtestResult: input.backtestResult,
  };
}

function toPersistedState(state: Store): PersistedState {
  return {
    selectedCardId: state.selectedCardId,
    cards: state.cards,
    zoneCardIds: state.zoneCardIds,
    equippedCardIds: state.equippedCardIds,
    strategyName: state.strategyName,
    canShort: state.canShort,
    pair: state.pair,
    timeframe: state.timeframe,
    timerange: state.timerange,
    backtestScenarios: state.backtestScenarios,
    lintWarnings: state.lintWarnings,
    buildId: state.buildId,
    strategyFile: state.strategyFile,
    jobId: state.jobId,
    backtestResult: state.backtestResult,
  };
}

const initialState = defaultPersistedState();

export const useStrategyStore = create<Store>()(
  persist(
    (set, get) => ({
      ...initialState,
      createCard: (cardType) => {
        const draft = get();
        const tempId = `tmp_${Date.now()}`;
        const pos = findAvailableWorkbenchPosition(draft.cards, draft.zoneCardIds.workbench, tempId);
        const card = createNewCard(cardType, "workbench", undefined, pos);
        set((state) => ({
          cards: {
            ...state.cards,
            [card.id]: card,
          },
          zoneCardIds: {
            ...state.zoneCardIds,
            workbench: [card.id, ...state.zoneCardIds.workbench],
          },
          selectedCardId: card.id,
        }));
        return card.id;
      },
      createStrategyCard: (title) => {
        const draft = get();
        const tempId = `tmp_${Date.now()}`;
        const pos = findAvailableWorkbenchPosition(draft.cards, draft.zoneCardIds.workbench, tempId);
        const card = createNewCard("strategy", "workbench", undefined, pos);
        if (title?.trim()) card.title = title.trim();
        set((state) => ({
          cards: {
            ...state.cards,
            [card.id]: card,
          },
          zoneCardIds: {
            ...state.zoneCardIds,
            workbench: [card.id, ...state.zoneCardIds.workbench],
          },
          selectedCardId: card.id,
        }));
        return card.id;
      },
      setStrategyCardComposed: (cardId, payload) =>
        set((state) => {
          const card = state.cards[cardId];
          if (!card || card.cardType !== "strategy") return state;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                buildId: payload.buildId,
                strategyFile: payload.strategyFile,
                moduleCode: payload.strategyCode,
                explain: payload.explain,
                sourceCardIds: payload.sourceCardIds ?? card.sourceCardIds,
                sourceVersionIds: payload.sourceVersionIds ?? card.sourceVersionIds,
                optimizationNote: payload.optimizationNote,
                requirement: optimizeRequirementByType(card.cardType),
                updatedAt: Date.now(),
              },
            },
          };
        }),
      duplicateCard: (cardId) => {
        const source = get().cards[cardId];
        if (!source) return;
        const draft = get();
        const tempId = `tmp_${Date.now()}`;
        const pos = findAvailableWorkbenchPosition(draft.cards, draft.zoneCardIds.workbench, tempId);
        const clone = createNewCard(source.cardType, "workbench", source.requirement, pos);
        clone.title = `${source.title}-副本`;
        set((state) => ({
          cards: {
            ...state.cards,
            [clone.id]: clone,
          },
          zoneCardIds: {
            ...state.zoneCardIds,
            workbench: [clone.id, ...state.zoneCardIds.workbench],
          },
          selectedCardId: clone.id,
        }));
      },
      deleteCard: (cardId) => {
        let deleted = false;
        set((state) => {
          const card = state.cards[cardId];
          if (!card) return state;

          const cards = { ...state.cards };
          delete cards[cardId];

          const nextWorkbench = removeId(state.zoneCardIds.workbench, cardId);
          const nextVault = removeId(state.zoneCardIds.vault, cardId);
          const remainingIds = [...nextWorkbench, ...nextVault];

          const nextEquipped = { ...state.equippedCardIds };
          if (card.cardType !== "strategy") {
            const type = card.cardType as ModuleCardType;
            if (nextEquipped[type] === cardId) {
              nextEquipped[type] = remainingIds.find((id) => cards[id]?.cardType === type);
            }
          }

          const nextSelected = state.selectedCardId === cardId
            ? nextWorkbench[0] ?? nextVault[0]
            : state.selectedCardId;

          deleted = true;
          return {
            cards,
            zoneCardIds: {
              workbench: nextWorkbench,
              vault: nextVault,
            },
            equippedCardIds: nextEquipped,
            selectedCardId: nextSelected,
            buildId: state.buildId === card.buildId ? undefined : state.buildId,
            strategyFile: state.buildId === card.buildId ? undefined : state.strategyFile,
            lintWarnings: state.buildId === card.buildId ? [] : state.lintWarnings,
          };
        });
        return deleted;
      },
      selectCard: (cardId) => set({ selectedCardId: cardId }),
      updateCardTitle: (cardId, title) =>
        set((state) => {
          const card = state.cards[cardId];
          if (!card) return state;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                title,
                updatedAt: Date.now(),
              },
            },
          };
        }),
      updateCardRequirement: (cardId, requirement) =>
        set((state) => {
          const card = state.cards[cardId];
          if (!card) return state;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                requirement,
                updatedAt: Date.now(),
              },
            },
          };
        }),
      setCardGenerated: (cardId, payload) =>
        set((state) => {
          const card = state.cards[cardId];
          if (!card) return state;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                versionId: payload.versionId,
                moduleCode: payload.code,
                explain: payload.explain,
                requirement: optimizeRequirementByType(card.cardType),
                updatedAt: Date.now(),
              },
            },
          };
        }),
      moveCard: (cardId, zone, workbenchPosition) => {
        let moved = false;
        set((state) => {
          const card = state.cards[cardId];
          if (!card) return state;

          const workbenchIds = removeId(state.zoneCardIds.workbench, cardId);
          const vaultIds = removeId(state.zoneCardIds.vault, cardId);

          if (zone === "workbench") {
            const snapped = workbenchPosition
              ? { x: snapToWorkbench(workbenchPosition.x), y: snapToWorkbench(workbenchPosition.y) }
              : normalizeCardPosition(card);

            const nextWorkbenchIds = [cardId, ...workbenchIds];
            let finalPos = snapped;
            if (!isWorkbenchPositionFree(state.cards, nextWorkbenchIds, cardId, finalPos)) {
              if (workbenchPosition) return state;
              finalPos = findAvailableWorkbenchPosition(state.cards, nextWorkbenchIds, cardId);
            }

            moved = true;
            return {
              cards: {
                ...state.cards,
                [cardId]: {
                  ...card,
                  zone,
                  workbenchX: finalPos.x,
                  workbenchY: finalPos.y,
                  updatedAt: Date.now(),
                },
              },
              zoneCardIds: {
                workbench: nextWorkbenchIds,
                vault: vaultIds,
              },
            };
          }

          moved = true;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                zone,
                updatedAt: Date.now(),
              },
            },
            zoneCardIds: {
              workbench: workbenchIds,
              vault: [cardId, ...vaultIds],
            },
          };
        });
        return moved;
      },
      setCardWorkbenchPosition: (cardId, position) => {
        let moved = false;
        set((state) => {
          const card = state.cards[cardId];
          if (!card || card.zone !== "workbench") return state;

          const snapped = { x: snapToWorkbench(position.x), y: snapToWorkbench(position.y) };
          if (!isWorkbenchPositionFree(state.cards, state.zoneCardIds.workbench, cardId, snapped)) return state;

          moved = true;
          return {
            cards: {
              ...state.cards,
              [cardId]: {
                ...card,
                workbenchX: snapped.x,
                workbenchY: snapped.y,
                updatedAt: Date.now(),
              },
            },
          };
        });
        return moved;
      },
      equipCard: (cardId) =>
        set((state) => {
          const card = state.cards[cardId];
          if (!card || card.cardType === "strategy") return state;
          return {
            equippedCardIds: {
              ...state.equippedCardIds,
              [card.cardType as ModuleCardType]: cardId,
            },
          };
        }),
      unequipCard: (cardType) =>
        set((state) => ({
          equippedCardIds: {
            ...state.equippedCardIds,
            [cardType]: undefined,
          },
        })),
      setStrategyMeta: (name) => set({ strategyName: name }),
      setCanShort: (canShort) => set({ canShort }),
      setBacktestConfig: (key, value) => set({ [key]: value } as Pick<Store, typeof key>),
      addBacktestScenario: () =>
        set((state) => {
          const index = state.backtestScenarios.length + 1;
          const scenario = createBacktestScenario({
            name: `场景 ${index}`,
            pair: state.pair,
            timeframe: state.timeframe,
            timerange: state.timerange,
            checked: false,
          });
          return {
            backtestScenarios: [scenario, ...state.backtestScenarios],
          };
        }),
      updateBacktestScenario: (id, key, value) =>
        set((state) => ({
          backtestScenarios: state.backtestScenarios.map((item) =>
            item.id === id
              ? {
                  ...item,
                  [key]: value,
                  updatedAt: Date.now(),
                }
              : item,
          ),
        })),
      toggleBacktestScenario: (id) =>
        set((state) => {
          const target = state.backtestScenarios.find((item) => item.id === id);
          if (!target) return state;
          const nextChecked = !target.checked;
          return {
            backtestScenarios: state.backtestScenarios.map((item) => ({
              ...item,
              checked: item.id === id ? nextChecked : false,
              updatedAt: item.id === id ? Date.now() : item.updatedAt,
            })),
          };
        }),
      removeBacktestScenario: (id) =>
        set((state) => {
          const remaining = state.backtestScenarios.filter((item) => item.id !== id);
          if (remaining.length > 0) {
            return {
              backtestScenarios: remaining,
            };
          }
          return {
            backtestScenarios: [
              createBacktestScenario({
                name: "默认场景",
                pair: state.pair,
                timeframe: state.timeframe,
                timerange: state.timerange,
                checked: false,
              }),
            ],
          };
        }),
      applyBacktestScenario: (id) =>
        set((state) => {
          const scenario = state.backtestScenarios.find((item) => item.id === id);
          if (!scenario) return state;
          return {
            pair: scenario.pair,
            timeframe: scenario.timeframe,
            timerange: scenario.timerange,
          };
        }),
      setComposeResult: ({ buildId, strategyFile, warnings }) =>
        set({
          buildId,
          strategyFile,
          lintWarnings: warnings,
        }),
      setJob: (jobId) => set({ jobId }),
      setBacktestResult: (result) => set({ backtestResult: result }),
    }),
    {
      name: STORE_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => toPersistedState(state),
      merge: (persistedState, currentState) => {
        if (!persistedState || typeof persistedState !== "object") return currentState;
        const normalized = normalizePersistedState(persistedState as Partial<PersistedState>);
        return {
          ...currentState,
          ...normalized,
        };
      },
    },
  ),
);
