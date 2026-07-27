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


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + _MAX_MULTIPART_OVERHEAD_BYTES
_READ_CHUNK_BYTES = 64 * 1024
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_SUFFIXES = frozenset({".txt", ".md"})
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

    @router.get("/namespaces")
    def list_namespaces(request: Request) -> dict[str, object]:
        context(request)
        items = runtime.knowledge_service.store.list_namespace_summaries()
        current_hash = runtime.knowledge_service.embedding_config_hash
        for item in items:
            index_hash = str(item.get("index_embedding_config_hash") or "")
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

    @router.delete("/namespaces/{namespace}/sources/{source_id}")
    def delete_source(request: Request, namespace: str, source_id: str) -> dict[str, object]:
        context(request, namespace)
        if runtime.knowledge_service.store.get_source(namespace, source_id) is None:
            raise KnowledgeRouteError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "source was not found")
        return runtime.knowledge_service.delete_source(namespace=namespace, source_id=source_id)

    @router.post("/namespaces/{namespace}/reindex")
    def reindex(request: Request, namespace: str, source_id: str | None = None) -> dict[str, object]:
        context(request, namespace)
        result = runtime.knowledge_service.reindex(namespace=namespace, source_id=source_id)
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
    ) -> dict[str, object]:
        context(request, namespace)
        _validate_upload_metadata(title, license, provenance, calculation_scope, review_status)
        _validate_optional_metadata(
            uri=uri,
            version=version,
            corpus_type=corpus_type,
            school=school,
            method=method,
        )
        original_filename, suffix = _validate_filename(file.filename)
        _check_declared_size(request)
        upload_id = f"kupl_{uuid4().hex[:12]}"
        upload_directory = runtime.knowledge_service.jobs.staging_root / upload_id
        upload_directory.mkdir(mode=0o700)
        upload_directory.chmod(0o700)
        stored_name = f"source{suffix}"
        staged_path = upload_directory / stored_name
        try:
            size, digest = await _stream_upload(file, staged_path)
            encoding = _validate_text_encoding(staged_path)
            provided_version = str(version or "").strip()
            provided_uri = str(uri or "").strip()
            resolved_version = provided_version or f"sha256:{digest}"
            resolved_uri = provided_uri or (
                f"upload://{namespace}/{upload_id}/{quote(original_filename)}"
            )
            source_id = _stable_source_id(
                namespace=namespace,
                uri=(
                    provided_uri
                    or (f"content-sha256:{digest}" if provided_version else "")
                ),
                version=resolved_version,
            )
            metadata = {
                "license": str(license).strip(),
                "provenance": str(provenance).strip(),
                "calculation_scope": str(calculation_scope).strip(),
                "review_status": "reviewed",
                "original_filename": original_filename,
                "stored_filename": stored_name,
                "content_sha256": digest,
                "content_bytes": size,
                "encoding": encoding,
                "media_type": str(file.content_type or ""),
                "upload_id": upload_id,
            }
            if str(school or "").strip():
                metadata["school"] = str(school).strip()
            if str(method or "").strip():
                metadata["method"] = str(method).strip()
            if str(corpus_type or "").strip():
                metadata["corpus_type"] = str(corpus_type).strip()
            result = runtime.knowledge_service.ingest_file(
                namespace=namespace,
                file_path=str(staged_path),
                staged_file_path=f"{upload_id}/{stored_name}",
                source={
                    "source_id": source_id,
                    "title": str(title).strip(),
                    "kind": "markdown" if suffix == ".md" else "text",
                    "uri": resolved_uri,
                    "version": resolved_version,
                    "metadata": metadata,
                },
            )
            return {
                **result,
                "upload_id": upload_id,
                "source_id": source_id,
                "uri": resolved_uri,
                "version": resolved_version,
            }
        except BaseException:
            if upload_directory.exists():
                shutil.rmtree(upload_directory, ignore_errors=True)
            raise
        finally:
            await file.close()

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
    if str(review_status or "").strip() != "reviewed":
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_REVIEW_REQUIRED", "review_status must be reviewed")


def _validate_optional_metadata(**values: str | None) -> None:
    if any(len(str(value or "").strip()) > _METADATA_LIMITS[name] for name, value in values.items()):
        raise KnowledgeRouteError(422, "KNOWLEDGE_UPLOAD_METADATA_INVALID", "upload metadata exceeds its limit")


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
