from __future__ import annotations

import codecs
import hashlib
import hmac
import re
import shutil
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError

from marten_runtime.knowledge.config import KnowledgeChunkingConfig
from marten_runtime.knowledge.answering import KnowledgeAnswerService
from marten_runtime.knowledge.previews import KnowledgePreviewStore


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + _MAX_MULTIPART_OVERHEAD_BYTES
_READ_CHUNK_BYTES = 64 * 1024
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_SUFFIXES = frozenset({".txt", ".md"})
_BAZI_THEORY_DRAFT_NAMESPACE = "bazi-theory-sandbox"
_BAZI_THEORY_NAMESPACE = "bazi-theory"
_EVIDENCE_KINDS = frozenset(
    {
        "classical_original",
        "historical_commentary",
        "modern_commentary",
        "marten_interpretation",
        "course_notes",
        "case_record",
    }
)
_METADATA_LIMITS = {
    "title": 300,
    "license": 200,
    "provenance": 2000,
    "calculation_scope": 500,
    "uri": 2000,
    "version": 300,
    "corpus_type": 32,
    "school": 300,
    "method": 500,
    "content_type": 100,
    "work": 300,
    "chapter": 500,
    "edition_or_source": 1000,
    "source_url": 2000,
    "verification_status": 100,
    "evidence_kind": 100,
}


class KnowledgeRouteError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


