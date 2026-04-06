import { type DragEvent, type MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { BacktestCharts } from "./modules/charts/BacktestCharts";
import { RetroBackdrop } from "./modules/workspace/RetroBackdrop";
import {
  composeStrategy,
  generateModule,
  getAiModels,
  getBacktestResult,
  getPersona,
  runBacktest,
  savePersona,
  setActiveAiModel,
} from "./api/client";
import { useStrategyStore } from "./store/strategyStore";
import type { AiModelPreset, BacktestResult, CardType, ModuleCardType, StrategyCard } from "./types";

const GRID = 24;
const PAD = 12;
const CARD_W = 220;
const CARD_H = 170;

type AiWorkStage = "idle" | "thinking" | "coding" | "done";
type ComposeSlotKey = ModuleCardType | "strategy";
type ComposeSlots = Record<ComposeSlotKey, string | undefined>;

const AI_STAGE_ORDER: Exclude<AiWorkStage, "idle">[] = ["thinking", "coding", "done"];
const COMPOSE_SLOT_ORDER: ComposeSlotKey[] = [
  "indicator_factor",
  "position_adjustment",
  "risk_system",
  "strategy",
];

function isModuleCardType(cardType: CardType): cardType is ModuleCardType {
  return cardType === "indicator_factor" || cardType === "position_adjustment" || cardType === "risk_system";
}

function cardTypeLabel(cardType: CardType): string {
  if (cardType === "indicator_factor") return "指标因子";
  if (cardType === "position_adjustment") return "仓位调整";
  if (cardType === "risk_system") return "风险系统";
  return "策略封装";
}

function shortVersion(versionId?: string): string {
  if (!versionId) return "未生成";
  return versionId.slice(0, 18);
}

function clampPanelWidth(width: number): number {
  if (typeof window === "undefined") return width;
  const max = Math.max(480, window.innerWidth - 56);
  return Math.min(Math.max(width, 420), max);
}

function hasGeneratedCode(card?: StrategyCard): boolean {
  if (!card) return false;
  if (card.cardType === "strategy") return Boolean(card.buildId && card.moduleCode);
  return Boolean(card.versionId && card.moduleCode);
}

function requirementFieldLabel(card?: StrategyCard): string {
  return hasGeneratedCode(card) ? "优化需求" : "策略需求";
}

function generateActionLabel(card?: StrategyCard): string {
  if (!card) return "生成代码";
  if (card.cardType === "strategy") return hasGeneratedCode(card) ? "优化完整策略" : "生成完整策略";
  return hasGeneratedCode(card) ? "优化代码" : "生成代码";
}

function aiStageLabel(stage: Exclude<AiWorkStage, "idle">): string {
  if (stage === "thinking") return "AI 思考中";
  if (stage === "coding") return "AI 写代码中";
  return "AI 完成";
}

function backtestStatusLabel(status?: string): string {
  if (!status) return "-";
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  if (status === "finished") return "已完成";
  if (status === "failed") return "失败";
  return status;
}

function snapGrid(value: number): number {
  return PAD + Math.round((value - PAD) / GRID) * GRID;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function composeSlotLabel(slot: ComposeSlotKey): string {
  if (slot === "indicator_factor") return "指标因子槽";
  if (slot === "position_adjustment") return "仓位调整槽";
  if (slot === "risk_system") return "风险系统槽";
  return "策略卡槽";
}

function composeSlotHint(slot: ComposeSlotKey): string {
  if (slot === "strategy") return "拖入策略卡（将作为封装输出卡）";
  return "拖入已生成代码的对应模块卡";
}

function stageClass(currentStage: AiWorkStage, stage: Exclude<AiWorkStage, "idle">): string {
  if (currentStage === "idle") return "ai-work-step";
  const currentIdx = AI_STAGE_ORDER.indexOf(currentStage as Exclude<AiWorkStage, "idle">);
  const idx = AI_STAGE_ORDER.indexOf(stage);
  if (idx < currentIdx) return "ai-work-step done";
  if (idx === currentIdx) return "ai-work-step active";
  return "ai-work-step";
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleString("zh-CN", { hour12: false });
}

export default function App() {
  const cards = useStrategyStore((state) => state.cards);
  const zoneCardIds = useStrategyStore((state) => state.zoneCardIds);
  const equippedCardIds = useStrategyStore((state) => state.equippedCardIds);
  const selectedCardId = useStrategyStore((state) => state.selectedCardId);
  const strategyName = useStrategyStore((state) => state.strategyName);
  const canShort = useStrategyStore((state) => state.canShort);
  const pair = useStrategyStore((state) => state.pair);
  const timeframe = useStrategyStore((state) => state.timeframe);
  const timerange = useStrategyStore((state) => state.timerange);
  const buildId = useStrategyStore((state) => state.buildId);
  const strategyFile = useStrategyStore((state) => state.strategyFile);
  const lintWarnings = useStrategyStore((state) => state.lintWarnings);
  const jobId = useStrategyStore((state) => state.jobId);
  const backtestResult = useStrategyStore((state) => state.backtestResult);

  const createCard = useStrategyStore((state) => state.createCard);
  const createStrategyCard = useStrategyStore((state) => state.createStrategyCard);
  const duplicateCard = useStrategyStore((state) => state.duplicateCard);
  const deleteCard = useStrategyStore((state) => state.deleteCard);
  const selectCard = useStrategyStore((state) => state.selectCard);
  const updateCardTitle = useStrategyStore((state) => state.updateCardTitle);
  const updateCardRequirement = useStrategyStore((state) => state.updateCardRequirement);
  const setCardGenerated = useStrategyStore((state) => state.setCardGenerated);
  const setStrategyCardComposed = useStrategyStore((state) => state.setStrategyCardComposed);
  const moveCard = useStrategyStore((state) => state.moveCard);
  const equipCard = useStrategyStore((state) => state.equipCard);
  const unequipCard = useStrategyStore((state) => state.unequipCard);
  const setStrategyMeta = useStrategyStore((state) => state.setStrategyMeta);
  const setCanShort = useStrategyStore((state) => state.setCanShort);
  const setBacktestConfig = useStrategyStore((state) => state.setBacktestConfig);
  const setComposeResult = useStrategyStore((state) => state.setComposeResult);
  const setJob = useStrategyStore((state) => state.setJob);
  const setBacktestResult = useStrategyStore((state) => state.setBacktestResult);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panelCardId, setPanelCardId] = useState<string | undefined>(undefined);
  const [panelWidth, setPanelWidth] = useState(560);
  const [resizingPanel, setResizingPanel] = useState(false);
  const [showAiPanel, setShowAiPanel] = useState(false);
  const [composeSlots, setComposeSlots] = useState<ComposeSlots>({
    indicator_factor: undefined,
    position_adjustment: undefined,
    risk_system: undefined,
    strategy: undefined,
  });
  const [backtestSlotCardId, setBacktestSlotCardId] = useState<string | undefined>(undefined);

  const [aiLoaded, setAiLoaded] = useState(false);
  const [aiModels, setAiModels] = useState<AiModelPreset[]>([]);
  const [activeModelKey, setActiveModelKey] = useState("");
  const [aiSecretsFile, setAiSecretsFile] = useState("");
  const [personaContent, setPersonaContent] = useState("");
  const [personaUpdatedAt, setPersonaUpdatedAt] = useState("");

  const [aiWorkStage, setAiWorkStage] = useState<AiWorkStage>("idle");
  const [showAiWorkStage, setShowAiWorkStage] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ cardId: string; x: number; y: number } | null>(null);

  const aiCodeStageTimerRef = useRef<number | null>(null);
  const aiDoneStageTimerRef = useRef<number | null>(null);
  const workbenchCanvasRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);

  const panelCard = panelCardId ? cards[panelCardId] : undefined;

  const workbenchCards = useMemo(
    () => zoneCardIds.workbench.map((id) => cards[id]).filter(Boolean),
    [zoneCardIds.workbench, cards],
  );
  const vaultCards = useMemo(() => zoneCardIds.vault.map((id) => cards[id]).filter(Boolean), [zoneCardIds.vault, cards]);
  const composeSlotCards = useMemo(
    () => ({
      indicator_factor: composeSlots.indicator_factor ? cards[composeSlots.indicator_factor] : undefined,
      position_adjustment: composeSlots.position_adjustment ? cards[composeSlots.position_adjustment] : undefined,
      risk_system: composeSlots.risk_system ? cards[composeSlots.risk_system] : undefined,
      strategy: composeSlots.strategy ? cards[composeSlots.strategy] : undefined,
    }),
    [cards, composeSlots],
  );
  const backtestSlotCard = useMemo(
    () => (backtestSlotCardId ? cards[backtestSlotCardId] : undefined),
    [backtestSlotCardId, cards],
  );
  const activeModel = useMemo(
    () => aiModels.find((item) => item.key === activeModelKey),
    [aiModels, activeModelKey],
  );

  const contextMenuStyle = useMemo(() => {
    if (!contextMenu) return undefined;
    const maxX = typeof window === "undefined" ? contextMenu.x : Math.max(8, window.innerWidth - 216);
    const maxY = typeof window === "undefined" ? contextMenu.y : Math.max(8, window.innerHeight - 172);
    return {
      left: `${Math.min(contextMenu.x, maxX)}px`,
      top: `${Math.min(contextMenu.y, maxY)}px`,
    };
  }, [contextMenu]);

  const clearAiStageTimers = () => {
    if (aiCodeStageTimerRef.current !== null) {
      window.clearTimeout(aiCodeStageTimerRef.current);
      aiCodeStageTimerRef.current = null;
    }
    if (aiDoneStageTimerRef.current !== null) {
      window.clearTimeout(aiDoneStageTimerRef.current);
      aiDoneStageTimerRef.current = null;
    }
  };

  const startAiWorkStage = () => {
    clearAiStageTimers();
    setShowAiWorkStage(true);
    setAiWorkStage("thinking");
    aiCodeStageTimerRef.current = window.setTimeout(() => {
      setAiWorkStage("coding");
      aiCodeStageTimerRef.current = null;
    }, 900);
  };

  const completeAiWorkStage = () => {
    clearAiStageTimers();
    setShowAiWorkStage(true);
    setAiWorkStage("done");
    aiDoneStageTimerRef.current = window.setTimeout(() => {
      setAiWorkStage("idle");
      setShowAiWorkStage(false);
      aiDoneStageTimerRef.current = null;
    }, 2200);
  };

  const resetAiWorkStage = () => {
    clearAiStageTimers();
    setAiWorkStage("idle");
    setShowAiWorkStage(false);
  };

  const refreshAiConfig = async () => {
    const [modelsRes, personaRes] = await Promise.allSettled([getAiModels(), getPersona()]);
    let loadError: string | null = null;

    if (modelsRes.status === "fulfilled") {
      setAiModels(modelsRes.value.models);
      setActiveModelKey(modelsRes.value.active_model_key);
      setAiSecretsFile(modelsRes.value.secrets_file);
    } else {
      loadError = modelsRes.reason instanceof Error ? modelsRes.reason.message : "加载模型列表失败";
    }

    if (personaRes.status === "fulfilled") {
      setPersonaContent(personaRes.value.content);
      setPersonaUpdatedAt(personaRes.value.updated_at);
    } else if (!loadError) {
      loadError = personaRes.reason instanceof Error ? personaRes.reason.message : "加载 AI 身份失败";
    }

    setAiLoaded(true);
    if (loadError) setError(loadError);
  };

  useEffect(() => {
    void refreshAiConfig();
  }, []);

  useEffect(
    () => () => {
      clearAiStageTimers();
    },
    [],
  );

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const result = await getBacktestResult(jobId);
        if (!active) return;
        setBacktestResult(result);
        if (result.status === "queued" || result.status === "running") {
          setShowAiWorkStage(true);
          setAiWorkStage("coding");
        }
        if (result.status === "failed" && result.error) {
          setError(result.error);
          resetAiWorkStage();
        }
        if (result.status === "finished") {
          completeAiWorkStage();
          window.clearInterval(timer);
        }
        if (result.status === "failed") {
          window.clearInterval(timer);
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "轮询回测结果失败");
        resetAiWorkStage();
        window.clearInterval(timer);
      }
    }, 1500);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [jobId, setBacktestResult]);

  useEffect(() => {
    if (!resizingPanel) return;

    const onMouseMove = (event: MouseEvent) => {
      setPanelWidth(clampPanelWidth(window.innerWidth - event.clientX));
    };
    const onMouseUp = () => setResizingPanel(false);

    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [resizingPanel]);

  useEffect(() => {
    const onResize = () => setPanelWidth((prev) => clampPanelWidth(prev));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!contextMenu) return;

    const closeOnOutside = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (target && contextMenuRef.current?.contains(target)) return;
      setContextMenu(null);
    };
    const closeOnEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextMenu(null);
    };
    const closeOnScroll = () => setContextMenu(null);

    window.addEventListener("mousedown", closeOnOutside);
    window.addEventListener("keydown", closeOnEsc);
    window.addEventListener("resize", closeOnScroll);
    window.addEventListener("scroll", closeOnScroll, true);

    return () => {
      window.removeEventListener("mousedown", closeOnOutside);
      window.removeEventListener("keydown", closeOnEsc);
      window.removeEventListener("resize", closeOnScroll);
      window.removeEventListener("scroll", closeOnScroll, true);
    };
  }, [contextMenu]);

  useEffect(() => {
    setComposeSlots((prev) => ({
      indicator_factor: prev.indicator_factor && cards[prev.indicator_factor] ? prev.indicator_factor : undefined,
      position_adjustment:
        prev.position_adjustment && cards[prev.position_adjustment] ? prev.position_adjustment : undefined,
      risk_system: prev.risk_system && cards[prev.risk_system] ? prev.risk_system : undefined,
      strategy: prev.strategy && cards[prev.strategy] ? prev.strategy : undefined,
    }));
    setBacktestSlotCardId((prev) => (prev && cards[prev] ? prev : undefined));
  }, [cards]);

  const resolveWorkbenchDropPosition = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const rect = workbenchCanvasRef.current?.getBoundingClientRect();
    if (!rect) return null;

    const minX = PAD;
    const minY = PAD;
    const maxX = Math.max(minX, rect.width - CARD_W - PAD);
    const maxY = Math.max(minY, rect.height - CARD_H - PAD);
    const rawX = clientX - rect.left - CARD_W / 2;
    const rawY = clientY - rect.top - CARD_H / 2;

    const clampedX = clamp(rawX, minX, maxX);
    const clampedY = clamp(rawY, minY, maxY);

    return {
      x: clamp(snapGrid(clampedX), minX, maxX),
      y: clamp(snapGrid(clampedY), minY, maxY),
    };
  };

  const handleDragStart = (cardId: string) => (event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.setData("text/plain", cardId);
    event.dataTransfer.effectAllowed = "move";
    setContextMenu(null);
  };

  const handleDropToWorkbench = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const cardId = event.dataTransfer.getData("text/plain");
    if (!cardId) return;

    const snappedPosition = resolveWorkbenchDropPosition(event.clientX, event.clientY);
    const moved = moveCard(cardId, "workbench", snappedPosition ?? undefined);
    if (!moved) setError("目标点位已被占用，已阻止卡牌叠加。");
    else setError(null);
  };

  const handleDropToVault = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const cardId = event.dataTransfer.getData("text/plain");
    if (!cardId) return;
    moveCard(cardId, "vault");
    setError(null);
  };

  const openCardPanel = (cardId: string) => {
    selectCard(cardId);
    setPanelCardId(cardId);
    setContextMenu(null);
  };

  const closeCardPanel = () => {
    setPanelCardId(undefined);
    setResizingPanel(false);
  };

  const handleCardContextMenu = (event: ReactMouseEvent<HTMLDivElement>, cardId: string) => {
    event.preventDefault();
    event.stopPropagation();
    selectCard(cardId);
    setContextMenu({ cardId, x: event.clientX, y: event.clientY });
  };

  const handleContextEquipToggle = (cardId: string) => {
    const card = cards[cardId];
    if (!card || !isModuleCardType(card.cardType)) return;
    const equipped = equippedCardIds[card.cardType] === cardId;
    if (equipped) unequipCard(card.cardType);
    else equipCard(cardId);
    setContextMenu(null);
  };

  const handleContextMoveToggle = (cardId: string) => {
    const card = cards[cardId];
    if (!card) return;

    if (card.zone === "workbench") {
      moveCard(cardId, "vault");
    } else {
      const moved = moveCard(cardId, "workbench");
      if (!moved) setError("装备区空间不足，无法放回。");
    }
    setContextMenu(null);
  };

  const assignComposeSlot = (slot: ComposeSlotKey, cardId: string): boolean => {
    const card = cards[cardId];
    if (!card) return false;

    if (slot === "strategy") {
      if (card.cardType !== "strategy") {
        setError("策略卡槽仅可放入策略卡。");
        return false;
      }
    } else {
      if (card.cardType !== slot) {
        setError(`${composeSlotLabel(slot)} 只能放入 ${cardTypeLabel(slot)} 卡。`);
        return false;
      }
      if (!card.versionId || !card.moduleCode) {
        setError(`${cardTypeLabel(slot)} 卡尚未生成代码，不能用于封装。`);
        return false;
      }
    }

    setComposeSlots((prev) => ({ ...prev, [slot]: cardId }));
    setError(null);
    return true;
  };

  const clearComposeSlot = (slot: ComposeSlotKey) => {
    setComposeSlots((prev) => ({ ...prev, [slot]: undefined }));
  };

  const handleDropToComposeSlot = (slot: ComposeSlotKey) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const cardId = event.dataTransfer.getData("text/plain");
    if (!cardId) return;
    assignComposeSlot(slot, cardId);
  };

  const assignBacktestSlot = (cardId: string): boolean => {
    const card = cards[cardId];
    if (!card || card.cardType !== "strategy") {
      setError("回测槽仅可放入策略卡。");
      return false;
    }
    setBacktestSlotCardId(cardId);
    setError(null);
    return true;
  };

  const handleDropToBacktestSlot = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const cardId = event.dataTransfer.getData("text/plain");
    if (!cardId) return;
    assignBacktestSlot(cardId);
  };

  const handleDeleteCard = (cardId: string) => {
    const card = cards[cardId];
    if (!card) return;
    const ok = window.confirm(`确认删除「${card.title}」？此操作会从持久化数据中移除该卡牌。`);
    if (!ok) return;

    const deleted = deleteCard(cardId);
    if (!deleted) {
      setError("删除失败：未找到目标卡牌。");
      return;
    }

    if (panelCardId === cardId) {
      setPanelCardId(undefined);
      setResizingPanel(false);
    }
    setComposeSlots((prev) => ({
      indicator_factor: prev.indicator_factor === cardId ? undefined : prev.indicator_factor,
      position_adjustment: prev.position_adjustment === cardId ? undefined : prev.position_adjustment,
      risk_system: prev.risk_system === cardId ? undefined : prev.risk_system,
      strategy: prev.strategy === cardId ? undefined : prev.strategy,
    }));
    setBacktestSlotCardId((prev) => (prev === cardId ? undefined : prev));
    setContextMenu(null);
    setError(null);
  };

  const resolveTargetCard = (cardId?: string): StrategyCard | undefined => {
    if (cardId) return cards[cardId];
    if (panelCardId) return cards[panelCardId];
    if (selectedCardId) return cards[selectedCardId];
    return undefined;
  };

  const handleGenerateSelectedCard = async (cardId?: string) => {
    const target = resolveTargetCard(cardId);
    if (!target) {
      setError("请先选中一个卡牌。");
      return;
    }
    if (target.cardType === "strategy") {
      await handleComposeStrategy(target.id);
      return;
    }

    setBusy(`正在生成 ${cardTypeLabel(target.cardType)} 代码...`);
    setError(null);
    startAiWorkStage();
    try {
      const response = await generateModule({
        cardType: target.cardType,
        requirement: target.requirement,
        timeframe,
        pair,
        canShort,
        optimizeTargetCode: hasGeneratedCode(target) ? target.moduleCode : undefined,
        optimizeFromVersionId: hasGeneratedCode(target) ? target.versionId : undefined,
      });
      setCardGenerated(target.id, {
        versionId: response.version_id,
        code: response.module_code,
        explain: response.explain,
      });
      completeAiWorkStage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "模块生成失败");
      resetAiWorkStage();
    } finally {
      setBusy(null);
    }
  };

  const handleComposeStrategy = async (forceCardId?: string) => {
    let strategyCard = forceCardId ? cards[forceCardId] : undefined;
    if (!strategyCard || strategyCard.cardType !== "strategy") {
      strategyCard = composeSlotCards.strategy;
    }
    if (!strategyCard || strategyCard.cardType !== "strategy") {
      setError("请将策略卡放入“策略卡槽”后再执行封装。");
      return;
    }

    const targetCardId = strategyCard.id;
    setComposeSlots((prev) => ({ ...prev, strategy: targetCardId }));

    const indicatorCard = composeSlotCards.indicator_factor;
    const positionCard = composeSlotCards.position_adjustment;
    const riskCard = composeSlotCards.risk_system;

    const hasSlotModules = Boolean(
      indicatorCard?.versionId && positionCard?.versionId && riskCard?.versionId,
    );
    const hasCardSourceModules = Boolean(
      strategyCard.sourceVersionIds?.indicator_factor &&
        strategyCard.sourceVersionIds?.position_adjustment &&
        strategyCard.sourceVersionIds?.risk_system,
    );
    const canStrategyOnlyOptimize = Boolean(strategyCard.moduleCode?.trim());

    if (!hasSlotModules && !hasCardSourceModules && !canStrategyOnlyOptimize) {
      setError("首次封装需要三张已生成代码的模块卡；已有策略卡可直接继续优化。");
      return;
    }

    let indicatorVersionId: string | undefined;
    let positionVersionId: string | undefined;
    let riskVersionId: string | undefined;
    let sourceCardIds: Record<ModuleCardType, string> | undefined;
    let sourceVersionIds: Record<ModuleCardType, string> | undefined;

    if (hasSlotModules && indicatorCard && positionCard && riskCard) {
      indicatorVersionId = indicatorCard.versionId;
      positionVersionId = positionCard.versionId;
      riskVersionId = riskCard.versionId;
      sourceCardIds = {
        indicator_factor: indicatorCard.id,
        position_adjustment: positionCard.id,
        risk_system: riskCard.id,
      };
      sourceVersionIds = {
        indicator_factor: indicatorCard.versionId ?? "-",
        position_adjustment: positionCard.versionId ?? "-",
        risk_system: riskCard.versionId ?? "-",
      };
    } else if (hasCardSourceModules) {
      indicatorVersionId = strategyCard.sourceVersionIds?.indicator_factor;
      positionVersionId = strategyCard.sourceVersionIds?.position_adjustment;
      riskVersionId = strategyCard.sourceVersionIds?.risk_system;
      sourceCardIds = strategyCard.sourceCardIds;
      sourceVersionIds = strategyCard.sourceVersionIds;
    }

    setBusy(hasSlotModules ? "正在封装策略并进行静态校验..." : "正在优化策略并进行静态校验...");
    setError(null);
    startAiWorkStage();

    try {
      const response = await composeStrategy({
        strategyName,
        requirement: strategyCard.requirement ?? "将三个模块整合为可运行的 freqtrade 策略。",
        pair,
        timeframe,
        timerange,
        canShort,
        indicatorVersionId,
        positionVersionId,
        riskVersionId,
        baseStrategyCode: strategyCard.moduleCode,
        baseBuildId: strategyCard.buildId,
      });

      setComposeResult({
        buildId: response.build_id,
        strategyFile: response.strategy_file,
        warnings: response.warnings,
      });
      setStrategyCardComposed(targetCardId, {
        buildId: response.build_id,
        strategyFile: response.strategy_file,
        strategyCode: response.strategy_code,
        explain: response.validation_logs.join("\n") || "策略已完成组合与验证。",
        sourceCardIds,
        sourceVersionIds:
          sourceVersionIds &&
          ({
            indicator_factor: response.source_versions.indicator_factor ?? sourceVersionIds.indicator_factor,
            position_adjustment: response.source_versions.position_adjustment ?? sourceVersionIds.position_adjustment,
            risk_system: response.source_versions.risk_system ?? sourceVersionIds.risk_system,
          } as Record<ModuleCardType, string>),
        optimizationNote: response.optimization_note,
      });

      setBacktestSlotCardId(targetCardId);
      selectCard(targetCardId);
      setPanelCardId(targetCardId);
      completeAiWorkStage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "策略封装失败");
      resetAiWorkStage();
    } finally {
      setBusy(null);
    }
  };

  const handleRunBacktest = async (forceStrategyCardId?: string) => {
    const strategyCard = forceStrategyCardId ? cards[forceStrategyCardId] : backtestSlotCard;
    if (!strategyCard || strategyCard.cardType !== "strategy") {
      setError("请先把封装好的策略卡拖入回测槽。");
      return;
    }

    if (!strategyCard.buildId) {
      setError("回测槽中的策略卡尚未封装完成，请先执行封装。");
      return;
    }

    setBacktestSlotCardId(strategyCard.id);
    setBusy("正在启动回测任务...");
    setError(null);
    startAiWorkStage();
    try {
      const result = await runBacktest({
        buildId: strategyCard.buildId,
        pair,
        timeframe,
        timerange,
      });
      setJob(result.job_id);
      const status: BacktestResult["status"] =
        result.status === "queued" || result.status === "running" || result.status === "finished" || result.status === "failed"
          ? result.status
          : "queued";
      setBacktestResult({
        job_id: result.job_id,
        status,
        logs: [],
      });
      setAiWorkStage("coding");
      setShowAiWorkStage(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动回测失败");
      resetAiWorkStage();
    } finally {
      setBusy(null);
    }
  };

  const handleSaveAiSettings = async () => {
    if (!aiLoaded) return;

    setBusy("正在保存 AI 配置...");
    setError(null);
    try {
      const [modelsRes, personaRes] = await Promise.all([
        activeModelKey ? setActiveAiModel(activeModelKey) : getAiModels(),
        savePersona(personaContent),
      ]);
      setAiModels(modelsRes.models);
      setActiveModelKey(modelsRes.active_model_key);
      setAiSecretsFile(modelsRes.secrets_file);
      setPersonaContent(personaRes.content);
      setPersonaUpdatedAt(personaRes.updated_at);
      setShowAiPanel(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 AI 配置失败");
    } finally {
      setBusy(null);
    }
  };

  const renderCard = (card: StrategyCard, onWorkbench: boolean) => {
    const selected = selectedCardId === card.id;
    const equipped = isModuleCardType(card.cardType) && equippedCardIds[card.cardType] === card.id;
    const cardStyle = onWorkbench
      ? {
          left: `${card.workbenchX ?? PAD}px`,
          top: `${card.workbenchY ?? PAD}px`,
        }
      : undefined;

    return (
      <div
        key={card.id}
        className={[
          "neo-card",
          selected ? "selected" : "",
          equipped ? "equipped" : "",
          onWorkbench ? "workbench-card" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        style={cardStyle}
        draggable
        onDragStart={handleDragStart(card.id)}
        onClick={() => selectCard(card.id)}
        onContextMenu={(event) => handleCardContextMenu(event, card.id)}
      >
        <div className="neo-card-head">
          <span className={`type-pill ${card.cardType}`}>{cardTypeLabel(card.cardType)}</span>
          {equipped ? <span className="equip-pill">已装载</span> : null}
        </div>
        <h3>{card.title}</h3>
        <p>{card.requirement}</p>
        <div className="neo-card-foot">
          {card.cardType === "strategy" ? (
            <span>Build: {shortVersion(card.buildId)}</span>
          ) : (
            <span>Version: {shortVersion(card.versionId)}</span>
          )}
          <span>{onWorkbench ? "装备区" : "仓库"}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="retro-shell">
      <div className="scanline-layer" />

      <header className="retro-topbar">
        <div className="brand-block">
          <h1>Freqtrade Strategy Studio</h1>
          <p>RETRO CARD ASSEMBLER</p>
          <div className="active-model-indicator">
            当前激活模型: {activeModel?.label ?? (activeModelKey || "加载中...")}
          </div>
        </div>
        <div className="toolbar-group">
          <button type="button" onClick={() => createCard("indicator_factor")}>
            新建指标因子卡
          </button>
          <button type="button" onClick={() => createCard("position_adjustment")}>
            新建仓位调整卡
          </button>
          <button type="button" onClick={() => createCard("risk_system")}>
            新建风险系统卡
          </button>
          <button type="button" onClick={() => createStrategyCard(`${strategyName}-策略卡`)}>
            新建策略封装卡
          </button>
          <button type="button" onClick={() => setShowAiPanel(true)}>
            AI 配置中心
          </button>
        </div>
      </header>

      <div className="deck-layout">
        <section className="workbench-zone">
          <div className="zone-title">装备区</div>
          <div className="zone-subtitle">右键卡牌可选属性、装载/卸载、移入仓库。拖拽时按点阵吸附，禁止叠放。</div>
          <div
            className="retro-canvas"
            ref={workbenchCanvasRef}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDropToWorkbench}
          >
            <RetroBackdrop />
            <div className="cards-layer workbench-layer">{workbenchCards.map((card) => renderCard(card, true))}</div>
          </div>
        </section>

        <section className="vault-zone">
          <div className="zone-title">仓库区</div>
          <div className="zone-subtitle">拖入这里暂存模块卡或策略卡，右键可放回装备区。</div>
          <div className="vault-list" onDragOver={(event) => event.preventDefault()} onDrop={handleDropToVault}>
            {vaultCards.length === 0 ? <div className="empty-tip">仓库为空，拖拽卡牌到这里进行暂存。</div> : null}
            {vaultCards.map((card) => renderCard(card, false))}
          </div>
        </section>
      </div>

      <div className="workflow-layout">
        <section className="assembly-zone">
          <div className="zone-title">策略封装区</div>
          <div className="zone-subtitle">
            新策略可放入三张模块卡 + 策略卡进行封装；已生成策略卡可直接继续优化，无需再次放置三模块。
          </div>

          <div className="control-grid">
            <label>
              策略名
              <input value={strategyName} onChange={(event) => setStrategyMeta(event.target.value)} />
            </label>
            <label className="toggle-item">
              <input type="checkbox" checked={canShort} onChange={(event) => setCanShort(event.target.checked)} />
              允许做空
            </label>
          </div>

          <div className="compose-slot-grid">
            {COMPOSE_SLOT_ORDER.map((slot) => {
              const slotCard = composeSlotCards[slot];
              const slotVersion =
                slotCard?.cardType === "strategy" ? shortVersion(slotCard.buildId) : shortVersion(slotCard?.versionId);
              return (
                <div
                  key={slot}
                  className="compose-slot"
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={handleDropToComposeSlot(slot)}
                >
                  <div className="compose-slot-title">{composeSlotLabel(slot)}</div>
                  {!slotCard ? (
                    <div className="empty-tip">{composeSlotHint(slot)}</div>
                  ) : (
                    <div className="compose-slot-card">
                      <strong>{slotCard.title}</strong>
                      <code>{slotVersion}</code>
                      <div className="compose-slot-actions">
                        <button type="button" onClick={() => selectCard(slotCard.id)}>
                          定位卡牌
                        </button>
                        <button type="button" onClick={() => clearComposeSlot(slot)}>
                          清空槽位
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="action-row">
            <button type="button" disabled={Boolean(busy)} onClick={() => void handleComposeStrategy()}>
              封装生成策略
            </button>
            <button
              type="button"
              disabled={Boolean(busy) || !selectedCardId}
              onClick={() => (selectedCardId ? duplicateCard(selectedCardId) : undefined)}
            >
              复制当前卡牌
            </button>
          </div>
        </section>

        <section className="backtest-zone">
          <div className="zone-title">回测配置区</div>
          <div className="zone-subtitle">拖入已封装策略卡，选择交易对、周期、区间后执行回测。</div>

          <div className="backtest-setup-grid">
            <div className="backtest-slot" onDragOver={(event) => event.preventDefault()} onDrop={handleDropToBacktestSlot}>
              <div className="compose-slot-title">回测策略槽</div>
              {!backtestSlotCard ? (
                <div className="empty-tip">拖入已封装策略卡（含 Build）。</div>
              ) : (
                <div className="compose-slot-card">
                  <strong>{backtestSlotCard.title}</strong>
                  <code>Build: {shortVersion(backtestSlotCard.buildId)}</code>
                  <div className="compose-slot-actions">
                    <button type="button" onClick={() => selectCard(backtestSlotCard.id)}>
                      定位卡牌
                    </button>
                    <button type="button" onClick={() => setBacktestSlotCardId(undefined)}>
                      清空槽位
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="backtest-config-panel">
              <div className="control-grid backtest-control-grid">
                <label>
                  交易对
                  <input value={pair} onChange={(event) => setBacktestConfig("pair", event.target.value)} />
                </label>
                <label>
                  周期
                  <input value={timeframe} onChange={(event) => setBacktestConfig("timeframe", event.target.value)} />
                </label>
                <label>
                  回测区间
                  <input value={timerange} onChange={(event) => setBacktestConfig("timerange", event.target.value)} />
                </label>
              </div>

              <div className="action-row">
                <button type="button" disabled={Boolean(busy)} onClick={() => void handleRunBacktest()}>
                  执行回测
                </button>
              </div>

              <div className="build-state">
                <div>当前 Build: {shortVersion(buildId)}</div>
                <div>策略文件: {strategyFile ?? "-"}</div>
                <div>回测任务: {jobId ?? "-"}</div>
                <div>回测状态: {backtestStatusLabel(backtestResult?.status)}</div>
                <div>自动修复轮次: {backtestResult?.repair_rounds ?? 0}</div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="result-zone analytics-zone">
        <div className="zone-title">回测结果区</div>
        <div className="zone-subtitle">执行回测后这里展示收益摘要、资金曲线与日志。</div>

        {backtestResult?.summary ? (
          <div className="summary-grid">
            <div>
              <div>交易次数</div>
              <strong>{backtestResult.summary.trades}</strong>
            </div>
            <div>
              <div>胜率</div>
              <strong>{backtestResult.summary.winrate.toFixed(2)}%</strong>
            </div>
            <div>
              <div>总收益</div>
              <strong>{backtestResult.summary.profit_total_pct.toFixed(2)}%</strong>
            </div>
            <div>
              <div>绝对收益</div>
              <strong>{backtestResult.summary.profit_total_abs.toFixed(4)}</strong>
            </div>
            <div>
              <div>最大回撤</div>
              <strong>{backtestResult.summary.max_drawdown_pct.toFixed(2)}%</strong>
            </div>
            <div>
              <div>Profit Factor</div>
              <strong>{backtestResult.summary.profit_factor?.toFixed(3) ?? "-"}</strong>
            </div>
            <div>
              <div>回测本金</div>
              <strong>{backtestResult.summary.starting_balance?.toFixed(2) ?? "-"}</strong>
            </div>
            <div>
              <div>可用资金比例</div>
              <strong>
                {backtestResult.summary.tradable_balance_ratio !== undefined
                  ? `${(backtestResult.summary.tradable_balance_ratio * 100).toFixed(1)}%`
                  : "-"}
              </strong>
            </div>
          </div>
        ) : (
          <div className="empty-tip">回测完成后会显示收益摘要与图表。</div>
        )}

        {backtestResult?.ai_review ? (
          <div className="ai-review-panel">
            <div className="zone-subtitle">AI 专家评价</div>
            <div className="ai-review-text">{backtestResult.ai_review}</div>
          </div>
        ) : null}

        {backtestResult?.series ? <BacktestCharts result={backtestResult} /> : null}

        <div className="result-logs">
          <div className="zone-subtitle">回测日志</div>
          <pre>{(backtestResult?.logs ?? []).join("\n") || "暂无日志"}</pre>
        </div>

        {lintWarnings.length > 0 ? (
          <div className="result-logs">
            <div className="zone-subtitle">策略校验提示</div>
            <pre>{lintWarnings.join("\n")}</pre>
          </div>
        ) : null}
      </section>

      {contextMenu ? (
        <div ref={contextMenuRef} className="context-menu" style={contextMenuStyle}>
          <button type="button" className="context-menu-item" onClick={() => openCardPanel(contextMenu.cardId)}>
            属性
          </button>
          {isModuleCardType(cards[contextMenu.cardId]?.cardType ?? "strategy") ? (
            <button type="button" className="context-menu-item" onClick={() => handleContextEquipToggle(contextMenu.cardId)}>
              {equippedCardIds[cards[contextMenu.cardId].cardType as ModuleCardType] === contextMenu.cardId
                ? "卸载"
                : "装载"}
            </button>
          ) : null}
          <button type="button" className="context-menu-item" onClick={() => handleContextMoveToggle(contextMenu.cardId)}>
            {cards[contextMenu.cardId]?.zone === "workbench" ? "移入仓库" : "放回装备区"}
          </button>
          <button type="button" className="context-menu-item danger" onClick={() => handleDeleteCard(contextMenu.cardId)}>
            删除卡牌
          </button>
        </div>
      ) : null}

      {panelCard ? (
        <div className="card-panel-overlay" onMouseDown={closeCardPanel}>
          <div className="card-panel-shell" style={{ width: `${panelWidth}px` }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-resize-handle" onMouseDown={() => setResizingPanel(true)} />
            <div className="card-panel">
              <div className="card-panel-title">
                <h2>{cardTypeLabel(panelCard.cardType)}属性</h2>
                <button type="button" onClick={closeCardPanel}>
                  关闭
                </button>
              </div>

              <label>
                卡牌标题
                <input value={panelCard.title} onChange={(event) => updateCardTitle(panelCard.id, event.target.value)} />
              </label>

              <label>
                {requirementFieldLabel(panelCard)}
                <textarea
                  value={panelCard.requirement}
                  onChange={(event) => updateCardRequirement(panelCard.id, event.target.value)}
                />
              </label>

              {panelCard.cardType === "strategy" && panelCard.sourceCardIds ? (
                <div className="strategy-source">
                  <div className="strategy-source-column">
                    <strong>模块来源</strong>
                    <code>指标因子: {panelCard.sourceCardIds.indicator_factor}</code>
                    <code>仓位调整: {panelCard.sourceCardIds.position_adjustment}</code>
                    <code>风险系统: {panelCard.sourceCardIds.risk_system}</code>
                  </div>
                  <div className="strategy-source-column">
                    <strong>来源版本</strong>
                    <code>指标因子: {panelCard.sourceVersionIds?.indicator_factor ?? "-"}</code>
                    <code>仓位调整: {panelCard.sourceVersionIds?.position_adjustment ?? "-"}</code>
                    <code>风险系统: {panelCard.sourceVersionIds?.risk_system ?? "-"}</code>
                  </div>
                </div>
              ) : null}

              <div className="card-panel-actions">
                <button type="button" disabled={Boolean(busy)} onClick={() => void handleGenerateSelectedCard(panelCard.id)}>
                  {generateActionLabel(panelCard)}
                </button>
                <button type="button" disabled={Boolean(busy)} onClick={() => duplicateCard(panelCard.id)}>
                  复制卡牌
                </button>
                <button type="button" className="danger" onClick={() => handleDeleteCard(panelCard.id)}>
                  删除卡牌
                </button>
                {isModuleCardType(panelCard.cardType) ? (
                  <button type="button" onClick={() => handleContextEquipToggle(panelCard.id)}>
                    {equippedCardIds[panelCard.cardType] === panelCard.id ? "卸载模块" : "装载模块"}
                  </button>
                ) : (
                  <button type="button" disabled={Boolean(busy)} onClick={() => void handleRunBacktest(panelCard.id)}>
                    用该策略回测
                  </button>
                )}
              </div>

              <div className="card-panel-meta">
                <div className="meta-pair">
                  <div className="meta-item-inline">
                    <span className="meta-label-inline">ID:</span>
                    <code>{panelCard.id}</code>
                  </div>
                  <div className="meta-item-inline">
                    <span className="meta-label-inline">{panelCard.cardType === "strategy" ? "Build:" : "Version:"}</span>
                    <code>{panelCard.cardType === "strategy" ? shortVersion(panelCard.buildId) : shortVersion(panelCard.versionId)}</code>
                  </div>
                </div>

                <div className="meta-pair">
                  <div className="meta-item-inline">
                    <span className="meta-label-inline">创建时间:</span>
                    <span className="meta-value-inline">{formatTime(panelCard.createdAt)}</span>
                  </div>
                  <div className="meta-item-inline">
                    <span className="meta-label-inline">更新时间:</span>
                    <span className="meta-value-inline">{formatTime(panelCard.updatedAt)}</span>
                  </div>
                </div>

                {panelCard.cardType === "strategy" ? (
                  <div className="meta-item-inline meta-wide">
                    <span className="meta-label-inline">策略文件:</span>
                    <span className="meta-value-inline">{panelCard.strategyFile ?? "-"}</span>
                  </div>
                ) : null}
              </div>

              <div className="card-code-preview">
                <pre>{panelCard.moduleCode ?? "尚未生成代码。右键卡牌 -> 属性，然后点击生成代码。"}</pre>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {showAiPanel ? (
        <div className="card-panel-overlay" onMouseDown={() => setShowAiPanel(false)}>
          <div className="card-panel-shell" style={{ width: `${panelWidth}px` }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-resize-handle" onMouseDown={() => setResizingPanel(true)} />
            <div className="card-panel ai-panel">
              <div className="card-panel-title">
                <h2>AI 配置中心</h2>
                <button type="button" onClick={() => setShowAiPanel(false)}>
                  关闭
                </button>
              </div>

              <label>
                当前模型
                <select value={activeModelKey} onChange={(event) => setActiveModelKey(event.target.value)}>
                  {aiModels.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="card-panel-meta">
                <div>配置文件: {aiSecretsFile || "-"}</div>
                <div>身份文档更新时间: {personaUpdatedAt || "-"}</div>
              </div>

              <label>
                AI 身份设定 (persona.md)
                <textarea
                  value={personaContent}
                  onChange={(event) => setPersonaContent(event.target.value)}
                  placeholder="在这里输入策略工程师身份、风格和边界要求。"
                />
              </label>

              <div className="card-panel-actions">
                <button type="button" disabled={Boolean(busy) || !aiLoaded} onClick={() => void handleSaveAiSettings()}>
                  保存配置
                </button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void refreshAiConfig()}>
                  重新加载
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <footer className="status-bar">
        <div className="status-main">
          <div>{busy ?? "系统就绪"}</div>
          <div className="autosave-tip">卡牌与策略自动保存已启用</div>
          {showAiWorkStage ? (
            <div className="ai-work-progress">
              {AI_STAGE_ORDER.map((stage) => (
                <span key={stage} className={stageClass(aiWorkStage, stage)}>
                  {aiStageLabel(stage)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="error-text">{error ?? ""}</div>
      </footer>
    </div>
  );
}
