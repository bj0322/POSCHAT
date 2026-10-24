# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptive AI 화면 API(1.17, main.Bridge의 믹스인): 'AI 실행 정책' 창, 로컬 AI 관리, 대화별 자동·로컬 모델, 통계.

- 설정은 config["adaptive"](adaptive_engine.DEFAULTS). 기본은 꺼짐이라 켜기 전에는 예전 동작과 같다.
- 로컬 실행기 연결·모델 목록·받기·지우기는 사용자가 이 창에서 누를 때만 한다. 받기 전에는 크기·출처·라이선스를 먼저 보인다.
- 웹페이지·PDF·MCP 결과는 이 API를 부를 수 없다(웹페이지 뷰에는 js_api가 없다). 그래서 외부 콘텐츠가 정책을 바꾸지 못한다.
"""
import threading
import time

import adaptive_engine
import adaptive_router
import api
import local_ai
import storage
import telemetry
from api import ApiError, ApiSettings


class AdaptiveApi:
    # ---- 상태 ----

    def _adaptive(self):
        return adaptive_engine.settings(self._config)

    def _local_runtime(self):
        rt = getattr(self, "_local_rt", None)
        if rt is None:
            rt = self._local_rt = adaptive_engine.LocalRuntime(lambda: self._config)
        return rt

    def _adaptive_public(self):
        s = self._adaptive()
        return {"enabled": s["enabled"], "policy": s["policy"], "show_badge": bool(s.get("show_badge", True)),
                "default_model": s["local"].get("default_model") or "", "local_supported": local_ai.SUPPORTED}

    def _cloud_guard(self, kind):
        """api.cloud_guard: Local Only 정책이면 Cloud 모델 호출을 막는다(라우터를 거치지 않는 호출까지)."""
        if adaptive_engine.local_only(self._config):
            telemetry.record("routing_failure", kind="local_only_blocked", policy="local_only", purpose=kind)
            raise ApiError("Local Only 정책이라 Cloud 모델을 부르지 않았습니다. 설정 → AI 실행 정책에서 정책을 바꾸거나 로컬 모델을 고르세요.")

    def adaptive_state(self, refresh=False):
        """AI 실행 정책 창: 설정, 로컬 실행기 상태, 설치된 모델(기능·크기·메모리 추정), 이 PC 자원, Cloud 예산."""
        rt = self._local_runtime()
        if refresh:
            rt.forget()
        s = self._adaptive()
        health = rt.health() if local_ai.SUPPORTED else {"ok": False, "error": "이 기기(안드로이드)에서는 로컬 AI를 쓸 수 없습니다."}
        models = rt.models() if health.get("ok") else []
        res = rt.resources() if local_ai.SUPPORTED else {}
        budget = local_ai.memory_budget(res) if res else None
        num_ctx = int(s["local"].get("num_ctx") or 8192)
        rows = []
        for m in models:
            need = local_ai.estimate_memory(m.get("size"), num_ctx)
            rows.append({**m, "memory_est": need, "memory_ok": need is None or budget is None or need <= budget,
                         "speed": (s["local"].get("speed") or {}).get(m["id"])})
        cloud_models = [{"id": mid, "label": label} for mid, label in self._models(self._mode())]
        return {"ok": True, "settings": s, "supported": local_ai.SUPPORTED, "health": health, "models": rows,
                "resources": res, "memory_budget": budget, "cloud_models": cloud_models,
                "cloud_model": self._adaptive_cloud_model(), "light_model": self._adaptive_light_model(),
                "light_suggestions": [m for m in ("claude-haiku-5-5", "gpt-5-mini-gs-2025-08-07", "gemini-3.8-flash",
                                                  "gpt-4.1-mini-gs-2025-04-14") if m in self._model_ids(self._mode())],
                "has_cloud_key": bool(self._api_key()),
                "budget": adaptive_engine.budget_state(self._config), "policies": adaptive_router.POLICY_LABELS,
                "stats": adaptive_router.load_stats(), "download": getattr(self, "_ai_download", None)}

    def adaptive_save(self, values):
        """정책 창의 저장. 알 수 없는 값은 무시하고, 주소는 정책(local_ai.check_endpoint)을 통과해야 저장한다."""
        values = values if isinstance(values, dict) else {}
        s = self._adaptive()
        local = dict(s["local"])
        if "endpoint" in values or "allow_remote" in values:
            allow = bool(values.get("allow_remote", local.get("allow_remote")))
            try:
                endpoint, _ = local_ai.check_endpoint(values.get("endpoint", local.get("endpoint")), allow, resolve=False)
            except local_ai.LocalAIError as e:
                return {"ok": False, "error": str(e)}
            local.update(endpoint=endpoint, allow_remote=allow)
        if "default_model" in values:
            model = str(values.get("default_model") or "").strip()
            if model and not local_ai.valid_model_name(model):
                return {"ok": False, "error": "로컬 모델 이름이 올바르지 않습니다."}
            local["default_model"] = model
        if "num_ctx" in values:
            try:
                local["num_ctx"] = max(2048, min(262144, int(values["num_ctx"])))
            except (TypeError, ValueError):
                pass
        s["local"] = local
        if "enabled" in values:
            s["enabled"] = bool(values["enabled"])
        if values.get("policy") in adaptive_router.POLICIES:
            s["policy"] = values["policy"]
        if "light_model" in values:  # 3단계의 경량 Cloud 모델: 지금 API 방식에서 고를 수 있는 모델만, 비우면 쓰지 않음
            model = str(values.get("light_model") or "")
            s["light_model"] = model if model in self._model_ids(self._mode()) else ""
        if "consult_max" in values:
            try:
                s["consult_max"] = max(0, min(2, int(values["consult_max"])))
            except (TypeError, ValueError):
                pass
        for key in ("escalation", "show_badge", "manual_fallback", "consult"):
            if key in values:
                s[key] = bool(values[key])
        for key, lo, hi in (("max_escalations", 0, adaptive_engine.MAX_ESCALATIONS), ("local_retries", 0, 1)):
            if key in values:
                try:
                    s[key] = max(lo, min(hi, int(values[key])))
                except (TypeError, ValueError):
                    pass
        if "cloud_model" in values:
            model = str(values.get("cloud_model") or "")
            s["cloud_model"] = model if model in self._model_ids(self._mode()) else ""
        if isinstance(values.get("budget"), dict):
            b = dict(s["budget"])
            for key in ("weekly_calls", "weekly_credits"):
                try:
                    b[key] = max(0, float(values["budget"].get(key) or 0)) if key == "weekly_credits" else max(0, int(values["budget"].get(key) or 0))
                except (TypeError, ValueError):
                    pass
            s["budget"] = b
        if "max_cost_per_request" in values:
            try:
                s["max_cost_per_request"] = max(0.0, float(values["max_cost_per_request"] or 0))
            except (TypeError, ValueError):
                pass
        if values.get("latency") in ("normal", "fast"):
            s["latency"] = values["latency"]
        if isinstance(values.get("privacy"), dict):
            p = dict(s["privacy"])
            for key in ("sensitive_local_only", "attachments_to_cloud"):
                if key in values["privacy"]:
                    p[key] = bool(values["privacy"][key])
            s["privacy"] = p
        if values.get("local_only_tools") in ("allow", "block"):
            s["local_only_tools"] = values["local_only_tools"]
        with self._lock:
            self._config["adaptive"] = s
            storage.save_config(self._config)
        self._local_runtime().forget()
        return {**self.adaptive_state(), "app": self.get_state()}

    def _adaptive_light_model(self):
        s = self._adaptive()
        light = s.get("light_model") or ""
        return light if light in self._model_ids(self._mode()) and light != self._adaptive_cloud_model() else ""

    def _adaptive_cloud_model(self):
        s = self._adaptive()
        return s["cloud_model"] if s["cloud_model"] in self._model_ids(self._mode()) else self._default_model()

    # ---- 로컬 AI 관리 ----

    def adaptive_test_connection(self, endpoint=None, allow_remote=None):
        """연결 시험(저장하지 않는다). 주소를 주면 그 주소로, 아니면 저장된 주소로."""
        if not local_ai.SUPPORTED:
            return {"ok": False, "error": "이 기기(안드로이드)에서는 로컬 AI를 쓸 수 없습니다."}
        local = self._adaptive()["local"]
        try:
            p = local_ai.OllamaProvider(endpoint if endpoint is not None else local.get("endpoint"),
                                        bool(local.get("allow_remote") if allow_remote is None else allow_remote))
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        h = p.health_check()
        if not h["ok"]:
            return {"ok": False, "error": h["error"], "health": h}
        try:
            models = p.list_models()
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e), "health": h}
        return {"ok": True, "health": h, "models": models}

    def adaptive_model_info(self, model):
        try:
            caps = self._local_runtime().capabilities(str(model))
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "model": model, "capabilities": caps}

    def adaptive_measure(self, model):
        """속도 측정(짧은 질문 하나, 로컬에서만 돈다). 결과는 설정에 남겨 라우터가 '빠른 응답 우선'에 쓴다."""
        try:
            m = self._local_runtime().provider().measure(str(model))
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        with self._lock:
            s = self._adaptive()
            s["local"].setdefault("speed", {})[str(model)] = {**m, "at": time.time()}
            self._config["adaptive"] = s
            storage.save_config(self._config)
        return {"ok": True, "speed": m}

    def adaptive_test_chat(self, model, text):
        """모델별 간단한 시험 대화(로컬에서만, 대화 기록에 남기지 않는다)."""
        text = str(text or "").strip()[:2000]
        if not text:
            return {"ok": False, "error": "보낼 글을 쓰세요."}
        try:
            res = self._local_runtime().provider().stream(local_ai.LocalRequest(model=str(model), prompt=text, timeout=180,
                                                                                 max_tokens=512), None, None)
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "text": res.text, "ms": res.ms, "tokens_per_s": res.tokens_per_s, "output_tokens": res.output_tokens}

    def adaptive_pull_preview(self, model):
        """받기 전 확인: 크기·출처·라이선스·남은 디스크(사용자가 '확인'을 눌렀을 때만 공개 저장소에 묻는다)."""
        if not local_ai.SUPPORTED:
            return {"ok": False, "error": "이 기기에서는 로컬 AI를 쓸 수 없습니다."}
        try:
            info = local_ai.pull_preview(str(model).strip())
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        free = local_ai.disk_free()
        return {"ok": True, **info, "disk_free": free, "disk_ok": free is None or not info["size"] or free > info["size"] * 1.1}

    def adaptive_pull(self, model):
        """모델 받기(백그라운드). 진행은 {"type": "adaptive", "kind": "pull"} 이벤트. 한 번에 하나만."""
        model = str(model or "").strip()
        if not local_ai.valid_model_name(model):
            return {"ok": False, "error": "모델 이름이 올바르지 않습니다(예: qwen2.5:7b)."}
        if getattr(self, "_ai_download", None):
            return {"ok": False, "error": "다른 모델을 받고 있습니다."}
        self._ai_download = {"model": model, "done": 0, "total": 0, "status": "시작"}
        self._ai_pull_cancel = threading.Event()
        threading.Thread(target=self._adaptive_pull_work, args=(model,), daemon=True).start()
        return {"ok": True}

    def _adaptive_pull_work(self, model):
        last = [0.0]

        def progress(done, total, status):
            self._ai_download = {"model": model, "done": done, "total": total, "status": status}
            if time.monotonic() - last[0] > 0.3:
                last[0] = time.monotonic()
                self._push({"type": "adaptive", "kind": "pull", **self._ai_download})

        try:
            self._local_runtime().provider().pull(model, progress, self._ai_pull_cancel.is_set)
            self._local_runtime().forget()
            self._push({"type": "adaptive", "kind": "pull_done", "model": model})
        except local_ai.LocalAIError as e:
            self._push({"type": "adaptive", "kind": "pull_error", "model": model, "error": str(e), "error_kind": e.kind})
        finally:
            self._ai_download = None

    def adaptive_pull_cancel(self):
        ev = getattr(self, "_ai_pull_cancel", None)
        if ev:
            ev.set()
        return {"ok": True}

    def adaptive_delete_model(self, model):
        try:
            self._local_runtime().provider().delete(str(model))
        except local_ai.LocalAIError as e:
            return {"ok": False, "error": str(e)}
        self._local_runtime().forget()
        return {"ok": True}

    def adaptive_stats(self, days=30):
        days = max(1, min(90, int(days or 30)))
        return {"ok": True, "summary": adaptive_engine.summary(days, config=self._config),
                "budget": adaptive_engine.budget_state(self._config)}

    # ---- 대화 실행에서 쓰는 도우미 ----

    def _thread_routed(self, model):
        """대화의 모델이 자동·로컬이고 자동 선택이 켜져 있는지."""
        return adaptive_engine.active(self._config) and (model == "auto" or bool(adaptive_engine.local_model_of(model)))

    def _routed_model_ok(self, model):
        model = str(model or "")
        if not adaptive_engine.active(self._config):
            return False
        return model == "auto" or (model.startswith("local:") and local_ai.valid_model_name(model[6:]))

    def _make_engine(self, thread, api_key, cancelled, on_event=None, area=""):
        """대화 하나의 실행에 쓸 엔진. 자동·로컬 모델이 아니면 None(예전 경로)."""
        model = (thread or {}).get("model")
        if not self._thread_routed(model):
            return None
        settings = self._thread_api_settings(thread)
        cloud_model = self._adaptive_cloud_model()

        def cloud_ask(prompt, chosen, on_delta, images):
            import agent as agent_module  # 시험에서 agent.ask를 바꿔 끼울 수 있게 부를 때 찾는다

            s = ApiSettings(**{**settings.__dict__, "model": chosen or cloud_model})
            return agent_module.ask(api_key, prompt, settings=s, on_delta=on_delta, cancelled=cancelled, images=images,
                                    **({"timeout": 600} if area == "po_note" else {}))

        return adaptive_engine.AdaptiveEngine(self._config, self._local_runtime(), cloud_ask, cloud_model,
                                              cloud_available=bool(api_key), mode=model, on_event=on_event,
                                              cancelled=cancelled, area_hint=area, light_model=self._adaptive_light_model(),
                                              frontier_session=(thread or {}).get("frontier_session"))

    def _save_frontier_session(self, thread_id, engine):
        """이 대화의 프런티어 상담 기록(질문·답 앞부분, 최근 6개)을 대화에 남긴다. 다음 요청의 상담에 이어서 붙인다."""
        if engine is None or not engine.consults:
            return
        with self._lock:
            thread = storage.load_thread(thread_id)
            if thread is not None:
                thread["frontier_session"] = engine.frontier_session[-6:]
                storage.save_thread(thread, update_timestamp=False)

    def _routed_ask(self, thread_model, api_key, purpose, area="", cancelled=None):
        """PO노트·대화 요약처럼 Agent를 거치지 않는 호출: (ask(prompt, on_delta) 함수, 엔진) 또는 (None, None)."""
        engine = self._make_engine({"model": thread_model}, api_key, cancelled or (lambda: False), area=area)
        if engine is None:
            return None, None

        def ask(prompt, on_delta=None):
            try:
                return engine.ask(prompt, purpose=purpose, on_delta=on_delta)
            except adaptive_engine.AdaptiveError as e:
                raise ApiError(str(e)) from e
        return ask, engine

    @staticmethod
    def _api_needed(config, model):
        """이 모델로 보내려면 Cloud 키가 있어야 하는지(로컬 모델·Local Only 정책은 키 없이도 된다)."""
        if not adaptive_engine.active(config):
            return True
        if adaptive_engine.local_model_of(model):
            return False
        if model == "auto":
            return not adaptive_engine.local_only(config) and not adaptive_engine.settings(config)["local"].get("default_model")
        return True


def describe_model(model):
    """대화·노트에 남길 모델 이름."""
    if model == "auto":
        return "자동 선택"
    local = adaptive_engine.local_model_of(model)
    return f"로컬 {local}" if local else api.model_label(model)
