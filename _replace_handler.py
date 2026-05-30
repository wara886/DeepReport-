"""Replace _handle_chat in web_ui.py with the new routing logic.

Reads web_ui.py, replaces the _handle_chat method body (from "def _handle_chat"
to just before the next "def _send_artifact"), writes back.
"""
import re

with open("src/app/web_ui.py", "r", encoding="utf-8") as f:
    source = f.read()

# Locate the old _handle_chat method
start_marker = "        def _handle_chat(self) -> None:"
# Next def after _handle_chat is _send_artifact
end_marker = "\n        def _send_artifact"

start_idx = source.find(start_marker)
end_idx = source.find(end_marker, start_idx)
if start_idx == -1 or end_idx == -1:
    print("ERROR: cannot find _handle_chat boundaries")
    exit(1)

# The old method text (includes trailing newline before _send_artifact)
old_text = source[start_idx:end_idx]

new_handle_chat = r"""        def _handle_chat(self) -> None:
            payload = self._read_json_body()
            message = str(payload.get("message") or "").strip()
            session_id = str(payload.get("session_id") or "local")
            user_id = str(payload.get("user_id") or "local_user")
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or latest_completed_period()).strip().upper()
            allow_report_run = bool(payload.get("allow_report_run", True))
            enable_remote_data = bool(payload.get("enable_remote_data", True))
            request_id = str(payload.get("request_id") or f"req_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")

            # --- Query Understanding Layer ---
            qu = QueryUnderstanding(config_path=config_path)
            intent = qu.intent_classify(message)
            if intent in ("report_generation", "data_query", "report_revision_request"):
                normalized = qu.normalize_query(message)
                message = normalized if normalized.strip() else message
            entities = qu.extract_entities(message, current_symbol=symbol, current_period=period, today=date.today())
            if entities.get("symbol"):
                payload["symbol"] = entities["symbol"]
                symbol = entities["symbol"]
            if entities.get("period"):
                payload["period"] = entities["period"]
                period = entities["period"]
            engines = _parse_engines(payload.get("engines") or default_engines_for_symbol(symbol, enable_remote_data))

            # --- Intent routing by priority ---

            # [1] report_artifact_request — highest priority, before pending_task
            if intent == "report_artifact_request":
                artifact = resolve_report_artifact(
                    output_root=output_root,
                    report_root=report_root,
                    symbol=symbol,
                    period=period,
                )
                if artifact["found"]:
                    answer = f"我找到了之前生成的 {artifact['symbol']} 财报，可以直接打开："
                    self._send_json({
                        "mode": "report_artifact",
                        "answer": answer,
                        "report_links": artifact["report_links"],
                        "symbol": artifact["symbol"],
                        "period": artifact["period"],
                        "run_id": artifact["run_id"],
                        "request_id": request_id,
                        "session_id": session_id,
                    })
                else:
                    answer = (
                        "我没有找到已生成的报告。你可以点击下方按钮生成一份新报告。"
                        if mode == "user"
                        else "未找到匹配的已有报告。"
                    )
                    self._send_json({
                        "mode": "report_artifact",
                        "answer": answer,
                        "found": False,
                        "request_id": request_id,
                        "session_id": session_id,
                    })
                return

            # [2] confirmation / cancel_or_modify — consume or clear pending_task
            pending_task = pending_report_tasks.get(session_id)
            if intent == "confirmation" and pending_task and allow_report_run:
                pending_symbol = str(pending_task.get("symbol") or "").strip().upper()
                if not pending_symbol:
                    self._send_json({
                        "mode": "confirm_report",
                        "answer": "还缺少公司身份信息，请先提供公司名称或 ticker（含交易所）再确认生成。",
                        "parsed_task": pending_task,
                        "request_id": request_id,
                    })
                    return
                symbol = pending_symbol
                period = str(pending_task.get("period") or period).strip().upper()
                payload["topic"] = str(pending_task.get("research_topic") or f"生成 {symbol} {period} 公司财报研报")
                chat_message = str(payload["topic"])
                parsed_task = llm_parse_chat_task(
                    chat_message,
                    current_symbol=symbol,
                    current_period=period,
                    config_path=config_path,
                )
                parsed_task = replace(parsed_task, should_run=True, needs_confirmation=False)
                pending_report_tasks.pop(session_id, None)
                _proceed_to_generation = True

            elif intent == "cancel_or_modify":
                pending_report_tasks.pop(session_id, None)
                self._send_json({
                    "mode": "general_chat",
                    "answer": "已取消当前操作。请重新输入公司名称或报告要求。",
                    "request_id": request_id,
                    "session_id": session_id,
                })
                return

            else:
                # For any other intent, clear pending task (don't let it hijack)
                if pending_task and intent != "report_generation":
                    pending_report_tasks.pop(session_id, None)
                parsed_task = llm_parse_chat_task(
                    message, current_symbol=symbol, current_period=period, config_path=config_path
                )
                _proceed_to_generation = False

            # [3] quality_review — no generation progress
            if intent == "quality_review":
                response = chat_service.handle_chat(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    symbol=symbol,
                    period=period,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    allow_report_run=False,
                    orchestrator=None,
                    engines=engines,
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                )
                response["mode"] = "quality_review"
                response["request_id"] = request_id
                response["parsed_task"] = parsed_task.to_dict()
                self._send_json(response)
                return

            # [4] report_revision_request — LLM chat about modifying existing report
            if intent == "report_revision_request":
                response = chat_service.handle_chat(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    symbol=symbol,
                    period=period,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    allow_report_run=False,
                    orchestrator=None,
                    engines=engines,
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                )
                response["mode"] = "general_chat"
                response["request_id"] = request_id
                self._send_json(response)
                return

            # [5] data_query — existing flow, no progress
            if intent == "data_query":
                metric_hint = entities.get("metric_hint", "")
                topic_prefix = f"查询 {symbol} {period} {metric_hint}" if metric_hint else f"查询 {symbol} {period} 财务数据"
                payload["topic"] = topic_prefix
                chat_response = chat_service.handle_chat(
                    message=f"{topic_prefix}：{message}",
                    session_id=session_id,
                    user_id=user_id,
                    symbol=symbol,
                    period=period,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    allow_report_run=False,
                    orchestrator=None,
                    engines=engines,
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                )
                chat_response["mode"] = "data_query"
                chat_response["request_id"] = request_id
                chat_response["parsed_task"] = {
                    "symbol": symbol, "period": period, "intent": intent,
                    "metric_hint": metric_hint, "query": message,
                }
                self._send_json(chat_response)
                return

            # [6] report_generation — existing flow with confirmation + progress
            confirmed_pending = bool(
                allow_report_run
                and intent == "confirmation"
                and locals().get("_proceed_to_generation", False)
            )
            if intent == "report_generation" or confirmed_pending:
                if parsed_task.should_run or parsed_task.needs_confirmation:
                    symbol = parsed_task.symbol
                    period = parsed_task.period
                    payload["topic"] = parsed_task.research_topic
                raw_engines = payload.get("engines")
                if _should_reset_engines_for_parsed_task(
                    parsed_task.should_run or parsed_task.needs_confirmation,
                    raw_engines,
                    symbol=symbol,
                    realtime=enable_remote_data,
                ):
                    raw_engines = default_engines_for_symbol(symbol, enable_remote_data)
                engines = _parse_engines(raw_engines or default_engines_for_symbol(symbol, enable_remote_data))

                if allow_report_run and (confirmed_pending or parsed_task.should_run or parsed_task.needs_confirmation):
                    guard = validate_period_for_report(period)
                    if not guard["ok"]:
                        response = chat_service.handle_chat(
                            message=message,
                            session_id=session_id,
                            user_id=user_id,
                            symbol=symbol,
                            period=period,
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                            allow_report_run=False,
                            orchestrator=None,
                            engines=engines,
                            fast=bool(payload.get("fast", True)),
                            execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                            enable_remote_data=enable_remote_data,
                            data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                        )
                        response["mode"] = "period_guard"
                        response["period_guard"] = guard
                        response["parsed_task"] = parsed_task.to_dict()
                        response["answer"] = guard["message"]
                        response["request_id"] = request_id
                        self._send_json(response)
                        return

                    if not confirmed_pending and parsed_task.needs_confirmation:
                        pending_report_tasks[session_id] = parsed_task.to_dict()
                        _c_identity = resolve_company_identity(
                            parsed_task.symbol or "", default=parsed_task.symbol or ""
                        )
                        response = chat_service.handle_chat(
                            message=message,
                            session_id=session_id,
                            user_id=user_id,
                            symbol=symbol,
                            period=period,
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                            allow_report_run=False,
                            orchestrator=None,
                            engines=engines,
                            fast=bool(payload.get("fast", True)),
                            execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                            enable_remote_data=enable_remote_data,
                            data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                        )
                        response["mode"] = "confirm_report"
                        response["parsed_task"] = parsed_task.to_dict()
                        response["answer"] = _confirmation_prompt(
                            parsed_task.symbol, parsed_task.period, engines, mode
                        )
                        response["confirm_data"] = {
                            "company_name": str(_c_identity.company_name or parsed_task.symbol or ""),
                            "symbol": str(_c_identity.canonical_symbol or parsed_task.symbol or ""),
                            "market": _market_label(parsed_task.symbol or ""),
                            "period": str(parsed_task.period or ""),
                            "analysis_scope": ["三表摘要", "财务分析", "估值观察", "风险提示", "投资结论"],
                            "data_sources_hint": "公司公开披露、SEC 文件、行情数据和公开资料",
                        }
                        response["request_id"] = request_id
                        self._send_json(response)
                        return

                    # confirmed_pending or parsed_task.should_run — execute generation
                    execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
                    execution_tier = str(payload.get("execution_tier") or "delivery")
                    async_report_run = bool(payload.get("async_report_run", False))
                    run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode)
                    orchestrator = MultiAgentOrchestrator(
                        output_dir=str(run_paths["output_dir"]),
                        report_dir=str(run_paths["report_dir"]),
                        config_path=config_path,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        memory_root=str(Path(memory_root) / "durable"),
                        execution_tier=execution_tier,
                    )
                    run_kwargs = {
                        "research_topic": str(payload.get("topic") or parsed_task.research_topic or message),
                        "symbol": symbol,
                        "period": period,
                        "execution_mode": execution_mode,
                        "fast": bool(payload.get("fast", True)),
                        "search_engines": engines,
                        "enable_remote_data": enable_remote_data,
                        "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    }
                    _mark_active_run(
                        session_id,
                        symbol=symbol,
                        period=period,
                        topic=str(run_kwargs["research_topic"]),
                        execution_mode=str(run_kwargs["execution_mode"]),
                        source="chat",
                    )

                    def _run_report_background() -> None:
                        try:
                            result = orchestrator.run(**run_kwargs)
                            quality_result = run_delivery_quality_pipeline(
                                run_paths["output_dir"],
                                run_paths["report_dir"],
                                config_path,
                                durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                memory_enabled=bool(payload.get("memory_enabled", True)),
                            )
                            rework_result = run_delivery_rework_loop(
                                orchestrator=orchestrator,
                                output_path=run_paths["output_dir"],
                                report_path=run_paths["report_dir"],
                                config_path=config_path,
                                initial_quality_result=quality_result,
                                run_kwargs=run_kwargs,
                                durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                memory_enabled=bool(payload.get("memory_enabled", True)),
                            )
                            if rework_result.get("quality_result"):
                                quality_result = rework_result["quality_result"]
                            if rework_result.get("rounds") and isinstance(result, dict):
                                result["delivery_rework"] = rework_result
                            _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result)
                        except Exception as exc:  # pragma: no cover - background safety boundary
                            (run_paths["output_dir"] / "run_error.json").write_text(
                                json.dumps({"error": str(exc), "symbol": symbol, "period": period}, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        finally:
                            _clear_active_run(session_id)

                    if async_report_run:
                        _enqueue_report(_run_report_background)
                        self._send_json({
                            "answer": "已启动后台研报生成；页面会继续轮询，完成后自动刷新报告、引用和质量结果。",
                            "mode": "report_generation_running",
                            "route_reason": "background report task",
                            "session_id": session_id,
                            "request_id": request_id,
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "result": {
                                "status": "running",
                                "symbol": symbol,
                                "period": period,
                                "execution_mode": execution_mode,
                            },
                            "parsed_task": parsed_task.to_dict(),
                            "_no_latest_until_complete": True,
                        })
                        return

                    try:
                        result = orchestrator.run(**run_kwargs)
                        quality_result = run_delivery_quality_pipeline(
                            run_paths["output_dir"],
                            run_paths["report_dir"],
                            config_path,
                            durable_memory_store=getattr(orchestrator, "durable_memory", None),
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                        )
                        rework_result = run_delivery_rework_loop(
                            orchestrator=orchestrator,
                            output_path=run_paths["output_dir"],
                            report_path=run_paths["report_dir"],
                            config_path=config_path,
                            initial_quality_result=quality_result,
                            run_kwargs=run_kwargs,
                            durable_memory_store=getattr(orchestrator, "durable_memory", None),
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                        )
                        if rework_result.get("quality_result"):
                            quality_result = rework_result["quality_result"]
                        if rework_result.get("rounds"):
                            result["delivery_rework"] = rework_result
                        _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result)
                        _clear_active_run(session_id)
                        report_links = build_report_links(run_paths["report_dir"])
                        latest = _latest_payload()
                        self._send_json({
                            "answer": "研报生成完成！可点击下方链接查看完整 HTML 研报。",
                            "mode": "report_generation_completed",
                            "route_reason": "confirmed report task" if confirmed_pending else "parsed report generation intent",
                            "session_id": session_id,
                            "request_id": request_id,
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "report_links": report_links,
                            "citations": _read_json(output_root / "citations.json", default=[]),
                            "result": {**result, **quality_result},
                            "parsed_task": parsed_task.to_dict(),
                            "latest": payload_for_mode(latest, mode),
                        })
                    except Exception as exc:  # pragma: no cover - defensive UI boundary
                        self._send_json({
                            "error": str(exc), "latest": _latest_payload(),
                            "request_id": request_id,
                        }, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    finally:
                        _clear_active_run(session_id)
                    return

            # [7] general_chat — fallthrough for chat and unrecognized intents
            response = chat_service.handle_chat(
                message=message,
                session_id=session_id,
                user_id=user_id,
                symbol=symbol,
                period=period,
                memory_enabled=bool(payload.get("memory_enabled", True)),
                allow_report_run=False,
                orchestrator=None,
                engines=engines,
                fast=bool(payload.get("fast", True)),
                execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                enable_remote_data=enable_remote_data,
                data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            )
            response["mode"] = "general_chat"
            response["request_id"] = request_id
            if parsed_task and (parsed_task.should_run or parsed_task.needs_confirmation):
                response["parsed_task"] = parsed_task.to_dict()
            self._send_json(response)
"""

if old_text == new_handle_chat:
    print("WARNING: old and new text are identical, skipping")
    exit(0)

source = source[:start_idx] + new_handle_chat + source[end_idx:]

with open("src/app/web_ui.py", "w", encoding="utf-8") as f:
    f.write(source)

print(f"_handle_chat replaced successfully (len old={len(old_text)}, len new={len(new_handle_chat)})")
