"""선택 기능: 벡터 검색(Qdrant REST API + OpenAI 호환 임베딩 API).

설정(연결·도구 → 연구 라이브러리 → 벡터 검색)에 Qdrant 주소와 임베딩 API 주소·모델을 넣었을 때만 쓴다.
    config["vector"] = {"enabled": true, "qdrant_url": "http://127.0.0.1:6333", "collection": "poschat",
                        "embedding_url": "https://.../v1/embeddings", "embedding_model": "..."}
    비밀: secret_store "vector:qdrant_key"(선택), "vector:embedding_key"(없으면 임베딩 요청에 키를 넣지 않음)

POSTECH GenAI 게이트웨이가 임베딩 API를 제공한다고 가정하지 않는다. 설정이 없거나 연결에 실패하면 rag·memory_store는
키워드 검색(FTS5)만으로 동작한다. 점 ID는 (doc_id, 청크 순서)로 만든 UUID라 다시 인덱싱해도 같은 점을 덮어쓴다.
"""
import uuid

import secret_store
import storage

NAMESPACE = uuid.UUID("8f6f2f1e-3c2a-4c55-9b9d-6f1f4b0b7a10")
BATCH = 32


class VectorError(Exception):
    pass


def _http(method, url, **kwargs):
    from office_mcp import ToolFailure, http

    try:
        r = http(method, url, timeout=60, **kwargs)
    except ToolFailure as e:
        raise VectorError(str(e))
    if r.status_code >= 300:
        raise VectorError(f"{url.split('?')[0]} 요청 실패(HTTP {r.status_code}): {r.text[:200]}")
    return r.json() if r.content else {}


class Embedder:
    def __init__(self, url, model, api_key=""):
        self.url, self.model, self.api_key = url, model, api_key

    def embed(self, texts):
        headers = {"Authorization": f"Bearer {self.api_key}", "x-api-key": self.api_key} if self.api_key else {}
        out = []
        for i in range(0, len(texts), BATCH):
            data = _http("POST", self.url, json={"model": self.model, "input": texts[i:i + BATCH]}, headers=headers)
            items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
            if len(items) != len(texts[i:i + BATCH]):
                raise VectorError("임베딩 API가 요청한 개수만큼 벡터를 돌려주지 않았습니다.")
            out += [item["embedding"] for item in items]
        return out


class Qdrant:
    def __init__(self, url, collection="poschat", api_key=""):
        self.url, self.collection, self.api_key = url.rstrip("/"), collection, api_key
        self._ready = False

    def _call(self, method, path, body=None):
        headers = {"api-key": self.api_key} if self.api_key else {}
        return _http(method, f"{self.url}/collections/{self.collection}{path}", json=body, headers=headers)

    def ensure(self, dim):
        if self._ready:
            return
        try:
            self._call("GET", "")
        except VectorError:
            self._call("PUT", "", {"vectors": {"size": dim, "distance": "Cosine"}})
        for field in ("collection", "doc_id", "layer"):
            try:
                self._call("PUT", "/index", {"field_name": field, "field_schema": "keyword"})
            except VectorError:
                pass  # 이미 있음
        self._ready = True

    def upsert(self, points):
        if points:
            self.ensure(len(points[0]["vector"]))
            self._call("PUT", "/points?wait=true", {"points": points})

    def delete(self, key, value):
        try:
            self._call("POST", "/points/delete?wait=true", {"filter": {"must": [{"key": key, "match": {"value": value}}]}})
        except VectorError:
            pass  # 컬렉션이 아직 없다

    def search(self, vector, key, values, limit):
        data = self._call("POST", "/points/search", {
            "vector": vector, "limit": limit, "with_payload": True,
            "filter": {"must": [{"key": key, "match": {"any": list(values)}}]}})
        return data.get("result") or []


class VectorIndex:
    """rag가 쓰는 연결: 청크를 벡터로 넣고, 질문으로 찾는다."""

    def __init__(self, embedder, store):
        self.embedder, self.store = embedder, store

    def replace_document(self, doc_id, rows):
        """rows: [(chunk_id, doc_id, collection, text)]"""
        self.store.delete("doc_id", doc_id)
        if not rows:
            return
        vectors = self.embedder.embed([text for _, _, _, text in rows])
        points = [{"id": str(uuid.uuid5(NAMESPACE, f"{doc_id}:{i}")), "vector": vec,
                   "payload": {"chunk_id": cid, "doc_id": did, "collection": coll}}
                  for i, ((cid, did, coll, _), vec) in enumerate(zip(rows, vectors))]
        self.store.upsert(points)

    def delete_document(self, doc_id):
        self.store.delete("doc_id", doc_id)

    def search(self, query, collections, limit):
        vector = self.embedder.embed([query])[0]
        hits = self.store.search(vector, "collection", collections, limit)
        return [{"chunk_id": h["payload"]["chunk_id"], "score": h.get("score", 0)} for h in hits
                if (h.get("payload") or {}).get("chunk_id") is not None]


def from_config(config=None):
    """설정이 갖춰져 있으면 VectorIndex, 아니면 None."""
    config = config if config is not None else storage.load_config()
    v = config.get("vector") or {}
    if not v.get("enabled") or not v.get("qdrant_url") or not v.get("embedding_url") or not v.get("embedding_model"):
        return None
    embedder = Embedder(v["embedding_url"], v["embedding_model"], secret_store.get("vector:embedding_key"))
    store = Qdrant(v["qdrant_url"], v.get("collection") or "poschat", secret_store.get("vector:qdrant_key"))
    return VectorIndex(embedder, store)
