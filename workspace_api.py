"""'연결·도구' 창(커넥터·MCP·메모리·동기화·연구·자동화·진단)이 부르는 Bridge API.

main.Bridge가 이 클래스를 상속한다. 밑줄로 시작하지 않는 메서드는 모두 JS(window.pywebview.api)에 노출된다.
Bridge의 _config·_lock·_push·_mcp·_workspace·_open_url을 쓴다.
비밀 값은 돌려주지 않는다(있는지와 마스킹한 끝자리만).
"""
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
