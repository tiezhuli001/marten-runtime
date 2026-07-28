from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import math
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from marten_runtime.interfaces.http.knowledge_routes import MAX_UPLOAD_BYTES, operator_authorized
from marten_runtime.knowledge.config import KnowledgeSearchConfig


_COOKIE_NAME = "marten_knowledge_operator"
_BAZI_THEORY_DRAFT_NAMESPACE = "bazi-theory-sandbox"
_BAZI_THEORY_NAMESPACE = "bazi-theory"


@dataclass(frozen=True)
class _ConsoleSession:
    expires_at: int
    csrf_token: str


class _ConsoleSessionCodec:
    def __init__(self, operator_token: str, *, ttl_seconds: int = 30 * 60) -> None:
        self.key = hashlib.sha256(f"knowledge-console\n{operator_token}".encode("utf-8")).digest()
        self.ttl_seconds = max(60, int(ttl_seconds))

    def create(self) -> tuple[str, _ConsoleSession]:
        session = _ConsoleSession(
            expires_at=int(time.time()) + self.ttl_seconds,
            csrf_token=secrets.token_urlsafe(24),
        )
        payload = _encode_json({"exp": session.expires_at, "csrf": session.csrf_token})
        signature = _encode_bytes(hmac.new(self.key, payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}", session

    def read(self, value: str | None) -> _ConsoleSession | None:
        payload, separator, signature = str(value or "").partition(".")
        if not separator or not payload or not signature:
            return None
        expected = _encode_bytes(hmac.new(self.key, payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            decoded = json.loads(_decode_bytes(payload).decode("utf-8"))
            session = _ConsoleSession(
                expires_at=int(decoded["exp"]),
                csrf_token=str(decoded["csrf"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if session.expires_at <= int(time.time()) or not session.csrf_token:
            return None
        return session


def build_knowledge_console_router(
    runtime,  # noqa: ANN001
    *,
    operator_token: str,
    session_ttl_seconds: int = 30 * 60,
) -> APIRouter:
    router = APIRouter()
    codec = _ConsoleSessionCodec(operator_token, ttl_seconds=session_ttl_seconds)

    def session(request: Request) -> _ConsoleSession | None:
        return codec.read(request.cookies.get(_COOKIE_NAME))

    def login_redirect() -> RedirectResponse:
        return RedirectResponse("/knowledge/console/login", status_code=303)

    def valid_csrf(current: _ConsoleSession, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied, current.csrf_token)

    async def api(
        request: Request,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> tuple[int, dict[str, object]]:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://knowledge-console.local") as client:
            response = await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {operator_token}"},
                data=data,
                files=files,
            )
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"ok": False, "error": {"code": "KNOWLEDGE_CONSOLE_UPSTREAM_INVALID", "message": response.text}}
        return response.status_code, dict(payload)

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):  # noqa: ANN201
        if session(request) is not None:
            return RedirectResponse("/knowledge/console", status_code=303)
        return HTMLResponse(_login_page())

    @router.post("/login")
    def login(request: Request, token: Annotated[str, Form()] = ""):  # noqa: ANN201
        if not operator_authorized(f"Bearer {token}", operator_token):
            return HTMLResponse(_login_page(error="Operator token 无效"), status_code=401)
        cookie, _ = codec.create()
        response = RedirectResponse("/knowledge/console", status_code=303)
        response.set_cookie(
            _COOKIE_NAME,
            cookie,
            max_age=codec.ttl_seconds,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/knowledge/console",
        )
        return response

    @router.post("/logout")
    def logout(
        request: Request,
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        response = RedirectResponse("/knowledge/console/login", status_code=303)
        response.delete_cookie(_COOKIE_NAME, path="/knowledge/console")
        return response

    @router.get("", response_class=HTMLResponse)
    async def home(request: Request, namespace: str = _BAZI_THEORY_DRAFT_NAMESPACE):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        namespace = _namespace(namespace)
        namespace_status, namespaces = await api(request, "GET", "/knowledge/namespaces")
        sources_status, sources = await api(
            request,
            "GET",
            f"/knowledge/namespaces/{quote(namespace)}/sources?page=1&page_size=100",
        )
        jobs_status, jobs = await api(
            request,
            "GET",
            f"/knowledge/namespaces/{quote(namespace)}/jobs?page=1&page_size=50",
        )
        stats_status, stats = await api(
            request,
            "GET",
            f"/knowledge/namespaces/{quote(namespace)}/stats",
        )
        for status_code, payload in (
            (namespace_status, namespaces),
            (sources_status, sources),
            (jobs_status, jobs),
            (stats_status, stats),
        ):
            if status_code >= 400:
                return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(
            _home_page(
                namespace=namespace,
                namespaces=list(namespaces.get("items") or []),
                sources=list(sources.get("items") or []),
                jobs=list(jobs.get("items") or []),
                stats=stats,
                csrf_token=current.csrf_token,
            )
        )

    @router.get("/namespaces/{namespace}/sources/{source_id}", response_class=HTMLResponse)
    async def source_detail(request: Request, namespace: str, source_id: str):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        namespace = _namespace(namespace)
        sources_status, sources = await api(
            request,
            "GET",
            f"/knowledge/namespaces/{quote(namespace)}/sources?page=1&page_size=100",
        )
        chunks_status, chunks = await api(
            request,
            "GET",
            f"/knowledge/namespaces/{quote(namespace)}/sources/{quote(source_id)}/chunks?page=1&page_size=100",
        )
        if sources_status >= 400:
            return HTMLResponse(_api_error_page(sources), status_code=sources_status)
        if chunks_status >= 400:
            return HTMLResponse(_api_error_page(chunks), status_code=chunks_status)
        source = next(
            (item for item in list(sources.get("items") or []) if str(item.get("source_id") or "") == source_id),
            None,
        )
        if source is None:
            return HTMLResponse(_error_page("KNOWLEDGE_SOURCE_NOT_FOUND", "source was not found"), status_code=404)
        return HTMLResponse(
            _source_page(
                namespace=namespace,
                source=dict(source),
                chunks=list(chunks.get("items") or []),
                csrf_token=current.csrf_token,
            )
        )

    @router.post("/namespaces/{namespace}/previews", response_class=HTMLResponse)
    async def create_preview(
        request: Request,
        namespace: str,
        file: Annotated[UploadFile, File()],
        csrf_token: Annotated[str, Form()] = "",
        title: Annotated[str, Form()] = "",
        source_url: Annotated[str, Form()] = "",
        evidence_kind: Annotated[str, Form()] = "modern_commentary",
        target_chars: Annotated[str, Form()] = "",
        overlap_chars: Annotated[str, Form()] = "",
        max_chars: Annotated[str, Form()] = "",
        embedding_profile_id: Annotated[str, Form()] = "default",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            await file.close()
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            await file.close()
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        await file.close()
        if len(content) > MAX_UPLOAD_BYTES:
            return HTMLResponse(_error_page("KNOWLEDGE_UPLOAD_TOO_LARGE", "upload exceeds 10 MiB"), status_code=413)
        original_filename = Path(str(file.filename or "source.md")).name
        resolved_title = str(title or "").strip() or Path(original_filename).stem
        resolved_source_url = str(source_url or "").strip()
        form = {
            "title": resolved_title,
            "license": "not-recorded",
            "provenance": resolved_source_url or f"console-upload:{original_filename}",
            "calculation_scope": "theory_interpretation",
            "review_status": "draft" if _namespace(namespace) == _BAZI_THEORY_DRAFT_NAMESPACE else "reviewed",
            "uri": resolved_source_url,
            "corpus_type": "theory",
            "content_type": "theory_document",
            "evidence_kind": evidence_kind,
            "work": resolved_title,
            "source_url": resolved_source_url,
            "verification_status": "operator-uploaded",
            "target_chars": target_chars,
            "overlap_chars": overlap_chars,
            "max_chars": max_chars,
            "embedding_profile_id": embedding_profile_id,
        }
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/previews",
            data=form,
            files={"file": (str(file.filename or "source.md"), content, str(file.content_type or "application/octet-stream"))},
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(
            _preview_page(
                namespace=_namespace(namespace),
                preview=payload,
                csrf_token=current.csrf_token,
            ),
            status_code=201,
        )

    @router.post("/namespaces/{namespace}/previews/{preview_id}/publish", response_class=HTMLResponse)
    async def publish_preview(
        request: Request,
        namespace: str,
        preview_id: str,
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/previews/{quote(preview_id)}/publish",
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_published_page(_namespace(namespace), payload), status_code=202)

    @router.post("/namespaces/{namespace}/search", response_class=HTMLResponse)
    def search(
        request: Request,
        namespace: str,
        query: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
        top_k: Annotated[str, Form()] = "",
        candidate_pool: Annotated[str, Form()] = "",
        fts_weight: Annotated[str, Form()] = "",
        vector_weight: Annotated[str, Form()] = "",
        metadata_weight: Annotated[str, Form()] = "",
        reranker_weight: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        try:
            search_config = _search_config(
                runtime.knowledge_service.config.search,
                top_k=top_k,
                candidate_pool=candidate_pool,
                fts_weight=fts_weight,
                vector_weight=vector_weight,
                metadata_weight=metadata_weight,
                reranker_weight=reranker_weight,
            )
        except ValueError as exc:
            return HTMLResponse(
                _error_page("KNOWLEDGE_SEARCH_PROFILE_INVALID", str(exc)),
                status_code=422,
            )
        result = runtime.knowledge_service.search(
            namespace=_namespace(namespace),
            query=query,
            top_k=search_config.default_top_k,
            search_config=search_config,
        )
        if not result.get("ok"):
            return HTMLResponse(
                _error_page(str(result.get("error_code") or "KNOWLEDGE_SEARCH_FAILED"), str(result.get("message") or "search failed")),
                status_code=422,
            )
        return HTMLResponse(_search_page(_namespace(namespace), result, current.csrf_token))

    @router.post("/namespaces/{namespace}/answer", response_class=HTMLResponse)
    async def answer(
        request: Request,
        namespace: str,
        query: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/answer",
            data={"query": query},
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_answer_page(_namespace(namespace), query, payload, current.csrf_token))

    @router.post("/namespaces/{namespace}/reindex", response_class=HTMLResponse)
    async def reindex_namespace(
        request: Request,
        namespace: str,
        confirm: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
        embedding_profile_id: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        if confirm != "reindex":
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CONFIRM_REQUIRED", "请确认 namespace reindex"), status_code=409)
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/reindex"
            + (f"?embedding_profile_id={quote(embedding_profile_id)}" if embedding_profile_id else ""),
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_operation_page("Reindex 已完成", payload, _namespace(namespace)))

    @router.post("/namespaces/{namespace}/sources/{source_id}/reindex", response_class=HTMLResponse)
    async def reindex_source(
        request: Request,
        namespace: str,
        source_id: str,
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/reindex?source_id={quote(source_id)}",
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_operation_page("Source reindex 已完成", payload, _namespace(namespace)))

    @router.post("/namespaces/{namespace}/sources/{source_id}/approve", response_class=HTMLResponse)
    async def approve_source(
        request: Request,
        namespace: str,
        source_id: str,
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        resolved_namespace = _namespace(namespace)
        if resolved_namespace != _BAZI_THEORY_DRAFT_NAMESPACE:
            return HTMLResponse(
                _error_page("KNOWLEDGE_APPROVAL_NAMESPACE_INVALID", "只有草稿箱来源可以审核发布"),
                status_code=422,
            )
        status_code, payload = await api(
            request,
            "POST",
            f"/knowledge/namespaces/{quote(resolved_namespace)}/sources/{quote(source_id)}/approve",
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_operation_page("审核通过并已发布", payload, _BAZI_THEORY_NAMESPACE))

    @router.post("/namespaces/{namespace}/sources/{source_id}/delete", response_class=HTMLResponse)
    async def delete_source(
        request: Request,
        namespace: str,
        source_id: str,
        confirm_source_id: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
    ):  # noqa: ANN201
        current = session(request)
        if current is None:
            return login_redirect()
        if not valid_csrf(current, csrf_token):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CSRF_INVALID", "CSRF 校验失败"), status_code=403)
        if not hmac.compare_digest(confirm_source_id, source_id):
            return HTMLResponse(_error_page("KNOWLEDGE_CONSOLE_CONFIRM_REQUIRED", "source id 确认不匹配"), status_code=409)
        status_code, payload = await api(
            request,
            "DELETE",
            f"/knowledge/namespaces/{quote(_namespace(namespace))}/sources/{quote(source_id)}",
        )
        if status_code >= 400:
            return HTMLResponse(_api_error_page(payload), status_code=status_code)
        return HTMLResponse(_operation_page("Source 已删除", payload, _namespace(namespace)))

    return router


def _namespace(value: str) -> str:
    resolved = str(value or "").strip()
    if not resolved or len(resolved) > 64 or not resolved[0].isalpha() or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in resolved
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "KNOWLEDGE_NAMESPACE_INVALID",
                "message": "namespace must start with a lowercase letter and contain only lowercase letters, digits, '_' or '-'",
            },
        )
    return resolved


def _namespace_label(namespace: str) -> str:
    if namespace == _BAZI_THEORY_DRAFT_NAMESPACE:
        return "草稿箱"
    if namespace == _BAZI_THEORY_NAMESPACE:
        return "正式库"
    return namespace


def _search_config(
    default: KnowledgeSearchConfig,
    *,
    top_k: str,
    candidate_pool: str,
    fts_weight: str,
    vector_weight: str,
    metadata_weight: str,
    reranker_weight: str,
) -> KnowledgeSearchConfig:
    try:
        resolved_top_k = int(top_k) if str(top_k).strip() else default.default_top_k
        resolved_pool = int(candidate_pool) if str(candidate_pool).strip() else default.candidate_pool
        if not 1 <= resolved_top_k <= 50 or not 1 <= resolved_pool <= 200:
            raise ValueError("top_k must be 1-50 and candidate_pool must be 1-200")
        weights = {
            "fts_weight": float(fts_weight) if str(fts_weight).strip() else default.fts_weight,
            "vector_weight": float(vector_weight) if str(vector_weight).strip() else default.vector_weight,
            "metadata_weight": float(metadata_weight) if str(metadata_weight).strip() else default.metadata_weight,
            "reranker_weight": float(reranker_weight) if str(reranker_weight).strip() else default.reranker_weight,
        }
        if any(not math.isfinite(value) or value < 0 for value in weights.values()):
            raise ValueError("search weights must be finite and non-negative")
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("at least one search weight must be greater than zero")
        normalized = {name: value / total for name, value in weights.items()}
        return KnowledgeSearchConfig(
            default_top_k=resolved_top_k,
            candidate_pool=resolved_pool,
            **normalized,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError(str(exc)) from exc


def _encode_json(payload: dict[str, object]) -> str:
    return _encode_bytes(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _display_uri(value: object) -> str:
    return unquote(str(value or ""))


def _page(title: str, body: str, *, nav: str = "") -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)} · Knowledge Console</title><style>
:root{{--bg:#f4f7fb;--panel:#fff;--ink:#172033;--muted:#667085;--line:#d9e0eb;--brand:#2457d6;--danger:#b42318}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"PingFang SC",sans-serif}}a{{color:var(--brand)}}header{{background:#111827;color:#fff;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}}header a{{color:#fff;text-decoration:none}}main{{max-width:1200px;margin:24px auto;padding:0 18px}}.grid{{display:grid;grid-template-columns:1fr 1.4fr;gap:18px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:18px;overflow:auto}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}}.card{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px}}.value{{font-size:24px;font-weight:700}}label{{display:block;font-weight:650;margin:10px 0 4px}}input,select,textarea,button{{font:inherit}}input,select,textarea{{width:100%;padding:9px;border:1px solid #bcc6d6;border-radius:7px}}textarea{{min-height:72px}}button,.button{{display:inline-block;border:0;border-radius:7px;padding:9px 14px;background:var(--brand);color:#fff;text-decoration:none;cursor:pointer}}button.danger{{background:var(--danger)}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}code,pre{{font-family:ui-monospace,SFMono-Regular,monospace}}pre{{white-space:pre-wrap;background:#0b1020;color:#e5e7eb;padding:12px;border-radius:8px}}.muted{{color:var(--muted)}}.error{{border-color:#fda29b;background:#fff6f5}}.ok{{border-color:#86efac;background:#f0fdf4}}.actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.fields{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}details{{margin:12px 0}}summary{{cursor:pointer;font-weight:650}}@media(max-width:760px){{.grid,.cards,.fields{{grid-template-columns:1fr}}header{{padding:12px 16px}}}}
</style></head><body><header><a href="/knowledge/console"><strong>Knowledge Console</strong></a>{nav}</header><main>{body}</main></body></html>"""


def _login_page(error: str = "") -> str:
    message = f'<div class="panel error"><strong>{_e(error)}</strong></div>' if error else ""
    return _page(
        "登录",
        f"<div class=\"panel\" style=\"max-width:460px;margin:8vh auto\"><h1>Operator 登录</h1><p class=\"muted\">使用 KNOWLEDGE_OPERATOR_TOKEN 建立短时 HttpOnly session。</p>{message}<form method=\"post\" action=\"/knowledge/console/login\"><label>Operator token</label><input type=\"password\" name=\"token\" autocomplete=\"current-password\" required><p><button type=\"submit\">登录</button></p></form></div>",
    )


def _home_page(
    *,
    namespace: str,
    namespaces: list[dict[str, object]],
    sources: list[dict[str, object]],
    jobs: list[dict[str, object]],
    stats: dict[str, object],
    csrf_token: str,
) -> str:
    options = "".join(
        f'<option value="{_e(item.get("namespace"))}"{" selected" if item.get("namespace") == namespace else ""}>{_e(_namespace_label(str(item.get("namespace") or "")))}</option>'
        for item in namespaces
    )
    if namespace not in {str(item.get("namespace") or "") for item in namespaces}:
        options += f'<option selected value="{_e(namespace)}">{_e(_namespace_label(namespace))}</option>'
    source_rows = "".join(
        f'<tr><td><a href="/knowledge/console/namespaces/{quote(namespace)}/sources/{quote(str(item.get("source_id") or ""))}">{_e(item.get("title"))}</a><br><code>{_e(item.get("source_id"))}</code></td><td>{_e(item.get("version"))}</td><td>{_e(item.get("chunk_count"))}</td><td>{_e("待审核" if namespace == _BAZI_THEORY_DRAFT_NAMESPACE else "已发布")}</td></tr>'
        for item in sources
    ) or '<tr><td colspan="4" class="muted">暂无 source</td></tr>'
    job_rows = "".join(
        f'<tr><td><code>{_e(item.get("job_id"))}</code></td><td>{_e(item.get("source_title"))}</td><td>{_e(item.get("status"))}</td><td>{_e(item.get("percent"))}%</td><td><code>{_e(item.get("error_code"))}</code> {_e(item.get("error"))}</td></tr>'
        for item in jobs[:20]
    ) or '<tr><td colspan="5" class="muted">暂无 job</td></tr>'
    csrf = _e(csrf_token)
    chunking = dict(stats.get("chunking_defaults") or {})
    search_defaults = dict(stats.get("search_defaults") or {})
    current_profile_id = str(stats.get("embedding_profile_id") or "default")
    profile_options = "".join(
        f'<option value="{_e(item.get("profile_id"))}"{" selected" if item.get("profile_id") == current_profile_id else ""}>{_e(item.get("profile_id"))} · {_e(item.get("model"))} · {_e(item.get("dimension"))}d</option>'
        for item in list(stats.get("embedding_profiles") or [])
    )
    nav = f'<form method="post" action="/knowledge/console/logout"><input type="hidden" name="csrf_token" value="{csrf}"><button type="submit">退出</button></form>'
    import_panel = (
        f'<section class="panel"><h2>导入草稿</h2><form method="post" enctype="multipart/form-data" action="/knowledge/console/namespaces/{quote(namespace)}/previews"><input type="hidden" name="csrf_token" value="{csrf}"><label>文件（.md/.txt）</label><input type="file" name="file" accept=".md,.txt" required><label>标题（可选）</label><input name="title"><label>来源链接（可选）</label><input type="url" name="source_url"><label>证据类型</label><select name="evidence_kind"><option value="modern_commentary" selected>现代注解</option><option value="classical_original">古籍原文</option><option value="historical_commentary">历代注解</option><option value="marten_interpretation">Marten 释义</option><option value="course_notes">课程讲义</option><option value="case_record">命例</option></select><details><summary>分段与向量设置</summary><div class="fields"><div><label>目标字符数</label><input type="number" name="target_chars" min="100" max="20000" value="{_e(chunking.get("target_chars"))}" required></div><div><label>重叠字符数</label><input type="number" name="overlap_chars" min="0" value="{_e(chunking.get("overlap_chars"))}" required></div><div><label>最大字符数</label><input type="number" name="max_chars" min="100" max="50000" value="{_e(chunking.get("max_chars"))}" required></div></div><label>Embedding profile</label><select name="embedding_profile_id">{profile_options}</select></details><p><button type="submit">生成 Preview</button></p></form></section>'
        if namespace == _BAZI_THEORY_DRAFT_NAMESPACE
        else ""
    )
    page_title = "经典书籍草稿箱" if namespace == _BAZI_THEORY_DRAFT_NAMESPACE else "经典书籍正式库"
    body = f"""
<div class="actions"><h1 style="flex:1">{page_title}</h1><form method="get" action="/knowledge/console"><select name="namespace" onchange="this.form.submit()">{options}</select></form></div>
<div class="cards"><div class="card"><div class="muted">Sources</div><div class="value">{len(sources)}</div></div><div class="card"><div class="muted">Chunks</div><div class="value">{_e(stats.get("chunk_count"))}</div></div><div class="card"><div class="muted">导入任务</div><div class="value">{len(jobs)}</div></div><div class="card"><div class="muted">Embedding hash</div><code>{_e(stats.get("embedding_config_hash") or "未索引")}</code></div></div>
<div class="grid"><div><section class="panel"><h2>Sources</h2><table><thead><tr><th>来源</th><th>版本</th><th>Chunks</th><th>审核</th></tr></thead><tbody>{source_rows}</tbody></table></section><section class="panel"><h2>导入任务</h2><table><thead><tr><th>任务 ID</th><th>来源</th><th>状态</th><th>进度</th><th>错误</th></tr></thead><tbody>{job_rows}</tbody></table></section></div><div>
{import_panel}
<section class="panel"><h2>知识问答</h2><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/answer"><input type="hidden" name="csrf_token" value="{csrf}"><label>Query</label><input name="query" required><p><button type="submit">AI 解释</button></p></form><details><summary>本次检索参数</summary><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/search"><input type="hidden" name="csrf_token" value="{csrf}"><label>Query</label><input name="query" required><div class="fields"><div><label>Top K</label><input type="number" name="top_k" min="1" max="50" value="{_e(search_defaults.get("default_top_k"))}"></div><div><label>Candidate pool</label><input type="number" name="candidate_pool" min="1" max="200" value="{_e(search_defaults.get("candidate_pool"))}"></div><div></div><div><label>FTS weight</label><input type="number" name="fts_weight" min="0" step="0.01" value="{_e(search_defaults.get("fts_weight"))}"></div><div><label>Vector weight</label><input type="number" name="vector_weight" min="0" step="0.01" value="{_e(search_defaults.get("vector_weight"))}"></div><div><label>Metadata weight</label><input type="number" name="metadata_weight" min="0" step="0.01" value="{_e(search_defaults.get("metadata_weight"))}"></div><div><label>Reranker weight</label><input type="number" name="reranker_weight" min="0" step="0.01" value="{_e(search_defaults.get("reranker_weight"))}"></div></div><p><button type="submit">检索试查</button></p></form></details></section>
<section class="panel error"><h2>Namespace reindex</h2><p>会重建该 namespace 的全部向量。选择 profile 并输入 <code>reindex</code> 确认。</p><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/reindex"><input type="hidden" name="csrf_token" value="{csrf}"><label>Embedding profile</label><select name="embedding_profile_id">{profile_options}</select><label>确认</label><input name="confirm" required><p><button type="submit" class="danger">Reindex namespace</button></p></form></section>
</div></div>"""
    return _page(page_title, body, nav=nav)


def _preview_page(*, namespace: str, preview: dict[str, object], csrf_token: str) -> str:
    metadata = dict(preview.get("metadata") or {})
    index_profile = dict(preview.get("index_profile") or {})
    chunking = dict(index_profile.get("chunking") or {})
    embedding = dict(index_profile.get("embedding") or {})
    chunk_length = dict(preview.get("chunk_length") or {})
    chunks = "".join(
        f'<tr><td>{_e(item.get("ordinal"))}</td><td>{_e(item.get("heading"))}</td><td>{_e(item.get("token_estimate"))}</td><td>{_e(item.get("text_preview"))}</td></tr>'
        for item in list(preview.get("chunks") or [])
    )
    body = f"""<section class="panel ok"><h1>内容预览</h1><p>预览不会创建来源或导入任务。确认内容与分段后再保存到草稿箱。</p><dl><dt>Preview ID</dt><dd><code>{_e(preview.get("preview_id"))}</code></dd><dt>Source ID</dt><dd><code>{_e(preview.get("source_id"))}</code></dd><dt>URI / Version</dt><dd>{_e(_display_uri(preview.get("uri")))} / {_e(preview.get("version"))}</dd><dt>Digest</dt><dd><code>{_e(metadata.get("content_sha256"))}</code></dd><dt>Chunks</dt><dd>{_e(preview.get("chunk_count"))} · 长度 {_e(chunk_length.get("min"))}/{_e(chunk_length.get("average"))}/{_e(chunk_length.get("max"))}（最小/平均/最大）</dd><dt>Chunk profile</dt><dd>target {_e(chunking.get("target_chars"))} · overlap {_e(chunking.get("overlap_chars"))} · max {_e(chunking.get("max_chars"))}</dd><dt>Embedding profile</dt><dd>{_e(embedding.get("profile_id"))} · {_e(embedding.get("model"))} · {_e(embedding.get("dimension"))}d</dd></dl><details><summary>Metadata</summary><pre>{_e(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))}</pre></details><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/previews/{quote(str(preview.get("preview_id") or ""))}/publish"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><p><button type="submit">保存到草稿箱</button> <a class="button" href="/knowledge/console?namespace={quote(namespace)}">返回</a></p></form></section><section class="panel"><h2>全部 Chunks</h2><table><thead><tr><th>#</th><th>Heading</th><th>Tokens</th><th>Text</th></tr></thead><tbody>{chunks}</tbody></table></section>"""
    return _page("Preview", body)


def _published_page(namespace: str, payload: dict[str, object]) -> str:
    is_draft = namespace == _BAZI_THEORY_DRAFT_NAMESPACE
    title = "草稿导入已开始" if is_draft else "导入已开始"
    destination = "草稿箱" if is_draft else _namespace_label(namespace)
    return _page(
        title,
        f'<section class="panel ok"><h1>{_e(title)}</h1><p>内容完成处理后会出现在{_e(destination)}，审核通过后才进入正式库。</p><p>导入任务：<code>{_e(payload.get("job_id"))}</code></p><p>状态：{_e(payload.get("status"))}</p><p><a class="button" href="/knowledge/console?namespace={quote(namespace)}">查看导入任务</a></p></section>',
    )


def _source_page(*, namespace: str, source: dict[str, object], chunks: list[dict[str, object]], csrf_token: str) -> str:
    metadata = dict(source.get("metadata") or {})
    rows = "".join(
        f'<tr><td>{_e(item.get("ordinal"))}</td><td>{_e(item.get("heading"))}</td><td>{_e(item.get("token_estimate"))}</td><td>{_e(item.get("text_preview"))}</td></tr>'
        for item in chunks
    )
    source_id = str(source.get("source_id") or "")
    approval = (
        f'<section class="panel ok"><h2>审核</h2><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/sources/{quote(source_id)}/approve"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><button type="submit">审核通过并发布</button></form></section>'
        if namespace == _BAZI_THEORY_DRAFT_NAMESPACE
        else ""
    )
    body = f"""<p><a href="/knowledge/console?namespace={quote(namespace)}">← 返回</a></p><section class="panel"><h1>{_e(source.get("title"))}</h1><p><code>{_e(source_id)}</code></p><p>{_e(_display_uri(source.get("uri")))} · {_e(source.get("version"))} · {len(chunks)} chunks</p><pre>{_e(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))}</pre><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/sources/{quote(source_id)}/reindex"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><button type="submit">Reindex source</button></form></section>{approval}<section class="panel"><h2>Chunks</h2><table><thead><tr><th>#</th><th>Heading</th><th>Tokens</th><th>Text</th></tr></thead><tbody>{rows}</tbody></table></section><section class="panel error"><h2>删除 source</h2><p>将软删除 source 与 {len(chunks)} 个 active chunks。请输入完整 source id 确认。</p><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/sources/{quote(source_id)}/delete"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><input name="confirm_source_id" required><p><button type="submit" class="danger">Delete source</button></p></form></section>"""
    return _page(str(source.get("title") or "Source"), body)


def _search_page(namespace: str, result: dict[str, object], csrf_token: str) -> str:
    rows = "".join(
        f'<tr><td>{_e(item.get("source_title"))}<br><code>{_e(item.get("source_id"))}</code></td><td>{_e(item.get("heading"))}</td><td>{_e(item.get("score"))}<br><code>{_e(json.dumps(item.get("score_parts") or {}, sort_keys=True))}</code></td><td>{_e(item.get("text"))}</td></tr>'
        for item in list(result.get("results") or [])
    ) or '<tr><td colspan="4" class="muted">无结果</td></tr>'
    timings = " · ".join(f"{name} {float(result.get(key) or 0):.1f} ms" for name, key in (("Embedding", "embedding_ms"), ("FTS", "fts_ms"), ("Vector", "vector_ms"), ("Rerank", "rerank_ms"), ("Total", "total_ms")))
    body = f"""<p><a href="/knowledge/console?namespace={quote(namespace)}">← 返回</a></p><section class="panel"><h1>检索试查</h1><p>Query：{_e(result.get("query"))}</p><p>Mode：<code>{_e(result.get("retrieval_mode"))}</code> · Vector：<code>{_e(result.get("vector_status"))}</code> · Rerank：<code>{_e(result.get("rerank_status"))}</code></p><p class="muted">{_e(timings)}</p><p class="muted">{_e(result.get("degraded_reason"))}</p><table><thead><tr><th>Source</th><th>Heading</th><th>Score</th><th>Text</th></tr></thead><tbody>{rows}</tbody></table></section><section class="panel"><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/answer"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><input type="hidden" name="query" value="{_e(result.get("query"))}"><button type="submit">AI 解释</button></form></section>"""
    return _page("检索试查", body)


def _answer_page(namespace: str, query: str, result: dict[str, object], csrf_token: str) -> str:
    evidence_rows = "".join(
        f'<tr><td>{_e(item.get("source_title"))}</td><td>{_e(item.get("heading"))}</td><td><code>{_e(item.get("evidence_kind"))}</code></td><td>{_e(item.get("text"))}</td></tr>'
        for item in list(result.get("evidence") or [])
    ) or '<tr><td colspan="4" class="muted">无证据</td></tr>'
    usage = json.dumps(result.get("usage") or {}, ensure_ascii=False, sort_keys=True)
    timing = f'检索 {float(result.get("retrieval_ms") or 0):.1f} ms · 生成 {float(result.get("generation_ms") or 0):.1f} ms · 总计 {float(result.get("total_ms") or 0):.1f} ms · 模型请求 {_e(result.get("model_request_count"))}'
    body = f"""<p><a href="/knowledge/console?namespace={quote(namespace)}">← 返回</a></p><section class="panel"><h1>AI 解释</h1><p>Query：{_e(query)}</p><p class="muted">{_e(timing)}</p><p class="muted">Tokens：<code>{_e(usage)}</code></p><article class="answer"><pre>{_e(result.get("answer"))}</pre></article></section><section class="panel"><h2>使用的证据</h2><table><thead><tr><th>书名</th><th>章节</th><th>类型</th><th>原文</th></tr></thead><tbody>{evidence_rows}</tbody></table></section><section class="panel"><form method="post" action="/knowledge/console/namespaces/{quote(namespace)}/answer"><input type="hidden" name="csrf_token" value="{_e(csrf_token)}"><label>继续提问</label><input name="query" required><p><button type="submit">AI 解释</button></p></form></section>"""
    return _page("AI 解释", body)


def _operation_page(title: str, payload: dict[str, object], namespace: str) -> str:
    return _page(
        title,
        f'<section class="panel ok"><h1>{_e(title)}</h1><pre>{_e(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))}</pre><p><a class="button" href="/knowledge/console?namespace={quote(namespace)}">返回 Console</a></p></section>',
    )


def _api_error_page(payload: dict[str, object]) -> str:
    error = dict(payload.get("error") or {})
    return _error_page(
        str(error.get("code") or "KNOWLEDGE_CONSOLE_UPSTREAM_FAILED"),
        str(error.get("message") or "Knowledge operation failed"),
    )


def _error_page(code: str, message: str) -> str:
    return _page(
        "操作失败",
        f'<section class="panel error"><h1>操作失败</h1><p><code>{_e(code)}</code></p><p>{_e(message)}</p><p><a class="button" href="/knowledge/console">返回 Console</a></p></section>',
    )
