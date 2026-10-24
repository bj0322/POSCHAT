# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""'연결·도구' 창(커넥터·MCP·메모리·동기화·연구·자동화·진단)이 부르는 Bridge API.

main.Bridge가 이 클래스를 상속한다. 밑줄로 시작하지 않는 메서드는 모두 JS(window.pywebview.api)에 노출된다.
Bridge의 _config·_lock·_push·_mcp·_workspace·_open_url을 쓴다.
비밀 값은 돌려주지 않는다(있는지와 마스킹한 끝자리만).
"""
import re
import threading

import connectors
import mcp_client
import oauth
import secret_store
import storage


class WorkspaceApi:
    _login_flows = None   # 커넥터 id -> 진행 중인 로그인 {"flow", "cancel"}

    # ---- 기능 플래그 ----

    def get_features(self):
        return {name: {"label": label, "enabled": connectors.feature_enabled(self._config, name)}
                for name, (label, _) in connectors.FEATURES.items()}

    def set_feature(self, name, enabled):
        if name not in connectors.FEATURES:
            return {"ok": False, "error": "알 수 없는 기능입니다."}
        with self._lock:
            self._config.setdefault("features", {})[name] = bool(enabled)
            storage.save_config(self._config)
        return {"ok": True, "features": self.get_features()}

    # ---- 커넥터 ----

    def _connector_entry(self, cid):
        return self._config.setdefault("connectors", {}).setdefault(cid, {})

    def get_connectors(self):
        inprocess = mcp_client.INPROCESS_BUILTIN
        external, _ = mcp_client.load_external()
        running = {s["name"]: s for s in self._mcp.status(self._config, self._workspace())["servers"]}
        items = []
        for cid, c in connectors.CONNECTORS.items():
            e = connectors.entry(self._config, cid)
            st = connectors.status(self._config, cid, inprocess=inprocess, conflict=c.server in external)
            policy = e.get("policy") or {}
            server = running.get(c.server, {})
            items.append({
                "id": cid, "name": c.name, "group": c.group, "description": c.description, "auth": c.auth,
                "provider": c.provider, "device_flow": c.device_flow, "feature": c.feature,
                "feature_enabled": connectors.feature_enabled(self._config, c.feature),
                "enabled": bool(e.get("enabled")), "desktop_only": c.desktop_only, "setup": c.setup,
                "scopes": connectors.wanted_scopes(self._config, cid) if c.auth == "oauth" else list(c.scopes),
                "secrets": [{"name": f.name, "label": f.label, "placeholder": f.placeholder, "help": f.help,
                             "has": secret_store.has(connectors.secret_name(cid, f.name)),
                             "masked": secret_store.mask(secret_store.get(connectors.secret_name(cid, f.name)))[-5:]}
                            for f in c.secrets],
                "has_oauth_token": bool((oauth.load(cid) or {}).get("access_token")),
                "options": [{"name": f.name, "label": f.label, "placeholder": f.placeholder, "help": f.help,
                             "value": connectors.option(self._config, cid, f.name, "")} for f in c.options],
                "tools": [{"name": t, "kind": k, "policy": policy.get(t, "")}
                          for t, k in connectors.TOOL_KINDS.get(c.server, {}).items()],
                "server_state": server.get("state", "idle"), "server_error": server.get("error", ""),
                **st,
            })
        clients = {}
        for provider in oauth.PROVIDERS:
            client_id, client_secret = connectors.oauth_client(self._config, provider)
            clients[provider] = {"client_id": client_id, "has_secret": bool(client_secret)}
        return {"connectors": items, "features": self.get_features(), "secret_backend": secret_store.backend_name(),
                "oauth_clients": clients, "android": inprocess}

    def set_connector_enabled(self, cid, enabled):
        if cid not in connectors.CONNECTORS:
            return {"ok": False, "error": "알 수 없는 커넥터입니다."}
        c = connectors.CONNECTORS[cid]
        with self._lock:
            self._connector_entry(cid)["enabled"] = bool(enabled)
            if enabled:  # 커넥터를 켜면 그 기능(Phase)도 켠다
                self._config.setdefault("features", {})[c.feature] = True
                self._config["features"]["connectors"] = True
            storage.save_config(self._config)
        return self.get_connectors()

    def set_connector_secret(self, cid, field, value):
        c = connectors.CONNECTORS.get(cid)
        if c is None or field not in {f.name for f in c.secrets}:
            return {"ok": False, "error": "알 수 없는 입력 칸입니다."}
        secret_store.set(connectors.secret_name(cid, field), str(value or "").strip())
        connectors.record_health(cid, "", "")
        return self.get_connectors()

    def set_connector_option(self, cid, name, value):
        c = connectors.CONNECTORS.get(cid)
        if c is None or name not in {f.name for f in c.options}:
            return {"ok": False, "error": "알 수 없는 옵션입니다."}
        value = value.strip() if isinstance(value, str) else value
        if name == "api_url" and value and not str(value).startswith("https://"):
            return {"ok": False, "error": "주소는 https://로 시작해야 합니다."}
        with self._lock:
            options = self._connector_entry(cid).setdefault("options", {})
            if value in ("", None):
                options.pop(name, None)
            else:
                options[name] = value
            storage.save_config(self._config)
        return self.get_connectors()

    def set_connector_policy(self, cid, tool, rule):
        c = connectors.CONNECTORS.get(cid)
        if c is None or tool not in connectors.TOOL_KINDS.get(c.server, {}):
            return {"ok": False, "error": "알 수 없는 도구입니다."}
        if rule not in ("",) + connectors.POLICIES:
            return {"ok": False, "error": "정책은 allow·ask·deny 중 하나입니다."}
        with self._lock:
            policy = self._connector_entry(cid).setdefault("policy", {})
            if rule:
                policy[tool] = rule
            else:
                policy.pop(tool, None)
            storage.save_config(self._config)
        return self.get_connectors()

    def set_server_policy(self, server, mode):
        """외부 MCP 서버: mode "ask_all"이면 서버가 읽기 전용이라고 신고한 도구도 묻는다."""
        if mode not in ("", "ask_all"):
            return {"ok": False, "error": "알 수 없는 정책입니다."}
        with self._lock:
            policies = self._config.setdefault("mcp_policy", {})
            if mode:
                policies.setdefault(str(server), {})["mode"] = mode
            else:
                policies.get(str(server), {}).pop("mode", None)
            storage.save_config(self._config)
        return self.get_mcp()

    def set_oauth_client(self, provider, client_id, client_secret=None, clear=False):
        if provider not in oauth.PROVIDERS:
            return {"ok": False, "error": "알 수 없는 인증 제공자입니다."}
        with self._lock:
            clients = self._config.setdefault("oauth_clients", {})
            if clear:
                clients.pop(provider, None)
            else:
                clients.setdefault(provider, {})["client_id"] = str(client_id or "").strip()
            storage.save_config(self._config)
        if clear:
            secret_store.delete(f"oauth_client:{provider}")
        elif client_secret:
            secret_store.set(f"oauth_client:{provider}", str(client_secret).strip())
        return self.get_connectors()

    def connector_login(self, cid):
        """OAuth 로그인을 시작한다. 진행은 {"type": "connector"} 이벤트로 알린다."""
        c = connectors.CONNECTORS.get(cid)
        if c is None or c.auth not in ("oauth", "token"):
            return {"ok": False, "error": "로그인하는 커넥터가 아닙니다."}
        if c.auth == "token" and not c.device_flow:
            return {"ok": False, "error": "이 커넥터는 토큰을 입력해 연결합니다."}
        client_id, client_secret = connectors.oauth_client(self._config, c.provider)
        if not client_id:
            what = "Google OAuth 클라이언트 ID" if c.provider == "google" else "GitHub OAuth App의 Client ID"
            return {"ok": False, "error": f"먼저 {what}를 입력하세요."}
        if self._login_flows is None:
            self._login_flows = {}
        self.connector_cancel_login(cid)
        cancel = threading.Event()
        state = {"cancel": cancel, "flow": None}
        self._login_flows[cid] = state
        threading.Thread(target=self._login_work, args=(cid, c, client_id, client_secret, state), daemon=True).start()
        return {"ok": True}

    def _login_work(self, cid, c, client_id, client_secret, state):
        provider = oauth.PROVIDERS[c.provider]
        try:
            if c.provider == "github":
                device = oauth.device_start(provider, client_id, list(c.scopes))
                self._push({"type": "connector", "kind": "device_code", "id": cid, "user_code": device["user_code"],
                            "url": device["verification_uri"]})
                self._open_url(device["verification_uri"])
                token = oauth.device_poll(provider, client_id, device, cancelled=state["cancel"].is_set)
            else:
                flow = oauth.LoopbackFlow(provider, client_id, connectors.wanted_scopes(self._config, cid),
                                          client_secret=client_secret, opener=None)
                state["flow"] = flow
                url = flow.start()
                self._push({"type": "connector", "kind": "login_url", "id": cid, "url": url})
                self._open_url(url)
                token = flow.wait()
            oauth.save(cid, token)
            result = connectors.verify(self._config, cid)
            if result.get("account"):
                with self._lock:
                    self._connector_entry(cid)["account"] = result["account"]
                    storage.save_config(self._config)
            self._push({"type": "connector", "kind": "login_done", "id": cid, "status": result})
        except oauth.OAuthError as e:
            self._push({"type": "connector", "kind": "login_error", "id": cid, "error": str(e)})
        except Exception as e:  # 네트워크 라이브러리 오류 등
            self._push({"type": "connector", "kind": "login_error", "id": cid, "error": f"{type(e).__name__}: {e}"})
        finally:
            if (self._login_flows or {}).get(cid) is state:
                self._login_flows.pop(cid, None)

    def connector_cancel_login(self, cid):
        state = (self._login_flows or {}).pop(cid, None)
        if state:
            state["cancel"].set()
            if state["flow"]:
                state["flow"].cancel()
        return {"ok": True}

    def connector_logout(self, cid):
        """연결 해제: OAuth 토큰은 서버에서 폐기한 뒤 지우고, 입력한 토큰·키도 지운다."""
        c = connectors.CONNECTORS.get(cid)
        if c is None:
            return {"ok": False, "error": "알 수 없는 커넥터입니다."}
        token = oauth.load(cid)
        revoked = oauth.revoke(oauth.PROVIDERS[c.provider], token) if token and c.provider in oauth.PROVIDERS else False
        oauth.forget(cid)
        for f in c.secrets:
            secret_store.delete(connectors.secret_name(cid, f.name))
        with self._lock:
            e = self._connector_entry(cid)
            e.pop("account", None)
            e["enabled"] = False
            storage.save_config(self._config)
        connectors.record_health(cid, "", "", account="")
        note = "서버에서 토큰을 폐기하고 지웠습니다." if revoked else "이 기기에서 인증 정보를 지웠습니다."
        if c.auth == "token":
            note += " GitHub 설정(Settings → Developer settings)에서 토큰 자체도 지우세요."
        return {**self.get_connectors(), "message": note}

    def connector_verify(self, cid):
        if cid not in connectors.CONNECTORS:
            return {"ok": False, "error": "알 수 없는 커넥터입니다."}
        result = connectors.verify(self._config, cid)
        if result.get("account"):
            with self._lock:
                self._connector_entry(cid)["account"] = result["account"]
                storage.save_config(self._config)
        return {**self.get_connectors(), "verified": result}

    def connector_log(self, cid=None, limit=100):
        return connectors.read_audit(limit=max(1, min(500, int(limit or 100))), connector=cid or None)

    # ---- 연구 라이브러리 (Phase 2) ----

    def _research_call(self, fn, *args, **kwargs):
        from office_mcp import ToolFailure

        import research_library

        try:
            return {"ok": True, "result": fn(*args, **kwargs)}
        except (ToolFailure, research_library.LibraryError, ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}

    def research_state(self, query="", tag=""):
        import rag
        import research_library

        ws = self._workspace()
        collections = ["library"] + ([rag.workspace_collection(ws)] if ws else [])
        try:
            index = rag.status(collections)
        except Exception as e:  # 손상된 인덱스 파일 등
            index = {"fts": "?", "documents": [], "chunks": 0, "error": str(e)}
        vector = dict(self._config.get("vector") or {})
        return {
            "feature": connectors.feature_enabled(self._config, "research"),
            "enabled": connectors.is_enabled(self._config, "research"),
            "papers": research_library.search(query or "", tag or None, None, limit=500),
            "total": len(research_library.load()["papers"]),
            "tags": research_library.tags(),
            "index": {**index, "documents": index["documents"][:200]},
            "workspace": ws, "indexing": bool(getattr(self, "_indexing", False)),
            "vector": {**vector, "has_qdrant_key": secret_store.has("vector:qdrant_key"),
                       "has_embedding_key": secret_store.has("vector:embedding_key")},
            "zotero": connectors.status(self._config, "zotero")["state"],
        }

    def research_add(self, identifier, tags=None):
        import research_library
        import research_mcp

        identifier = str(identifier or "").strip()
        if not identifier:
            return {"ok": False, "error": "arXiv 번호·DOI·논문 주소를 입력하세요."}
        if identifier.lower().endswith(".pdf") and not identifier.lower().startswith("http"):
            return {"ok": False, "error": "PDF는 에이전트에게 'research.library_add로 이 PDF를 더해 줘'라고 요청하세요."}
        res = self._research_call(research_mcp.lookup, identifier)
        if not res["ok"]:
            return res
        meta = res["result"]
        if tags:
            meta["tags"] = tags
        return self._research_call(lambda: research_library.add(meta)[0])

    def research_update(self, pid, fields):
        import research_library

        fields = {k: v for k, v in (fields or {}).items() if k in ("tags", "collections", "notes", "title", "year", "venue")}
        return self._research_call(research_library.update, pid, **fields)

    def research_remove(self, pid):
        import research_library

        return self._research_call(research_library.remove, pid)

    def research_bibtex(self, ids=None, tag=None, save=False):
        import research_library

        papers = ([research_library.get(i) for i in ids] if ids else research_library.search("", tag or None, None, 100000))
        if not papers:
            return {"ok": False, "error": "내보낼 논문이 없습니다."}
        text = research_library.to_bibtex(papers)
        out = {"ok": True, "bibtex": text, "count": len(papers)}
        if save:
            path = research_library.research_dir() / "library.bib"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            out["path"] = str(path)
            self._open_url(str(path.parent))
        return out

    def research_index(self):
        """작업 폴더 문서를 백그라운드에서 인덱싱한다. 진행은 {"type": "hub", "kind": "index_*"} 이벤트."""
        ws = self._workspace()
        if not ws:
            return {"ok": False, "error": "먼저 작업 폴더를 선택하세요."}
        if getattr(self, "_indexing", False):
            return {"ok": False, "error": "이미 인덱싱하고 있습니다."}
        self._indexing = True
        threading.Thread(target=self._index_work, args=(ws,), daemon=True).start()
        return {"ok": True}

    def _index_work(self, ws):
        import time as _time

        import rag
        import vector_store

        last = [0.0]

        def progress(done, total, name):
            if _time.monotonic() - last[0] >= 0.3 or done == total:
                last[0] = _time.monotonic()
                self._push({"type": "hub", "kind": "index_progress", "done": done, "total": total, "name": name})

        try:
            vectors = vector_store.from_config(self._config)
            summary = rag.index_folder(ws, rag.workspace_collection(ws), on_progress=progress, vectors=vectors)
            self._push({"type": "hub", "kind": "index_done", "summary": summary})
        except Exception as e:
            self._push({"type": "hub", "kind": "index_error", "error": f"{type(e).__name__}: {e}"})
        finally:
            self._indexing = False

    def research_search(self, query, limit=8):
        import rag
        import vector_store

        ws = self._workspace()
        collections = ["library"] + ([rag.workspace_collection(ws)] if ws else [])
        try:
            results = rag.search(query, collections, limit=int(limit or 8), vectors=vector_store.from_config(self._config))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "results": [{**r, "cite": rag.cite(r, ws or None)} for r in results]}

    def research_remove_document(self, doc_id):
        import rag
        import vector_store

        rag.remove_document(str(doc_id), vector_store.from_config(self._config))
        return {"ok": True}

    def set_vector_config(self, settings):
        from urllib.parse import urlparse

        settings = settings or {}

        def ok_url(url):
            u = urlparse(url)
            local = u.hostname in ("127.0.0.1", "localhost", "::1")
            return bool(u.hostname) and (u.scheme == "https" or (u.scheme == "http" and local))

        cfg = {"enabled": bool(settings.get("enabled")),
               "qdrant_url": str(settings.get("qdrant_url") or "").strip(),
               "collection": str(settings.get("collection") or "poschat").strip() or "poschat",
               "embedding_url": str(settings.get("embedding_url") or "").strip(),
               "embedding_model": str(settings.get("embedding_model") or "").strip()}
        for key in ("qdrant_url", "embedding_url"):
            if cfg[key] and not ok_url(cfg[key]):
                return {"ok": False, "error": "주소는 https:// 이거나 이 PC(http://127.0.0.1)여야 합니다."}
        if cfg["enabled"] and not (cfg["qdrant_url"] and cfg["embedding_url"] and cfg["embedding_model"]):
            return {"ok": False, "error": "벡터 검색을 켜려면 Qdrant 주소, 임베딩 API 주소와 모델이 모두 필요합니다."}
        with self._lock:
            self._config["vector"] = cfg
            storage.save_config(self._config)
        for name in ("qdrant_key", "embedding_key"):
            if settings.get(name):
                secret_store.set(f"vector:{name}", str(settings[name]).strip())
            if settings.get(f"clear_{name}"):
                secret_store.delete(f"vector:{name}")
        return {"ok": True, **self.research_state()}

    def zotero_import_now(self, full=False):
        import research_mcp

        if not connectors.has_credential("zotero"):
            return {"ok": False, "error": "먼저 커넥터 탭에서 Zotero API 키를 넣으세요."}
        return self._research_call(research_mcp.zotero_import, None, bool(full))

    # ---- 통합 메모리·인계 (Phase 3) ----

    def _project_key(self):
        import ai_memory

        ws = self._workspace()
        if not ws:
            return ""
        try:
            workspace, project = ai_memory.resolve_scope(ws)
        except OSError:
            return ""
        return f"{workspace}/{project}"

    def memory_state(self, layer="", query=""):
        import handoff
        import memory_store

        project = self._project_key()
        try:
            stats = memory_store.stats()
            if query:
                hits = memory_store.search(query, layers=[layer] if layer else None, project=project or None, limit=50)
                items = [{**h, "id": h.get("id", ""), "kind": h.get("kind", "note")} for h in hits]
            else:
                items = memory_store.entries(layer=layer or None, limit=200)
            handoffs = handoff.list_handoffs(limit=30)
            error = ""
        except Exception as e:  # 손상된 DB 등: 화면은 열리게 한다
            stats, items, handoffs, error = {"layers": {}, "handoffs": {}, "fts": "?"}, [], [], f"{type(e).__name__}: {e}"
        return {
            "feature": connectors.feature_enabled(self._config, "memory_hub"),
            "enabled": connectors.is_enabled(self._config, "memory"),
            "project": project, "stats": stats, "items": items, "handoffs": handoffs, "error": error,
            "sync": self.sync_state(), "android": mcp_client.INPROCESS_BUILTIN,
        }

    def memory_add(self, text, layer="project", kind="note", title=""):
        import memory_store

        project = self._project_key() if layer in ("project", "research") else ""
        if layer in ("project", "research") and not project:
            return {"ok": False, "error": "프로젝트 기억은 작업 폴더를 고른 뒤 남깁니다."}
        try:
            entry, created = memory_store.write(text, layer=layer, project=project, kind=kind, title=title)
        except memory_store.MemoryStoreError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "entry": entry, "created": created}

    def memory_delete_entry(self, entry_id):
        import memory_store

        try:
            memory_store.delete(entry_id)
        except memory_store.MemoryStoreError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def handoff_set_status(self, task_id, status):
        import handoff

        try:
            if status == "completed":
                rec = handoff.complete(task_id, "사용자가 화면에서 완료로 표시")
            elif status == "cancelled":
                rec = handoff.cancel(task_id)
            elif status == "accepted":
                rec = handoff.accept("poschat-user", task_id=task_id)
            else:
                return {"ok": False, "error": "알 수 없는 상태입니다."}
        except handoff.HandoffError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "handoff": rec}

    def memory_summarize_thread(self, thread_id):
        """대화를 요약해 대화 메모리(conversation)에 남긴다. 모델을 한 번 부른다(크레딧 사용)."""
        key = self._api_key()
        thread = storage.load_thread(thread_id)
        if not key:
            return {"ok": False, "error": self._missing_key_error()}
        if not thread or not thread.get("messages"):
            return {"ok": False, "error": "요약할 대화가 없습니다."}
        threading.Thread(target=self._summarize_work, args=(thread, key), daemon=True).start()
        return {"ok": True}

    def _summarize_work(self, thread, key):
        import api
        import memory_store

        lines = [f"{'사용자' if m['role'] == 'user' else '어시스턴트'}: {m['content'][:1500]}"
                 for m in thread["messages"] if m.get("role") in ("user", "assistant")][-40:]
        prompt = ("다음은 대화 요약 작업입니다. 아래 대화에서 나중에 다시 찾아볼 가치가 있는 내용(결정, 알게 된 사실, 남은 일)을 "
                  "한국어로 5줄 이내의 불릿으로 요약하세요. 비밀번호·키 같은 민감한 정보는 쓰지 마세요.\n\n[대화]\n" + "\n".join(lines))
        try:
            settings = self._thread_api_settings(thread)
            text = api.ask(key, prompt, settings=settings)
            entry, _ = memory_store.write(text.strip(), layer="conversation", kind="summary",
                                          title=f"대화 '{thread.get('title', '')}' 요약", tags=[f"thread:{thread['id']}"])
            self._push({"type": "hub", "kind": "summary_done", "entry": entry})
        except Exception as e:
            self._push({"type": "hub", "kind": "summary_error", "error": f"{type(e).__name__}: {e}"})

    # ---- 동기화 ----

    def _sync_settings(self):
        import sync

        return {k: self._config.get(k) for k in sync.SETTINGS_KEYS}

    def _stamp_settings(self, before):
        """동기화하는 설정이 바뀌었으면 바뀐 시각을 남긴다(동기화의 최종 수정 우선 판단)."""
        import time as _time

        if before != self._sync_settings():
            self._config["settings_updated"] = _time.time()

    def _apply_synced_settings(self, values, stamp):
        with self._lock:
            if float(self._config.get("settings_updated") or 0) > float(stamp or 0):
                return  # 이 기기의 설정이 더 최근
            self._config.update(values)
            self._config["settings_updated"] = stamp
            storage.save_config(self._config)

    def sync_state(self):
        import sync

        ok, reason = sync.available()
        cfg = dict(self._config.get("sync") or {})
        return {"available": ok, "reason": reason, "enabled": bool(cfg.get("enabled")),
                "feature": connectors.feature_enabled(self._config, "sync"),
                "backend": cfg.get("backend", "folder"), "folder": cfg.get("folder", ""),
                "include": {k: (cfg.get("include") or {}).get(k, True) for k in sync.INCLUDE},
                "has_key": bool(secret_store.get("sync:key")), "device_name": cfg.get("device_name", ""),
                "last_sync": cfg.get("last_sync"), "last_error": cfg.get("last_error", ""),
                "last_report": cfg.get("last_report"), "running": bool(getattr(self, "_syncing", False)),
                "gsync": connectors.status(self._config, "gsync")["state"]}

    def sync_choose_folder(self):
        import webview

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory="")
        if not result:
            return {"ok": False}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"ok": True, "folder": str(path)}

    def sync_setup(self, settings):
        """동기화 켜기: 저장소·암호·대상을 정하고 키를 만든다. 다른 기기에서 이미 쓰는 저장소면 같은 암호여야 한다."""
        import platform

        import memory_store
        import sync

        settings = settings or {}
        ok, reason = sync.available()
        if not ok:
            return {"ok": False, "error": reason}
        backend_name = settings.get("backend") if settings.get("backend") in ("folder", "gdrive") else "folder"
        cfg = {"enabled": True, "backend": backend_name, "folder": str(settings.get("folder") or "").strip(),
               "include": {k: bool((settings.get("include") or {}).get(k, True)) for k in sync.INCLUDE},
               "device_name": str(settings.get("device_name") or platform.node() or "이 기기")[:60]}
        if backend_name == "folder":
            from pathlib import Path

            if not cfg["folder"] or not Path(cfg["folder"]).is_dir():
                return {"ok": False, "error": "동기화 폴더(OneDrive·Dropbox 등의 폴더)를 고르세요."}
        elif not connectors.has_credential("gsync"):
            return {"ok": False, "error": "먼저 커넥터 탭에서 'Google Drive 동기화 저장소'에 로그인하세요."}
        try:
            key = sync.setup(sync.backend_from_config({"sync": cfg}), settings.get("passphrase", ""))
        except sync.SyncError as e:
            return {"ok": False, "error": str(e)}
        sync.save_key(key)
        memory_store.device_id()
        with self._lock:
            self._config["sync"] = cfg
            self._config.setdefault("features", {})["sync"] = True
            storage.save_config(self._config)
        self._sync_schedule(0.5)
        return {"ok": True, "state": self.sync_state()}

    def sync_set_include(self, include):
        import sync

        with self._lock:
            cfg = self._config.setdefault("sync", {})
            cfg["include"] = {k: bool((include or {}).get(k, True)) for k in sync.INCLUDE}
            storage.save_config(self._config)
        return self.sync_state()

    def sync_now(self):
        if not (self._config.get("sync") or {}).get("enabled"):
            return {"ok": False, "error": "동기화가 꺼져 있습니다."}
        if getattr(self, "_syncing", False):
            return {"ok": False, "error": "이미 동기화하고 있습니다."}
        threading.Thread(target=self._sync_work, daemon=True).start()
        return {"ok": True}

    def _sync_work(self):
        import time as _time

        import memory_store
        import sync

        if getattr(self, "_syncing", False):
            return
        self._syncing = True
        self._push({"type": "hub", "kind": "sync_started"})
        try:
            report = sync.sync_once(dict(self._config), device=memory_store.device_id(),
                                    device_name=(self._config.get("sync") or {}).get("device_name", ""),
                                    on_settings=self._apply_synced_settings)
            with self._lock:
                cfg = self._config.setdefault("sync", {})
                cfg.update(last_sync=_time.time(), last_error="", last_report=report)
                storage.save_config(self._config)
            self._push({"type": "hub", "kind": "sync_done", "report": report})
        except Exception as e:
            message = str(e) if isinstance(e, sync.SyncError) else f"{type(e).__name__}: {e}"
            with self._lock:
                self._config.setdefault("sync", {})["last_error"] = message
                storage.save_config(self._config)
            self._push({"type": "hub", "kind": "sync_error", "error": message})
        finally:
            self._syncing = False

    def _sync_schedule(self, delay):
        """동기화를 켰을 때만: delay초 뒤 한 번(이미 예약돼 있으면 그대로). 이후 15분마다."""
        cfg = self._config.get("sync") or {}
        if not cfg.get("enabled") or not connectors.feature_enabled(self._config, "sync"):
            return
        timer = getattr(self, "_sync_timer", None)
        if timer is not None and timer.is_alive():
            return

        def run():
            self._sync_timer = None
            self._sync_work()
            self._sync_schedule(15 * 60)

        self._sync_timer = threading.Timer(delay, run)
        self._sync_timer.daemon = True
        self._sync_timer.start()

    def sync_disconnect(self):
        """이 기기의 동기화를 끈다(원격 데이터와 로컬 데이터는 남긴다)."""
        import sync

        sync.forget_key()
        with self._lock:
            self._config.setdefault("sync", {})["enabled"] = False
            storage.save_config(self._config)
        timer = getattr(self, "_sync_timer", None)
        if timer is not None:
            timer.cancel()
        return {"ok": True, "state": self.sync_state()}

    def sync_wipe_remote(self):
        """원격 동기화 데이터를 모두 지운다(다른 기기도 동기화가 멈춘다). 로컬 데이터는 남긴다."""
        import sync

        try:
            sync.wipe(sync.backend_from_config(self._config))
        except (sync.SyncError, OSError) as e:
            return {"ok": False, "error": str(e)}
        return self.sync_disconnect()

    # ---- 에이전트 자동화 (Phase 4) ----

    def automation_state(self):
        import json as _json
        import shutil as _shutil

        auto = self._config.get("automation") or {}
        py = dict(auto.get("python") or {})
        detected, error = "", ""
        if not mcp_client.INPROCESS_BUILTIN:
            import office_mcp
            import runner_mcp

            try:
                detected = runner_mcp.interpreter()
            except office_mcp.ToolFailure as e:
                error = str(e)
        log = []
        try:
            lines = (storage.APP_DIR / "logs" / "exec.jsonl").read_text(encoding="utf-8").splitlines()[-30:]
            log = [_json.loads(line) for line in reversed(lines) if line.strip()]
        except (FileNotFoundError, ValueError):
            pass
        return {
            "feature": connectors.feature_enabled(self._config, "automation"),
            "android": mcp_client.INPROCESS_BUILTIN,
            "python": {"enabled": connectors.is_enabled(self._config, "python"), "interpreter": py.get("interpreter", ""),
                       "detected": detected, "error": error, "isolation": py.get("isolation", "none"),
                       "docker_image": py.get("docker_image", "python:3.12-slim"), "timeout": py.get("timeout", 120),
                       "memory_mb": py.get("memory_mb", 2048), "docker": bool(_shutil.which("docker"))},
            "ssh": {"enabled": connectors.is_enabled(self._config, "ssh"), "hosts": (auto.get("ssh") or {}).get("hosts") or {},
                    "timeout": (auto.get("ssh") or {}).get("timeout", 120), "client": bool(_shutil.which("ssh"))},
            "log": log,
        }

    def set_python_settings(self, settings):
        from pathlib import Path

        settings = settings or {}
        interp = str(settings.get("interpreter") or "").strip()
        if interp and not Path(interp).is_file():
            return {"ok": False, "error": f"Python 실행 파일이 없습니다: {interp}"}
        try:
            timeout = max(5, min(3600, int(settings.get("timeout") or 120)))
            memory = max(128, min(65536, int(settings.get("memory_mb") or 2048)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "시간 제한과 메모리는 숫자로 입력하세요."}
        image = str(settings.get("docker_image") or "python:3.12-slim").strip()
        if not re.fullmatch(r"[A-Za-z0-9._/:@\-]{1,200}", image):
            return {"ok": False, "error": "Docker 이미지 이름이 잘못되었습니다."}
        with self._lock:
            auto = self._config.setdefault("automation", {})
            auto["python"] = {"interpreter": interp, "isolation": "docker" if settings.get("isolation") == "docker" else "none",
                              "docker_image": image, "timeout": timeout, "memory_mb": memory}
            storage.save_config(self._config)
        return {"ok": True, **self.automation_state()}

    def set_ssh_host(self, alias, spec):
        alias = str(alias or "").strip()
        spec = spec or {}
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", alias):
            return {"ok": False, "error": "별칭은 영문·숫자·-·_로 40자 이내입니다."}
        host, user = str(spec.get("host") or "").strip(), str(spec.get("user") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", host) or (user and not re.fullmatch(r"[A-Za-z0-9_.\-]+", user)):
            return {"ok": False, "error": "호스트·사용자 이름에 쓸 수 없는 글자가 있습니다."}
        try:
            port = int(spec.get("port") or 22)
        except (TypeError, ValueError):
            return {"ok": False, "error": "포트는 숫자입니다."}
        allowed = spec.get("allowed_commands") or []
        if isinstance(allowed, str):
            allowed = [a.strip() for a in allowed.split(",") if a.strip()]
        entry = {"host": host, "user": user, "port": port, "identity_file": str(spec.get("identity_file") or "").strip(),
                 "cwd": str(spec.get("cwd") or "").strip(), "allowed_commands": [str(a) for a in allowed][:50],
                 "allow_shell": bool(spec.get("allow_shell"))}
        with self._lock:
            ssh = self._config.setdefault("automation", {}).setdefault("ssh", {})
            ssh.setdefault("hosts", {})[alias] = entry
            storage.save_config(self._config)
        return {"ok": True, **self.automation_state()}

    def remove_ssh_host(self, alias):
        with self._lock:
            hosts = ((self._config.get("automation") or {}).get("ssh") or {}).get("hosts") or {}
            hosts.pop(str(alias), None)
            storage.save_config(self._config)
        return {"ok": True, **self.automation_state()}

    def python_check(self):
        import office_mcp
        import runner_mcp

        try:
            return {"ok": True, "info": runner_mcp.python_info()}
        except office_mcp.ToolFailure as e:
            return {"ok": False, "error": str(e)}

    # ---- 사용량·진단 (Phase 5) ----

    def feedback(self, thread_id, message_id, rating):
        """답변 평가(👍 1 / 👎 -1, 0이면 지우기). 대화에 저장하고 모델별 품질 비교에 쓴다."""
        import telemetry

        try:
            rating = max(-1, min(1, int(rating)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "평가는 1, -1, 0 중 하나입니다."}
        with self._lock:
            thread = storage.load_thread(thread_id)
            msg = next((m for m in (thread or {}).get("messages", []) if m.get("id") == message_id), None)
            if msg is None or msg.get("role") != "assistant":
                return {"ok": False, "error": "평가할 답변을 찾지 못했습니다."}
            previous = msg.get("feedback", 0)
            if rating:
                msg["feedback"] = rating
            else:
                msg.pop("feedback", None)
            storage.save_thread(thread, update_timestamp=False)
        if rating and rating != previous:
            telemetry.record("feedback", model=msg.get("model") or thread.get("model") or "?", rating=rating)
        return {"ok": True, "feedback": rating}

    def diagnostics_state(self, days=30):
        import evals
        import telemetry

        days = max(1, min(90, int(days or 30)))
        lf = dict((self._config.get("telemetry") or {}).get("langfuse") or {})
        return {
            "feature": connectors.feature_enabled(self._config, "observability"),
            "summary": telemetry.summary(days), "usage": storage.usage_summary(),
            "langfuse": {**lf, "has_public": secret_store.has("langfuse:public_key"),
                         "has_secret": secret_store.has("langfuse:secret_key")},
            "eval_sets": [{"name": e["name"], "description": e.get("description", ""), "cases": len(e["cases"])}
                          for e in evals.sets().values()],
            "eval_results": evals.recent(5), "evaluating": bool(getattr(self, "_evaluating", False)),
            "models": [{"id": m, "label": label} for m, label in self._models(self._mode())],
            "documented_credit_models": sorted(telemetry.DOCUMENTED_RATES),
        }

    def set_telemetry_settings(self, settings):
        settings = settings or {}
        host = str(settings.get("host") or "").strip().rstrip("/")
        if settings.get("enabled") and not host.startswith("https://"):
            return {"ok": False, "error": "Langfuse 주소는 https://로 시작해야 합니다(예: https://cloud.langfuse.com)."}
        with self._lock:
            tel = self._config.setdefault("telemetry", {})
            tel["langfuse"] = {"enabled": bool(settings.get("enabled")), "host": host,
                               "include_content": bool(settings.get("include_content"))}
            storage.save_config(self._config)
        for name in ("public_key", "secret_key"):
            if settings.get(name):
                secret_store.set(f"langfuse:{name}", str(settings[name]).strip())
        if settings.get("clear_keys"):
            secret_store.delete("langfuse:public_key")
            secret_store.delete("langfuse:secret_key")
        self._export_schedule(5)
        return {"ok": True, **self.diagnostics_state()}

    def telemetry_export_now(self):
        import telemetry

        sent = telemetry.export_pending()
        return {"ok": True, "sent": sent, "export": telemetry.summary(1)["export"]}

    def _export_schedule(self, delay):
        """Langfuse 내보내기를 켰을 때만 1분마다 모아 보낸다."""
        lf = (self._config.get("telemetry") or {}).get("langfuse") or {}
        timer = getattr(self, "_export_timer", None)
        if not lf.get("enabled") or (timer is not None and timer.is_alive()):
            return

        def run():
            import telemetry

            self._export_timer = None
            try:
                telemetry.export_pending()
            finally:
                self._export_schedule(60)

        self._export_timer = threading.Timer(delay, run)
        self._export_timer.daemon = True
        self._export_timer.start()

    def eval_run(self, set_name, models):
        """평가 세트를 고른 모델들에 돌린다(모델을 케이스 수 × 모델 수만큼 부른다). 진행은 hub 이벤트."""
        import evals

        key = self._api_key()
        if not key:
            return {"ok": False, "error": self._missing_key_error()}
        eval_set = evals.sets().get(str(set_name))
        allowed = self._model_ids(self._mode())
        models = [m for m in (models or []) if m in allowed][:6]
        if eval_set is None or not models:
            return {"ok": False, "error": "평가 세트와 모델(최대 6개)을 고르세요."}
        if getattr(self, "_evaluating", False):
            return {"ok": False, "error": "이미 평가하고 있습니다."}
        self._evaluating = True
        self._eval_cancel = threading.Event()
        threading.Thread(target=self._eval_work, args=(eval_set, models, key), daemon=True).start()
        return {"ok": True, "calls": len(models) * len(eval_set["cases"])}

    def _eval_work(self, eval_set, models, key):
        import api
        import evals

        def ask(model, prompt):
            settings = api.ApiSettings.from_config(self._config)
            settings.model, settings.stream = model, False
            return api.ask(key, prompt, settings=settings, timeout=120)

        try:
            report = evals.run(eval_set, models, ask, cancelled=self._eval_cancel.is_set,
                               on_progress=lambda done, total, model, case: self._push(
                                   {"type": "hub", "kind": "eval_progress", "done": done, "total": total, "model": model}))
            self._push({"type": "hub", "kind": "eval_done",
                        "summary": {m: {k: v for k, v in r.items() if k != "results"} for m, r in report["models"].items()}})
        except Exception as e:
            self._push({"type": "hub", "kind": "eval_error", "error": f"{type(e).__name__}: {e}"})
        finally:
            self._evaluating = False

    def eval_cancel(self):
        event = getattr(self, "_eval_cancel", None)
        if event:
            event.set()
        return {"ok": True}

    # ---- 플러그인 (1.12, Anthropic Knowledge Work Plugins) ----

    def plugins_state(self, refresh=False):
        """플러그인 목록과 설치 상태. 처음이거나 refresh면 GitHub에서 목록을 받는다."""
        import plugins

        try:
            catalog = plugins.catalog(refresh=bool(refresh))
        except plugins.PluginError as e:
            return {"ok": False, "error": str(e), "installed": plugins.installed(), "source": plugins.REPO_URL}
        items = [{k: v for k, v in p.items() if k != "readme"} for p in catalog.get("plugins", [])]
        return {"ok": True, "plugins": items, "installed": plugins.installed(), "updated": catalog.get("updated"),
                "source": plugins.REPO_URL}

    def plugin_detail(self, name):
        import plugins

        try:
            info = plugins.find(str(name))
        except plugins.PluginError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "plugin": info, "installed": plugins.installed().get(info["name"])}

    def _plugin_change(self, action, *args):
        import plugins

        try:
            action(*args)
        except plugins.PluginError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "installed": plugins.installed(), "skills": self._skills()}

    def plugin_install(self, name):
        import plugins

        return self._plugin_change(plugins.install, str(name))

    def plugin_remove(self, name):
        import plugins

        return self._plugin_change(plugins.remove, str(name))

    def plugin_set_enabled(self, name, enabled):
        import plugins

        return self._plugin_change(plugins.set_enabled, str(name), bool(enabled))
