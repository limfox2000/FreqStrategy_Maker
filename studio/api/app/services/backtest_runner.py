from __future__ import annotations

import json
import subprocess
import threading
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..schemas.backtest import BacktestResultResponse, BacktestRunRequest, BacktestRunResponse
from .ai_runtime import get_ai_identity
from .llm_adapter import LlmAdapterError, complete_text
from .storage import BACKTEST_RESULTS_DIR, FREQTRADE_DIR, JOB_DIR, new_id, read_json, write_json
from .strategy_composer import load_build, repair_strategy_file, repair_strategy_with_ai


_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
MAX_BACKTEST_REPAIR_ROUNDS = 2


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["logs"].append(line.rstrip())


def _update_job(job_id: str, **kwargs: Any) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kwargs)
            write_json(JOB_DIR / f"{job_id}.json", _JOBS[job_id])


def _container_strategy_path(host_strategy_path: Path) -> str:
    return f"/freqtrade/user_data/strategies/generated/{host_strategy_path.name}"


def _is_valid_timeframe(value: str) -> bool:
    return bool(re.fullmatch(r"\d+[mhdwM]", value.strip()))


def _extract_strategy_timeframes(strategy_file: Path) -> tuple[str | None, list[str]]:
    text = strategy_file.read_text(encoding="utf-8", errors="ignore")

    main_timeframe: str | None = None
    main_match = re.search(r"(?m)^\s*timeframe\s*=\s*['\"](\d+[mhdwM])['\"]\s*$", text)
    if main_match:
        main_timeframe = main_match.group(1)

    timeframes: list[str] = []
    patterns = [
        r"@informative\s*\(\s*['\"](\d+[mhdwM])['\"]",
        r"@informative\s*\([^)]*timeframe\s*=\s*['\"](\d+[mhdwM])['\"]",
        r"merge_informative_pair\s*\([^)]*['\"](\d+[mhdwM])['\"]",
        r"get_pair_dataframe\s*\([^)]*timeframe\s*=\s*['\"](\d+[mhdwM])['\"]",
    ]
    for pattern in patterns:
        for tf in re.findall(pattern, text, flags=re.IGNORECASE):
            if _is_valid_timeframe(tf):
                timeframes.append(tf)

    dedup: list[str] = []
    seen: set[str] = set()
    for tf in timeframes:
        key = tf.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(tf)

    return main_timeframe, dedup


def _resolve_backtest_timeframes(strategy_file: Path, request_timeframe: str) -> tuple[str, list[str]]:
    strategy_main, strategy_extra = _extract_strategy_timeframes(strategy_file)

    base = strategy_main if (strategy_main and _is_valid_timeframe(strategy_main)) else request_timeframe
    if not _is_valid_timeframe(base):
        base = "1m"

    download_tfs: list[str] = [base]
    seen = {base.lower()}
    for tf in strategy_extra:
        if tf.lower() in seen:
            continue
        download_tfs.append(tf)
        seen.add(tf.lower())

    return base, download_tfs


def _trading_mode_from_pair(pair: str) -> str:
    return "futures" if ":" in pair else "spot"