def error_envelope(code: str, message: str, *, retryable: bool = False) -> dict[str, object]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def build_knowledge_router(runtime, *, operator_token: str) -> APIRouter:  # noqa: ANN001
    router = APIRouter()
    expected_token = operator_token.encode("utf-8")
    preview_store = KnowledgePreviewStore(runtime.knowledge_service.jobs.staging_root)
    answer_service = KnowledgeAnswerService(
        knowledge_service=runtime.knowledge_service,
        llm_factory=lambda: runtime.llm_client_factory.get(
            runtime.default_agent.model_profile,
            default_client=runtime.runtime_loop.llm,
        ),
        model_profile=runtime.default_agent.model_profile,
    )

    def authorize(request: Request) -> None:
        if not operator_authorized(request.headers.get("authorization"), expected_token):
            raise KnowledgeRouteError(
                401,
                "KNOWLEDGE_OPERATOR_UNAUTHORIZED",
                "operator authorization failed",
            )

    def context(request: Request, namespace: str | None = None) -> None:
        authorize(request)
        if namespace is not None and not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise KnowledgeRouteError(422, "KNOWLEDGE_NAMESPACE_INVALID", "namespace is invalid")

    async def stage_preview(
        *,
        request: Request,
        namespace: str,
        file: UploadFile,
        title: str | None,
        license_name: str | None,
        provenance: str | None,
        calculation_scope: str | None,
        review_status: str,
        uri: str | None,
        version: str | None,
        corpus_type: str | None,
        school: str | None,
        method: str | None,
        content_type: str | None,
        work: str | None,
        chapter: str | None,
        edition_or_source: str | None,
        source_url: str | None,
        verification_status: str | None,
        evidence_kind: str,
        target_chars: str | None,
        overlap_chars: str | None,
        max_chars: str | None,
        embedding_profile_id: str | None,
    ) -> dict[str, object]:
        context(request, namespace)
        _validate_upload_metadata(
            title,
            license_name,
            provenance,
            calculation_scope,
            review_status,
            namespace=namespace,
        )
        optional_metadata = {
            "uri": uri,
            "version": version,
            "corpus_type": corpus_type,
            "school": school,
            "method": method,
            "content_type": content_type,
            "work": work,
            "chapter": chapter,
            "edition_or_source": edition_or_source,
            "source_url": source_url,
            "verification_status": verification_status,
            "evidence_kind": evidence_kind,
        }
        _validate_optional_metadata(**optional_metadata)
        _validate_evidence_kind(evidence_kind)
        chunking = _resolve_chunking_config(
            runtime.knowledge_service.config.chunking,
            target_chars=target_chars,
            overlap_chars=overlap_chars,
            max_chars=max_chars,
        )
        profile_id = str(embedding_profile_id or "default").strip()
        profile_validation = runtime.knowledge_service.validate_embedding_profile(
            namespace=namespace,
            embedding_profile_id=profile_id,
        )
        if not profile_validation.get("ok"):
            raise KnowledgeRouteError(
                409 if profile_validation.get("error_code") == "KNOWLEDGE_EMBEDDING_PROFILE_MISMATCH" else 422,
                str(profile_validation.get("error_code") or "KNOWLEDGE_EMBEDDING_PROFILE_INVALID"),
                str(profile_validation.get("message") or "embedding profile is invalid"),
            )
        original_filename, suffix = _validate_filename(file.filename)
        _check_declared_size(request)
        preview_id = f"kprv_{uuid4().hex[:12]}"
        preview_directory = runtime.knowledge_service.jobs.staging_root / preview_id
        preview_directory.mkdir(mode=0o700)
        preview_directory.chmod(0o700)
        stored_name = f"source{suffix}"
        staged_path = preview_directory / stored_name
        try:
            size, digest = await _stream_upload(file, staged_path)
            encoding = _validate_text_encoding(staged_path)
            provided_version = str(version or "").strip()
            provided_uri = str(uri or "").strip()
            resolved_version = provided_version or f"sha256:{digest}"
            resolved_uri = provided_uri or (
                f"upload://{namespace}/{preview_id}/{quote(original_filename)}"
            )
            if evidence_kind in {"classical_original", "historical_commentary"}:
                optional_metadata["work"] = str(work or title or original_filename).strip()
                optional_metadata["chapter"] = str(chapter or "document").strip()
                optional_metadata["edition_or_source"] = str(
                    edition_or_source or provenance or original_filename
                ).strip()
                optional_metadata["source_url"] = str(source_url or resolved_uri).strip()
                optional_metadata["verification_status"] = str(
                    verification_status or "operator-provided"
                ).strip()
            _validate_classical_metadata(optional_metadata)
            source_id = _stable_source_id(
                namespace=namespace,
                uri=provided_uri or (f"content-sha256:{digest}" if provided_version else ""),
                version=resolved_version,
            )
            metadata = {
                "license": str(license_name).strip(),
                "provenance": str(provenance).strip(),
                "calculation_scope": str(calculation_scope).strip(),
                "review_status": str(review_status).strip(),
                "original_filename": original_filename,
                "stored_filename": stored_name,
                "content_sha256": digest,
                "content_bytes": size,
                "encoding": encoding,
                "media_type": str(file.content_type or ""),
                "preview_id": preview_id,
                "index_profile": {
                    "chunking": chunking.model_dump(mode="json"),
                    "embedding_profile_id": profile_id,
                },
            }
            for name in (
                "school",
                "method",
                "corpus_type",
                "content_type",
                "work",
                "chapter",
                "edition_or_source",
                "source_url",
                "verification_status",
                "evidence_kind",
            ):
                value = str(optional_metadata.get(name) or "").strip()
                if value:
                    metadata[name] = value
            source = {
                "source_id": source_id,
                "title": str(title).strip(),
                "kind": "markdown" if suffix == ".md" else "text",
                "uri": resolved_uri,
                "version": resolved_version,
                "metadata": metadata,
            }
            preview = runtime.knowledge_service.preview_file(
                namespace=namespace,
                file_path=str(staged_path),
                source=source,
            )
            return preview_store.record(
                preview_id=preview_id,
                namespace=namespace,
                staged_file_path=f"{preview_id}/{stored_name}",
                source=source,
                preview=preview,
            )
        except BaseException:
            if preview_directory.exists():
                shutil.rmtree(preview_directory, ignore_errors=True)
            raise

    def publish_preview(*, namespace: str, preview_id: str) -> dict[str, object]:
        try:
            return preview_store.publish(
                namespace=namespace,
                preview_id=preview_id,
                publisher=runtime.knowledge_service.ingest_file,
            )
        except KeyError as exc:
            raise KnowledgeRouteError(404, "KNOWLEDGE_PREVIEW_NOT_FOUND", "preview was not found") from exc
        except TimeoutError as exc:
            raise KnowledgeRouteError(410, "KNOWLEDGE_PREVIEW_EXPIRED", "preview has expired") from exc
        except (FileNotFoundError, ValueError) as exc:
            raise KnowledgeRouteError(
                409,
                "KNOWLEDGE_PREVIEW_DIGEST_MISMATCH",
                "preview content changed before publish",
            ) from exc

    @router.get("/namespaces")
    def list_namespaces(request: Request) -> dict[str, object]:
        context(request)
        items = runtime.knowledge_service.store.list_namespace_summaries()
        for item in items:
            index_hash = str(item.get("index_embedding_config_hash") or "")
            profile_id = str(item.get("embedding_profile_id") or "default")
            current_hash = runtime.knowledge_service.embedding_profile_hashes.get(profile_id, "")
            item["current_embedding_config_hash"] = current_hash
            item["config_mismatch"] = bool(index_hash and index_hash != current_hash)
        return {"ok": True, "items": items, "total": len(items)}

    @router.get("/namespaces/{namespace}/sources")
    def list_sources(
        request: Request,
        namespace: str,
        page: str = "1",
        page_size: str = "50",
    ) -> dict[str, object]:
        context(request, namespace)
        resolved_page, resolved_page_size = _pagination(page, page_size)
        items, total = runtime.knowledge_service.store.list_source_summaries(
            namespace,
            page=resolved_page,
            page_size=resolved_page_size,
        )
        return _page(items, resolved_page, resolved_page_size, total)

    @router.get("/namespaces/{namespace}/sources/{source_id}/chunks")
    def list_source_chunks(
        request: Request,
        namespace: str,
        source_id: str,
        page: str = "1",
        page_size: str = "50",
    ) -> dict[str, object]:
        context(request, namespace)
        if runtime.knowledge_service.store.get_source(namespace, source_id) is None:
            raise KnowledgeRouteError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "source was not found")
        resolved_page, resolved_page_size = _pagination(page, page_size)
        items, total = runtime.knowledge_service.store.list_chunk_summaries(
            namespace,
            source_id,
            page=resolved_page,
            page_size=resolved_page_size,
        )
        return _page(items, resolved_page, resolved_page_size, total)

    @router.get("/namespaces/{namespace}/jobs")
    def list_jobs(
        request: Request,
        namespace: str,
        page: str = "1",
        page_size: str = "50",
    ) -> dict[str, object]:
        context(request, namespace)
        resolved_page, resolved_page_size = _pagination(page, page_size)
        items, total = runtime.knowledge_service.store.list_ingest_job_summaries(
            namespace,
            page=resolved_page,
            page_size=resolved_page_size,
        )
        return _page(items, resolved_page, resolved_page_size, total)

    @router.get("/namespaces/{namespace}/stats")
    def namespace_stats(request: Request, namespace: str) -> dict[str, object]:
        context(request, namespace)
        return runtime.knowledge_service.stats(namespace=namespace)

    @router.post("/namespaces/{namespace}/answer")
    def answer_query(
        request: Request,
        namespace: str,
        query: Annotated[str, Form()] = "",
    ) -> dict[str, object]:
        context(request, namespace)
        if not str(query or "").strip():
            raise KnowledgeRouteError(422, "KNOWLEDGE_QUERY_REQUIRED", "query is required")
        result = answer_service.answer(namespace=namespace, query=query)
        if not result.get("ok"):
            raise KnowledgeRouteError(
                502,
                str(result.get("error_code") or "KNOWLEDGE_ANSWER_FAILED"),
                str(result.get("message") or "answer generation failed"),
                retryable=True,
            )
        return result

    @router.delete("/namespaces/{namespace}/sources/{source_id}")
    def delete_source(request: Request, namespace: str, source_id: str) -> dict[str, object]:
        context(request, namespace)
        if runtime.knowledge_service.store.get_source(namespace, source_id) is None:
            raise KnowledgeRouteError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "source was not found")
        return runtime.knowledge_service.delete_source(namespace=namespace, source_id=source_id)

    @router.post("/namespaces/{namespace}/sources/{source_id}/approve")
    def approve_source(request: Request, namespace: str, source_id: str) -> dict[str, object]:
        context(request, namespace)
        if namespace != _BAZI_THEORY_DRAFT_NAMESPACE:
            raise KnowledgeRouteError(
                422,
                "KNOWLEDGE_APPROVAL_NAMESPACE_INVALID",
                "only the bazi theory draft namespace supports approval",
            )
        result = runtime.knowledge_service.approve_source(
            draft_namespace=namespace,
            source_id=source_id,
            target_namespace=_BAZI_THEORY_NAMESPACE,
        )
        if result.get("ok"):
            return result
        error_code = str(result.get("error_code") or "KNOWLEDGE_APPROVAL_FAILED")
        raise KnowledgeRouteError(
            404 if error_code == "KNOWLEDGE_SOURCE_NOT_FOUND" else 409,
            error_code,
            str(result.get("message") or "source approval failed"),
        )

    @router.post("/namespaces/{namespace}/reindex")
    def reindex(
        request: Request,
        namespace: str,
        source_id: str | None = None,
        embedding_profile_id: str | None = None,
    ) -> dict[str, object]:
        context(request, namespace)
        result = runtime.knowledge_service.reindex(
            namespace=namespace,
            source_id=source_id,
            embedding_profile_id=embedding_profile_id,
        )
        if not result.get("ok") and result.get("error_code") == "KNOWLEDGE_SOURCE_NOT_FOUND":
            raise KnowledgeRouteError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "source was not found")
        if not result.get("ok"):
            raise KnowledgeRouteError(
                422,
                str(result.get("error_code") or "KNOWLEDGE_REINDEX_FAILED"),
                str(result.get("message") or "reindex failed"),
                retryable=True,
            )
        return result

    @router.post("/namespaces/{namespace}/uploads", status_code=202)
    async def upload_source(
        request: Request,
        namespace: str,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
        license: Annotated[str | None, Form()] = None,
        provenance: Annotated[str | None, Form()] = None,
        calculation_scope: Annotated[str | None, Form()] = None,
        review_status: Annotated[str, Form()] = "reviewed",
        uri: Annotated[str | None, Form()] = None,
        version: Annotated[str | None, Form()] = None,
        corpus_type: Annotated[str | None, Form()] = None,
        school: Annotated[str | None, Form()] = None,
        method: Annotated[str | None, Form()] = None,
        content_type: Annotated[str | None, Form()] = None,
        work: Annotated[str | None, Form()] = None,
        chapter: Annotated[str | None, Form()] = None,
        edition_or_source: Annotated[str | None, Form()] = None,
        source_url: Annotated[str | None, Form()] = None,
        verification_status: Annotated[str | None, Form()] = None,
        evidence_kind: Annotated[str, Form()] = "modern_commentary",
        target_chars: Annotated[str | None, Form()] = None,
        overlap_chars: Annotated[str | None, Form()] = None,
        max_chars: Annotated[str | None, Form()] = None,
        embedding_profile_id: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        try:
            preview = await stage_preview(
                request=request,
                namespace=namespace,
                file=file,
                title=title,
                license_name=license,
                provenance=provenance,
                calculation_scope=calculation_scope,
                review_status=review_status,
                uri=uri,
                version=version,
                corpus_type=corpus_type,
                school=school,
                method=method,
                content_type=content_type,
                work=work,
                chapter=chapter,
                edition_or_source=edition_or_source,
                source_url=source_url,
                verification_status=verification_status,
                evidence_kind=evidence_kind,
                target_chars=target_chars,
                overlap_chars=overlap_chars,
                max_chars=max_chars,
                embedding_profile_id=embedding_profile_id,
            )
            published = publish_preview(namespace=namespace, preview_id=str(preview["preview_id"]))
            result = dict(published.get("publish_result") or {})
            return {
                **result,
                "upload_id": preview["preview_id"],
                "preview_id": preview["preview_id"],
                "source_id": preview["source_id"],
                "uri": preview["uri"],
                "version": preview["version"],
            }
        finally:
            await file.close()

    @router.post("/namespaces/{namespace}/previews", status_code=201)
    async def preview_source(
        request: Request,
        namespace: str,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
        license: Annotated[str | None, Form()] = None,
        provenance: Annotated[str | None, Form()] = None,
        calculation_scope: Annotated[str | None, Form()] = None,
        review_status: Annotated[str, Form()] = "reviewed",
        uri: Annotated[str | None, Form()] = None,
        version: Annotated[str | None, Form()] = None,
        corpus_type: Annotated[str | None, Form()] = None,
        school: Annotated[str | None, Form()] = None,
        method: Annotated[str | None, Form()] = None,
        content_type: Annotated[str | None, Form()] = None,
        work: Annotated[str | None, Form()] = None,
        chapter: Annotated[str | None, Form()] = None,
        edition_or_source: Annotated[str | None, Form()] = None,
        source_url: Annotated[str | None, Form()] = None,
        verification_status: Annotated[str | None, Form()] = None,
        evidence_kind: Annotated[str, Form()] = "modern_commentary",
        target_chars: Annotated[str | None, Form()] = None,
        overlap_chars: Annotated[str | None, Form()] = None,
        max_chars: Annotated[str | None, Form()] = None,
        embedding_profile_id: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        try:
            return await stage_preview(
                request=request,
                namespace=namespace,
                file=file,
                title=title,
                license_name=license,
                provenance=provenance,
                calculation_scope=calculation_scope,
                review_status=review_status,
                uri=uri,
                version=version,
                corpus_type=corpus_type,
                school=school,
                method=method,
                content_type=content_type,
                work=work,
                chapter=chapter,
                edition_or_source=edition_or_source,
                source_url=source_url,
                verification_status=verification_status,
                evidence_kind=evidence_kind,
                target_chars=target_chars,
                overlap_chars=overlap_chars,
                max_chars=max_chars,
                embedding_profile_id=embedding_profile_id,
            )
        finally:
            await file.close()

    @router.get("/namespaces/{namespace}/previews/{preview_id}")
    def get_preview(request: Request, namespace: str, preview_id: str) -> dict[str, object]:
        context(request, namespace)
        try:
            return preview_store.public(preview_store.get(namespace=namespace, preview_id=preview_id))
        except KeyError as exc:
            raise KnowledgeRouteError(404, "KNOWLEDGE_PREVIEW_NOT_FOUND", "preview was not found") from exc
        except TimeoutError as exc:
            raise KnowledgeRouteError(410, "KNOWLEDGE_PREVIEW_EXPIRED", "preview has expired") from exc

    @router.post("/namespaces/{namespace}/previews/{preview_id}/publish", status_code=202)
    def publish_source_preview(request: Request, namespace: str, preview_id: str) -> dict[str, object]:
        context(request, namespace)
        return publish_preview(namespace=namespace, preview_id=preview_id)

    @router.delete("/namespaces/{namespace}/previews/{preview_id}")
    def delete_preview(request: Request, namespace: str, preview_id: str) -> dict[str, object]:
        context(request, namespace)
        try:
            deleted = preview_store.delete(namespace=namespace, preview_id=preview_id)
        except KeyError as exc:
            raise KnowledgeRouteError(404, "KNOWLEDGE_PREVIEW_NOT_FOUND", "preview was not found") from exc
        except TimeoutError as exc:
            raise KnowledgeRouteError(410, "KNOWLEDGE_PREVIEW_EXPIRED", "preview has expired") from exc
        if not deleted:
            raise KnowledgeRouteError(409, "KNOWLEDGE_PREVIEW_PUBLISHED", "published preview cannot be deleted")
        return {"ok": True, "preview_id": preview_id, "deleted": True}

    return router


def _pagination(page: str, page_size: str) -> tuple[int, int]:
    try:
        resolved_page = int(page)
        resolved_page_size = int(page_size)
    except (TypeError, ValueError) as exc:
        raise KnowledgeRouteError(422, "KNOWLEDGE_PAGINATION_INVALID", "page and page_size are invalid") from exc
    if resolved_page < 1 or resolved_page_size < 1 or resolved_page_size > 100:
        raise KnowledgeRouteError(422, "KNOWLEDGE_PAGINATION_INVALID", "page and page_size are invalid")
    return resolved_page, resolved_page_size


def _page(items: list[dict[str, object]], page: int, page_size: int, total: int) -> dict[str, object]:
    return {"ok": True, "items": items, "page": page, "page_size": page_size, "total": total}


def _validate_upload_metadata(
    title: str | None,
    license_name: str | None,
    provenance: str | None,
    calculation_scope: str | None,
    review_status: str,
    *,
    namespace: str,
) -> None:
    if any(not str(value or "").strip() for value in (title, license_name, provenance, calculation_scope)):
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_METADATA_INVALID", "required upload metadata is missing")
    values = {
        "title": title,
        "license": license_name,
        "provenance": provenance,
        "calculation_scope": calculation_scope,
    }
    if any(len(str(value or "").strip()) > _METADATA_LIMITS[name] for name, value in values.items()):
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_METADATA_INVALID", "upload metadata exceeds its limit")
    resolved_review_status = str(review_status or "").strip()
    if resolved_review_status not in {"draft", "reviewed"}:
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_REVIEW_REQUIRED", "review_status must be draft or reviewed")
    if namespace != _BAZI_THEORY_DRAFT_NAMESPACE and resolved_review_status != "reviewed":
        raise KnowledgeRouteError(
            422,
            "KNOWLEDGE_UPLOAD_REVIEW_REQUIRED",
            "draft review status is only allowed in bazi-theory-sandbox",
        )


def _validate_optional_metadata(**values: str | None) -> None:
    if any(len(str(value or "").strip()) > _METADATA_LIMITS[name] for name, value in values.items()):
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_METADATA_INVALID", "upload metadata exceeds its limit")


def _validate_classical_metadata(values: dict[str, str | None]) -> None:
    evidence_kind = str(values.get("evidence_kind") or "").strip()
    if evidence_kind not in {"classical_original", "historical_commentary"}:
        return
    required = ("work", "chapter", "edition_or_source", "source_url", "verification_status")
    if any(not str(values.get(name) or "").strip() for name in required):
        raise KnowledgeRouteError(
            422,
            "KNOWLEDGE_UPLOAD_METADATA_INVALID",
            "classical excerpt metadata is incomplete",
        )


def _validate_evidence_kind(value: str) -> None:
    if str(value or "").strip() not in _EVIDENCE_KINDS:
        raise KnowledgeRouteError(
            422,
            "KNOWLEDGE_UPLOAD_EVIDENCE_KIND_INVALID",
            "evidence_kind is invalid",
        )


def _resolve_chunking_config(
    default: KnowledgeChunkingConfig,
    *,
    target_chars: str | None,
    overlap_chars: str | None,
    max_chars: str | None,
) -> KnowledgeChunkingConfig:
    try:
        values = {
            "target_chars": int(target_chars) if str(target_chars or "").strip() else default.target_chars,
            "overlap_chars": int(overlap_chars) if str(overlap_chars or "").strip() else default.overlap_chars,
            "max_chars": int(max_chars) if str(max_chars or "").strip() else default.max_chars,
            "batch_size": default.batch_size,
        }
        if not 100 <= values["target_chars"] <= 20_000:
            raise ValueError("target_chars must be between 100 and 20000")
        if not 100 <= values["max_chars"] <= 50_000:
            raise ValueError("max_chars must be between 100 and 50000")
        return KnowledgeChunkingConfig(**values)
    except (TypeError, ValueError, ValidationError) as exc:
        raise KnowledgeRouteError(
            422,
            "KNOWLEDGE_CHUNKING_PROFILE_INVALID",
            str(exc),
        ) from exc


def _validate_filename(filename: str | None) -> tuple[str, str]:
    value = str(filename or "")
    if not value or Path(value).name != value or "\\" in value:
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_FILENAME_INVALID", "upload filename is invalid")
    suffix = Path(value).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_FORMAT_UNSUPPORTED", "only .txt and .md are supported")
    return value, suffix


def _check_declared_size(request: Request) -> None:
    error = declared_upload_error(request.headers.get("content-length"))
    if error is not None:
        raise error


async def _stream_upload(file: UploadFile, path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with path.open("xb") as target:
        while chunk := await file.read(_READ_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise KnowledgeRouteError(413, "KNOWLEDGE_UPLOAD_TOO_LARGE", "upload exceeds 10 MiB")
            target.write(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _validate_text_encoding(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        has_content = False
        try:
            with path.open("rb") as source:
                while chunk := source.read(_READ_CHUNK_BYTES):
                    text = decoder.decode(chunk)
                    if "\x00" in text:
                        raise UnicodeError("NUL byte is not valid text")
                    has_content = has_content or any(not character.isspace() for character in text)
                tail = decoder.decode(b"", final=True)
                if "\x00" in tail:
                    raise UnicodeError("NUL byte is not valid text")
                has_content = has_content or any(not character.isspace() for character in tail)
            if has_content:
                return encoding
        except UnicodeError:
            continue
    raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_ENCODING_INVALID", "file encoding is unsupported")


def _stable_source_id(*, namespace: str, uri: str, version: str) -> str:
    identity = f"{namespace}\n{uri}\n{version}".encode("utf-8")
    return f"ksrc_{hashlib.sha256(identity).hexdigest()[:20]}"


def operator_authorized(authorization: str | None, expected_token: str | bytes) -> bool:
    scheme, separator, credential = str(authorization or "").partition(" ")
    supplied = credential.encode("utf-8") if separator and scheme.lower() == "bearer" else b""
    expected = expected_token.encode("utf-8") if isinstance(expected_token, str) else expected_token
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def declared_upload_error(content_length: str | None) -> KnowledgeRouteError | None:
    if not content_length:
        return None
    try:
        declared = int(content_length)
    except ValueError:
        return KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_SIZE_INVALID", "Content-Length is invalid")
    if declared > MAX_UPLOAD_REQUEST_BYTES:
        return KnowledgeRouteError(413, "KNOWLEDGE_UPLOAD_TOO_LARGE", "upload exceeds 10 MiB")
    return None
