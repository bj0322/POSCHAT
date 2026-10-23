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