def _run_command(
    job_id: str,
    command: list[str],
    timeout_sec: int,
    timeout_error: str,
) -> tuple[int | None, str | None, list[str]]:
    try:
        process = subprocess.Popen(
            command,
            cwd=str(FREQTRADE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        return None, f"Docker command not found: {exc}", []

    try:
        stdout, _ = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        process.kill()
        return None, timeout_error, []

    lines = (stdout or "").splitlines()
    for line in lines:
        _append_log(job_id, line)

    return process.returncode, None, lines


def _summarize_backtest_locally(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "回测已完成，建议结合交易明细继续评估策略稳定性。"

    profit_pct = float(summary.get("profit_total_pct", 0.0))
    drawdown_pct = float(summary.get("max_drawdown_pct", 0.0))
    winrate = float(summary.get("winrate", 0.0))
    trades = int(summary.get("trades", 0))
    profit_factor_raw = summary.get("profit_factor")
    profit_factor = float(profit_factor_raw) if isinstance(profit_factor_raw, (int, float)) else None

    verdict = "策略表现偏弱，建议先优化入场与风控。"
    if profit_pct > 0 and drawdown_pct <= 20 and (profit_factor is None or profit_factor >= 1.1):
        verdict = "策略表现较稳健，可考虑继续做参数细化。"
    if profit_pct > 5 and drawdown_pct <= 12 and winrate >= 45:
        verdict = "策略表现良好，可进入下一轮样本外验证。"

    pf_text = f"{profit_factor:.2f}" if profit_factor is not None else "-"
    return (
        f"{verdict} 交易{trades}次，胜率{winrate:.1f}%，收益{profit_pct:.2f}%，"
        f"最大回撤{drawdown_pct:.2f}%，Profit Factor={pf_text}。"
    )


def _build_backtest_review(summary: dict[str, Any] | None) -> str:
    local_review = _summarize_backtest_locally(summary)
    if not summary:
        return local_review

    try:
        identity = get_ai_identity()
        if not identity.api_key:
            return local_review

        system_prompt = (
            "You are a quantitative trading reviewer.\n"
            "Given backtest metrics, produce one concise Chinese evaluation in <= 80 Chinese characters.\n"
            "Do not output markdown."
        )
        user_prompt = (
            "请基于以下回测摘要，给出一句简短评价，包含一个可执行改进方向。\n"
            f"{json.dumps(summary, ensure_ascii=False)}"
        )
        completion = complete_text(identity, system_prompt, user_prompt)
        review = " ".join(completion.text.strip().split())
        if not review:
            return local_review
        return review[:180]
    except LlmAdapterError:
        return local_review
    except Exception:  # noqa: BLE001
        return local_review


def _run_job(
    job_id: str,
    request: BacktestRunRequest,
    strategy_file: Path,
    strategy_name: str,
    strategy_requirement: str,
) -> None:
    _update_job(job_id, status="running")

    output_host_path = BACKTEST_RESULTS_DIR / f"mvp_{job_id}.json"
    output_container_path = f"/freqtrade/user_data/backtest_results/mvp_{job_id}.json"
    trading_mode = _trading_mode_from_pair(request.pair)
    repair_rounds = 0

    while True:
        backtest_timeframe, download_timeframes = _resolve_backtest_timeframes(strategy_file, request.timeframe)
        if backtest_timeframe != request.timeframe:
            _append_log(
                job_id,
                f"[mvp-backtest] strategy timeframe override: request={request.timeframe} resolved={backtest_timeframe}",
            )

        _append_log(
            job_id,
            (
                f"[mvp-backtest] download-data: pair={request.pair} "
                f"timeframes={','.join(download_timeframes)} range={request.timerange} mode={trading_mode}"
            ),
        )
        download_command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "freqtrade",
            "freqtrade",
            "download-data",
            "--config",
            "/freqtrade/user_data/config.json",
            "--pairs",
            request.pair,
            "--timeframes",
            *download_timeframes,
            "--timerange",
            request.timerange,
            "--trading-mode",
            trading_mode,
        ]
        download_code, download_error, download_lines = _run_command(
            job_id,
            download_command,
            timeout_sec=1200,
            timeout_error="data download timeout (over 20 minutes)",
        )
        if download_error is not None:
            _update_job(job_id, status="failed", error=download_error, repair_rounds=repair_rounds)
            return
        if download_code != 0:
            download_tail = "\n".join([line for line in download_lines if line.strip()][-24:])
            _update_job(
                job_id,
                status="failed",
                error=(
                    f"download-data exited with code {download_code}"
                    + (f"\n{download_tail}" if download_tail else "")
                ),
                repair_rounds=repair_rounds,
            )
            return

        _append_log(
            job_id,
            (
                f"[mvp-backtest] running strategy backtest: pair={request.pair} "
                f"timeframe={backtest_timeframe} range={request.timerange}"
            ),
        )
        command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "freqtrade",
            "/freqtrade/user_data/tools/mvp_backtest_runner.py",
            "--strategy",
            _container_strategy_path(strategy_file),
            "--pair",
            request.pair,
            "--timeframe",
            backtest_timeframe,
            "--timerange",
            request.timerange,
            "--output",
            output_container_path,
        ]

        code, run_error, run_lines = _run_command(
            job_id,
            command,
            timeout_sec=1800,
            timeout_error="backtest timeout (over 30 minutes)",
        )
        if run_error is not None:
            _update_job(job_id, status="failed", error=run_error, repair_rounds=repair_rounds)
            return

        if code == 0:
            break

        if repair_rounds >= MAX_BACKTEST_REPAIR_ROUNDS:
            run_tail = "\n".join([line for line in run_lines if line.strip()][-24:])
            _update_job(
                job_id,
                status="failed",
                error=(
                    f"backtest process exited with code {code}"
                    + (f"\n{run_tail}" if run_tail else "")
                ),
                repair_rounds=repair_rounds,
            )
            return

        repair_rounds += 1
        _append_log(job_id, f"[mvp-backtest] ai-expert repair round {repair_rounds}/{MAX_BACKTEST_REPAIR_ROUNDS}")

        try:
            current_code = strategy_file.read_text(encoding="utf-8")
            repaired_code, repair_note = repair_strategy_with_ai(
                strategy_name=strategy_name,
                requirement=strategy_requirement,
                current_code=current_code,
                error_lines=run_lines[-200:],
            )
            strategy_file.write_text(repaired_code, encoding="utf-8")
            _append_log(job_id, f"[mvp-backtest] ai-expert repaired strategy: {repair_note}")
        except HTTPException as exc:
            _update_job(
                job_id,
                status="failed",
                error=f"ai-expert repair failed: {exc.detail}",
                repair_rounds=repair_rounds,
            )
            return
        except Exception as exc:  # noqa: BLE001
            _update_job(
                job_id,
                status="failed",
                error=f"ai-expert repair failed: {exc}",
                repair_rounds=repair_rounds,
            )
            return

    if not output_host_path.exists():
        _update_job(job_id, status="failed", error=f"result file not found: {output_host_path}", repair_rounds=repair_rounds)
        return

    payload = read_json(output_host_path)
    summary_payload = payload.get("summary", {})
    ai_review = _build_backtest_review(summary_payload if isinstance(summary_payload, dict) else None)
    _append_log(job_id, f"[mvp-backtest] ai-review: {ai_review}")

    artifacts = payload.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}

    _update_job(
        job_id,
        status="finished",
        summary=summary_payload,
        series=payload.get("series", {}),
        artifacts=artifacts,
        ai_review=ai_review,
        repair_rounds=repair_rounds,
    )


def start_backtest(request: BacktestRunRequest) -> BacktestRunResponse:
    build = load_build(request.build_id)
    strategy_file = Path(build["strategy_file"])
    strategy_name = str(build.get("strategy_name", strategy_file.stem))
    strategy_requirement = str(build.get("requirement", "Maintain strategy intent while fixing backtest runtime issues."))

    try:
        repair_strategy_file(strategy_file, strategy_name=strategy_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"strategy file invalid: {exc}") from exc

    job_id = new_id("bt")
    job = {
        "job_id": job_id,
        "status": "queued",
        "logs": [],
        "summary": None,
        "series": {},
        "artifacts": {
            "strategy_file": str(strategy_file),
        },
        "ai_review": None,
        "repair_rounds": 0,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job
    write_json(JOB_DIR / f"{job_id}.json", job)

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request, strategy_file, strategy_name, strategy_requirement),
        daemon=True,
    )
    thread.start()
    return BacktestRunResponse(job_id=job_id, status="queued")


def get_backtest_result(job_id: str) -> BacktestResultResponse:
    with _LOCK:
        job = _JOBS.get(job_id)

    if job is None:
        path = JOB_DIR / f"{job_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
        job = read_json(path)

    return BacktestResultResponse(
        job_id=job["job_id"],
        status=job["status"],
        logs=job.get("logs", []),
        summary=job.get("summary"),
        series=job.get("series", {}),
        artifacts=job.get("artifacts", {}),
        ai_review=job.get("ai_review"),
        repair_rounds=int(job.get("repair_rounds", 0) or 0),
        error=job.get("error"),
    )
