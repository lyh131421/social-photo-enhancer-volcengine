from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import mimetypes
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union
from urllib import error, parse, request


HTTP_METHOD = "POST"
MINIO_UPLOAD_METHOD = "PUT"
VOLCENGINE_SUCCESS_CODE = 10000
VOLCENGINE_RETRYABLE_CODES = {50429, 50430, 50511, 50519}
VOLCENGINE_NON_RETRYABLE_CODES = {50411, 50412, 50413, 50512, 50520, 50521, 50522, 50500, 50501}
DEFAULT_MINIO_ENDPOINT = "http://huashidai1.com:9000"
DEFAULT_MINIO_PUBLIC_BASE_URL = "https://www.huashidai1.com/oss"
DEFAULT_MINIO_BUCKET = "skill"
DEFAULT_MINIO_REGION = "us-east-1"
DEFAULT_MINIO_SERVICE = "s3"
DEFAULT_MINIO_OBJECT_PREFIX = "input"
DEFAULT_SOURCE_URL_PREFIX = f"{DEFAULT_MINIO_PUBLIC_BASE_URL}/{DEFAULT_MINIO_BUCKET}/"
DEFAULT_DOWNLOAD_DIR = r"C:\Users\Administrator\Desktop\upload"

SCENE_ALIASES = {
    "portrait": "portrait",
    "selfie": "portrait",
    "person": "portrait",
    "people": "portrait",
    "cafe": "cafe",
    "coffee": "cafe",
    "restaurant": "cafe",
    "food": "food",
    "meal": "food",
    "travel": "travel",
    "trip": "travel",
    "street": "travel",
    "daily": "daily",
    "lifestyle": "daily",
    "home": "daily",
}

DEFECT_ALIASES = {
    "low light": "low-lighting",
    "dark": "low-lighting",
    "underexposed": "low-lighting",
    "lighting": "low-lighting",
    "noise": "noise",
    "grain": "noise",
    "blurry": "soft-focus",
    "blur": "soft-focus",
    "soft": "soft-focus",
    "clutter": "busy-background",
    "busy": "busy-background",
    "messy": "busy-background",
    "flat": "flat-color",
    "washed": "flat-color",
    "weak composition": "weak-composition",
    "composition": "weak-composition",
    "color cast": "color-cast",
    "cast": "color-cast",
}

STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "clear-portrait": {
        "scene_types": {"portrait"},
        "prompt_cues": [
            "clean and natural skin tone",
            "soft directional light",
            "realistic facial detail",
            "subtle depth separation",
            "premium portrait finish",
        ],
        "negative_focus": ["plastic skin", "reshaped face", "over-whitening"],
    },
    "warm-cafe": {
        "scene_types": {"cafe", "food"},
        "prompt_cues": [
            "warm ambient light",
            "controlled highlights",
            "tidy premium lifestyle composition",
            "appetizing realistic detail",
            "cozy editorial atmosphere",
        ],
        "negative_focus": ["extreme yellow cast", "fake food texture", "scene rewrite"],
    },
    "airy-travel": {
        "scene_types": {"travel"},
        "prompt_cues": [
            "airy transparent light",
            "crisp environmental detail",
            "natural sky tone",
            "gentle cinematic depth",
            "editorial travel atmosphere",
        ],
        "negative_focus": ["changed landmark", "dramatic fake sky", "over-processed contrast"],
    },
    "daily-atmosphere": {
        "scene_types": {"daily", "food", "cafe", "travel", "portrait"},
        "prompt_cues": [
            "balanced natural lighting uplift",
            "cleaner visual hierarchy",
            "premium color harmony",
            "realistic texture retention",
            "polished daily-life atmosphere",
        ],
        "negative_focus": ["heavy filter", "gimmicky effect", "strong scene rewrite"],
    },
}

BASE_NEGATIVE_CONSTRAINTS = [
    "plastic skin",
    "extra fingers",
    "extra limbs",
    "distorted face",
    "warped background geometry",
    "unrelated objects",
    "waxy texture",
    "excessive blur",
    "oversaturated colors",
]


@dataclass
class EnhanceInput:
    source_image: str
    user_goal: Optional[str] = None
    style_override: Optional[str] = None
    preserve_identity: bool = True
    num_outputs: int = 3

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EnhanceInput":
        source_image = data.get("source_image")
        if isinstance(source_image, Sequence) and not isinstance(source_image, (str, bytes)):
            raise ValueError("source_image must contain exactly one image, not a list.")
        normalized_source = _clean_optional_text(source_image)
        if not normalized_source:
            raise ValueError("source_image is required.")
        if not _is_supported_source_input(normalized_source):
            raise ValueError(
                "source_image must be either a skill public URL, an http/https image URL, or a readable local file path."
            )
        num_outputs = int(data.get("num_outputs", 3))
        if num_outputs <= 0:
            raise ValueError("num_outputs must be positive.")
        return cls(
            source_image=normalized_source,
            user_goal=_clean_optional_text(data.get("user_goal")),
            style_override=_clean_optional_text(data.get("style_override")),
            preserve_identity=bool(data.get("preserve_identity", True)),
            num_outputs=num_outputs,
        )


@dataclass
class ImageAnalysis:
    scene_type: str
    defects: List[str]
    must_keep: List[str]
    recommended_style: str


@dataclass
class PromptSpec:
    positive_prompt: str
    negative_prompt: str
    strength: float
    num_outputs: int
    selected_style: str


@dataclass
class JobHandle:
    job_id: str
    status_url: str
    provider_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    status: str
    images: List[Dict[str, Any]]
    error: Optional[str] = None
    provider_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QcReport:
    passed: bool
    issues: List[str]
    retry_recommended: bool


@dataclass
class EnhanceResult:
    selected_style: str
    final_prompt: Dict[str, Any]
    jimeng_request: Dict[str, Any]
    results: List[Dict[str, Any]]
    qc_report: QcReport
    provider_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["qc_report"] = asdict(self.qc_report)
        return payload


@dataclass
class PreparedSourceImage:
    original_source: str
    public_url: str
    source_kind: str
    object_key: Optional[str] = None
    uploaded_to_minio: bool = False


@dataclass
class MinioConfig:
    access_key: str
    secret_key: str
    endpoint: str = DEFAULT_MINIO_ENDPOINT
    bucket: str = DEFAULT_MINIO_BUCKET
    region: str = DEFAULT_MINIO_REGION
    service: str = DEFAULT_MINIO_SERVICE
    public_base_url: str = DEFAULT_MINIO_PUBLIC_BASE_URL
    object_prefix: str = DEFAULT_MINIO_OBJECT_PREFIX
    timeout_seconds: int = 30
    verify_public_url: bool = True

    @property
    def host(self) -> str:
        return parse.urlparse(self.endpoint).netloc

    @classmethod
    def from_env(cls) -> "MinioConfig":
        access_key = os.getenv("MINIO_ACCESS_KEY", "").strip()
        secret_key = os.getenv("MINIO_SECRET_KEY", "").strip()
        if not access_key:
            raise ValueError("MINIO_ACCESS_KEY is required when the source image must be uploaded to MinIO.")
        if not secret_key:
            raise ValueError("MINIO_SECRET_KEY is required when the source image must be uploaded to MinIO.")
        verify_public_url = os.getenv("MINIO_VERIFY_PUBLIC_URL", "true").strip().lower() not in {"0", "false", "no"}
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            endpoint=os.getenv("MINIO_ENDPOINT", DEFAULT_MINIO_ENDPOINT).strip().rstrip("/"),
            bucket=os.getenv("MINIO_BUCKET", DEFAULT_MINIO_BUCKET).strip() or DEFAULT_MINIO_BUCKET,
            region=os.getenv("MINIO_REGION", DEFAULT_MINIO_REGION).strip() or DEFAULT_MINIO_REGION,
            service=os.getenv("MINIO_SERVICE", DEFAULT_MINIO_SERVICE).strip() or DEFAULT_MINIO_SERVICE,
            public_base_url=os.getenv("MINIO_PUBLIC_BASE_URL", DEFAULT_MINIO_PUBLIC_BASE_URL).strip().rstrip("/"),
            object_prefix=os.getenv("MINIO_OBJECT_PREFIX", DEFAULT_MINIO_OBJECT_PREFIX).strip().strip("/"),
            timeout_seconds=int(os.getenv("MINIO_TIMEOUT_SECONDS", "30")),
            verify_public_url=verify_public_url,
        )


@dataclass
class JimengConfig:
    access_key: str
    secret_key: str
    endpoint: str = "https://visual.volcengineapi.com"
    region: str = "cn-north-1"
    service: str = "cv"
    req_key: str = "jimeng_t2i_v40"
    submit_action: str = "CVSync2AsyncSubmitTask"
    get_result_action: str = "CVSync2AsyncGetResult"
    version: str = "2022-08-31"
    timeout_seconds: int = 30

    @property
    def host(self) -> str:
        return parse.urlparse(self.endpoint).netloc

    @classmethod
    def from_env(cls) -> "JimengConfig":
        access_key = os.getenv("JIMENG_ACCESS_KEY", "").strip()
        secret_key = os.getenv("JIMENG_SECRET_KEY", "").strip()
        if not access_key:
            raise ValueError("JIMENG_ACCESS_KEY is required.")
        if not secret_key:
            raise ValueError("JIMENG_SECRET_KEY is required.")
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            endpoint=os.getenv("JIMENG_ENDPOINT", "https://visual.volcengineapi.com").strip().rstrip("/"),
            region=os.getenv("JIMENG_REGION", "cn-north-1").strip(),
            service=os.getenv("JIMENG_SERVICE", "cv").strip(),
            req_key=os.getenv("JIMENG_REQ_KEY", "jimeng_t2i_v40").strip() or "jimeng_t2i_v40",
            submit_action=os.getenv("JIMENG_SUBMIT_ACTION", "CVSync2AsyncSubmitTask").strip(),
            get_result_action=os.getenv("JIMENG_GET_RESULT_ACTION", "CVSync2AsyncGetResult").strip(),
            version=os.getenv("JIMENG_API_VERSION", "2022-08-31").strip(),
            timeout_seconds=int(os.getenv("JIMENG_TIMEOUT_SECONDS", "30")),
        )


class JimengProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        request_id: Optional[str] = None,
        provider_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.provider_meta = provider_meta or {}

    @property
    def retryable(self) -> bool:
        return is_retryable_provider_code(self.code)

    @classmethod
    def from_response(cls, response: Mapping[str, Any], http_status: Optional[int] = None) -> "JimengProviderError":
        provider_meta = response_meta(response)
        if http_status is not None:
            provider_meta["http_status"] = http_status
        message = str(response.get("message") or response.get("error") or "Jimeng request failed.")
        return cls(
            message=message,
            code=_coerce_int(response.get("code") or response.get("status")),
            request_id=_clean_optional_text(response.get("request_id")),
            provider_meta=provider_meta,
        )

    def __str__(self) -> str:
        if self.code is None:
            return super().__str__()
        return f"{super().__str__()} (code={self.code})"


class ResultDownloadError(RuntimeError):
    pass


class MinioUploadError(RuntimeError):
    pass


Transport = Callable[[str, str, Dict[str, str], Optional[str], int], Dict[str, Any]]


class JimengAdapter:
    def __init__(
        self,
        config: Optional[JimengConfig] = None,
        transport: Optional[Transport] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
    ) -> None:
        self.config = config or JimengConfig.from_env()
        self.transport = transport or self._default_transport
        self.clock = clock or datetime.datetime.utcnow

    def submit(self, provider_request: Mapping[str, Any]) -> JobHandle:
        query = format_query({"Action": self.config.submit_action, "Version": self.config.version})
        payload = self._provider_payload(provider_request)
        body = compact_json(payload)
        data = self.transport(
            HTTP_METHOD,
            self._request_url(query),
            build_v4_headers(self.config, query, body, current_time=self.clock()),
            body,
            self.config.timeout_seconds,
        )
        self._ensure_success_response(data)
        response_data = _as_mapping(data.get("data"))
        task_id = _clean_optional_text(response_data.get("task_id"))
        if not task_id:
            raise JimengProviderError(
                message="Jimeng submit succeeded without task_id.",
                code=VOLCENGINE_SUCCESS_CODE,
                request_id=_clean_optional_text(data.get("request_id")),
                provider_meta=response_meta(data),
            )
        return JobHandle(
            job_id=task_id,
            status_url=self._request_url(format_query({"Action": self.config.get_result_action, "Version": self.config.version})),
            provider_meta={**response_meta(data), "task_id": task_id},
        )

    def poll(
        self,
        handle: JobHandle,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: int = 120,
    ) -> ProviderResult:
        query = format_query({"Action": self.config.get_result_action, "Version": self.config.version})
        deadline = time.time() + timeout_seconds
        last_meta: Dict[str, Any] = {}
        while time.time() < deadline:
            req_json = compact_json({"return_url": True})
            body = compact_json(
                {
                    "req_key": self.config.req_key,
                    "task_id": handle.job_id,
                    "req_json": req_json,
                }
            )
            data = self.transport(
                HTTP_METHOD,
                self._request_url(query),
                build_v4_headers(self.config, query, body, current_time=self.clock()),
                body,
                self.config.timeout_seconds,
            )
            last_meta = response_meta(data)
            if _coerce_int(data.get("code")) != VOLCENGINE_SUCCESS_CODE:
                provider_error = JimengProviderError.from_response(data)
                return ProviderResult(
                    status="failed",
                    images=[],
                    error=str(provider_error),
                    provider_meta={**provider_error.provider_meta, "retryable": provider_error.retryable, "task_id": handle.job_id},
                )

            response_data = _as_mapping(data.get("data"))
            provider_status = _clean_optional_text(response_data.get("status")) or "unknown"
            normalized_status = normalize_provider_status(provider_status)

            if normalized_status == "succeeded":
                images = extract_result_images(response_data)
                if not images:
                    return ProviderResult(
                        status="failed",
                        images=[],
                        error="Jimeng task finished without image outputs.",
                        provider_meta={**last_meta, "provider_status": provider_status, "task_id": handle.job_id},
                    )
                return ProviderResult(
                    status="succeeded",
                    images=images,
                    provider_meta={**last_meta, "provider_status": provider_status, "task_id": handle.job_id},
                )

            if normalized_status == "failed":
                return ProviderResult(
                    status="failed",
                    images=[],
                    error=f"Jimeng task ended with status {provider_status}.",
                    provider_meta={**last_meta, "provider_status": provider_status, "task_id": handle.job_id},
                )

            time.sleep(poll_interval_seconds)

        return ProviderResult(
            status="failed",
            images=[],
            error="Jimeng job polling timed out.",
            provider_meta={**last_meta, "timeout_seconds": timeout_seconds, "task_id": handle.job_id, "retryable": True},
        )

    def _provider_payload(self, provider_request: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "req_key": provider_request["req_key"],
            "image_urls": provider_request["image_urls"],
            "prompt": provider_request["prompt"],
            "scale": provider_request["scale"],
        }

    def _request_url(self, query: str) -> str:
        return f"{self.config.endpoint}?{query}"

    @staticmethod
    def _ensure_success_response(response: Mapping[str, Any]) -> None:
        if _coerce_int(response.get("code")) != VOLCENGINE_SUCCESS_CODE:
            raise JimengProviderError.from_response(response)

    @staticmethod
    def _default_transport(
        method: str,
        url: str,
        headers: Dict[str, str],
        payload: Optional[str],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        body = None if payload is None else payload.encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError as decode_error:
                raise RuntimeError(f"Jimeng HTTP error {exc.code}: {raw}") from decode_error
            raise JimengProviderError.from_response(parsed, http_status=exc.code) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Jimeng network error: {exc.reason}") from exc
        if not raw:
            return {}
        return json.loads(raw)


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = sign(secret_key.encode("utf-8"), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    return sign(k_service, "request")


def format_query(parameters: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in sorted(parameters):
        parts.append(
            f"{parse.quote(str(key), safe='-_.~')}={parse.quote(str(parameters[key]), safe='-_.~')}"
        )
    return "&".join(parts)


def build_v4_headers(
    config: JimengConfig,
    query_string: str,
    request_body: str,
    current_time: Optional[datetime.datetime] = None,
) -> Dict[str, str]:
    now = current_time or datetime.datetime.utcnow()
    if now.tzinfo is not None:
        now = now.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    current_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(request_body.encode("utf-8")).hexdigest()
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_headers = (
        "content-type:application/json\n"
        f"host:{config.host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{current_date}\n"
    )
    canonical_request = (
        f"{HTTP_METHOD}\n"
        "/\n"
        f"{query_string}\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{payload_hash}"
    )
    credential_scope = f"{date_stamp}/{config.region}/{config.service}/request"
    string_to_sign = (
        "HMAC-SHA256\n"
        f"{current_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signing_key = get_signature_key(config.secret_key, date_stamp, config.region, config.service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "HMAC-SHA256 "
        f"Credential={config.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    return {
        "Content-Type": "application/json",
        "X-Date": current_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }


def build_minio_v4_headers(
    config: MinioConfig,
    canonical_uri: str,
    payload: bytes,
    content_type: str,
    current_time: Optional[datetime.datetime] = None,
) -> Dict[str, str]:
    now = current_time or datetime.datetime.utcnow()
    if now.tzinfo is not None:
        now = now.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    current_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{config.host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{current_date}\n"
    )
    canonical_request = (
        f"{MINIO_UPLOAD_METHOD}\n"
        f"{canonical_uri}\n"
        "\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{payload_hash}"
    )
    credential_scope = f"{date_stamp}/{config.region}/{config.service}/aws4_request"
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{current_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signing_key = get_aws_signature_key(config.secret_key, date_stamp, config.region, config.service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={config.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    return {
        "Content-Type": content_type,
        "X-Amz-Date": current_date,
        "X-Amz-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }


def prepare_source_image(
    source_image: str,
    config: Optional[MinioConfig] = None,
    current_time: Optional[datetime.datetime] = None,
) -> PreparedSourceImage:
    normalized_source = source_image.strip()
    if _is_public_source_url(normalized_source):
        return PreparedSourceImage(
            original_source=normalized_source,
            public_url=normalized_source,
            source_kind="public-url",
            uploaded_to_minio=False,
        )

    active_config = config or MinioConfig.from_env()
    source_payload = load_source_payload(normalized_source)
    object_key = build_minio_object_key(
        source_payload["filename"],
        current_time=current_time,
        object_prefix=active_config.object_prefix,
    )
    upload_bytes_to_minio(
        source_payload["content"],
        object_key=object_key,
        content_type=source_payload["content_type"],
        config=active_config,
        current_time=current_time,
    )
    public_url = build_public_source_url(object_key, public_base_url=active_config.public_base_url, bucket=active_config.bucket)
    if active_config.verify_public_url:
        verify_public_image_url(public_url, timeout_seconds=active_config.timeout_seconds)
    return PreparedSourceImage(
        original_source=normalized_source,
        public_url=public_url,
        source_kind=source_payload["source_kind"],
        object_key=object_key,
        uploaded_to_minio=True,
    )


def load_source_payload(source_image: str) -> Dict[str, Any]:
    if _is_web_url(source_image):
        return _download_source_payload(source_image)
    source_path = Path(source_image).expanduser()
    if not source_path.is_file():
        raise ValueError(f"source_image local file does not exist: {source_image}")
    try:
        content = source_path.read_bytes()
    except OSError as exc:
        raise MinioUploadError(f"Failed to read source image from {source_path}: {exc}") from exc
    filename = source_path.name
    content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
    return {
        "content": content,
        "content_type": content_type,
        "filename": filename,
        "source_kind": "local-file",
    }


def upload_bytes_to_minio(
    payload: bytes,
    object_key: str,
    content_type: str,
    config: Optional[MinioConfig] = None,
    current_time: Optional[datetime.datetime] = None,
) -> str:
    active_config = config or MinioConfig.from_env()
    canonical_uri = build_minio_canonical_uri(active_config.bucket, object_key)
    request_url = active_config.endpoint + canonical_uri
    headers = build_minio_v4_headers(
        active_config,
        canonical_uri=canonical_uri,
        payload=payload,
        content_type=content_type,
        current_time=current_time,
    )
    req = request.Request(url=request_url, data=payload, headers=headers, method=MINIO_UPLOAD_METHOD)
    try:
        with request.urlopen(req, timeout=active_config.timeout_seconds) as response:
            status_code = getattr(response, "status", 200)
            if status_code >= 300:
                raise MinioUploadError(f"MinIO upload failed with HTTP {status_code} for {object_key}.")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MinioUploadError(f"MinIO upload failed with HTTP {exc.code} for {object_key}: {body}") from exc
    except error.URLError as exc:
        raise MinioUploadError(f"MinIO upload network error for {object_key}: {exc.reason}") from exc
    return build_public_source_url(object_key, public_base_url=active_config.public_base_url, bucket=active_config.bucket)


def verify_public_image_url(public_url: str, timeout_seconds: int = 30) -> None:
    head_request = request.Request(public_url, method="HEAD")
    try:
        with request.urlopen(head_request, timeout=timeout_seconds):
            return
    except error.HTTPError as exc:
        if exc.code not in {403, 405}:
            raise MinioUploadError(f"Uploaded image is not publicly reachable at {public_url}: HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise MinioUploadError(f"Uploaded image public URL verification failed for {public_url}: {exc.reason}") from exc

    try:
        with request.urlopen(public_url, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) >= 300:
                raise MinioUploadError(f"Uploaded image is not publicly reachable at {public_url}.")
    except error.HTTPError as exc:
        raise MinioUploadError(f"Uploaded image is not publicly reachable at {public_url}: HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise MinioUploadError(f"Uploaded image public URL verification failed for {public_url}: {exc.reason}") from exc


def build_minio_object_key(
    filename: str,
    current_time: Optional[datetime.datetime] = None,
    object_prefix: Optional[str] = None,
) -> str:
    timestamp = current_time or datetime.datetime.now()
    extension = _normalized_extension(filename) or ".jpg"
    prefix = (object_prefix or resolve_minio_object_prefix()).strip("/")
    dated_prefix = timestamp.strftime("%Y/%m/%d")
    parts = [part for part in [prefix, dated_prefix, f"{uuid.uuid4().hex}{extension}"] if part]
    return "/".join(parts)


def build_minio_canonical_uri(bucket: str, object_key: str) -> str:
    path_parts = [bucket.strip("/")] + [segment for segment in object_key.strip("/").split("/") if segment]
    return "/" + "/".join(parse.quote(segment, safe="-_.~") for segment in path_parts)


def get_aws_signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    return sign(k_service, "aws4_request")


def enhance_social_photo(
    input_data: Union[EnhanceInput, Mapping[str, Any]],
    adapter: Optional[JimengAdapter] = None,
    raw_analysis: Optional[Union[str, Mapping[str, Any], ImageAnalysis]] = None,
    poll_interval_seconds: float = 2.0,
    timeout_seconds: int = 120,
    max_retries: int = 1,
) -> EnhanceResult:
    enhance_input = input_data if isinstance(input_data, EnhanceInput) else EnhanceInput.from_mapping(input_data)
    prepared_source = prepare_source_image(enhance_input.source_image)
    prepared_input = replace(enhance_input, source_image=prepared_source.public_url)
    analysis = normalize_analysis(raw_analysis or analyze_source_image(enhance_input.source_image), enhance_input.style_override)
    prompt_spec = build_img2img_prompt(
        analysis=analysis,
        user_goal=prepared_input.user_goal,
        style_override=prepared_input.style_override,
        preserve_identity=prepared_input.preserve_identity,
        num_outputs=prepared_input.num_outputs,
    )
    provider_request = build_jimeng_request(prepared_input, prompt_spec, prepared_source=prepared_source)
    active_adapter = adapter or JimengAdapter()

    attempt = 0
    last_request = provider_request
    provider_meta: Dict[str, Any] = {"attempts": [], "source_image": asdict(prepared_source)}
    final_result: Optional[ProviderResult] = None
    final_qc: Optional[QcReport] = None

    while attempt <= max_retries:
        job_id: Optional[str] = None
        try:
            handle = submit_jimeng_job(last_request, active_adapter)
            job_id = handle.job_id
            polled = poll_jimeng_job(handle, active_adapter, poll_interval_seconds, timeout_seconds)
            if polled.status == "succeeded":
                task_id = _clean_optional_text(polled.provider_meta.get("task_id")) or job_id or "unknown-task"
                polled.images = download_result_images(polled.images, task_id=task_id)
        except JimengProviderError as exc:
            polled = ProviderResult(status="failed", images=[], error=str(exc), provider_meta=exc.provider_meta)
        except ResultDownloadError as exc:
            polled = ProviderResult(
                status="failed",
                images=[],
                error=str(exc),
                provider_meta={"retryable": False, "task_id": job_id},
            )
        except RuntimeError as exc:
            polled = ProviderResult(status="failed", images=[], error=str(exc), provider_meta={"retryable": True})

        qc_report = run_quality_check(prepared_input.source_image, polled, analysis=analysis)
        provider_meta["attempts"].append(
            {
                "attempt": attempt + 1,
                "job_id": job_id,
                "status": polled.status,
                "error": polled.error,
                "provider_meta": polled.provider_meta,
                "qc_report": asdict(qc_report),
            }
        )
        final_result = polled
        final_qc = qc_report
        if polled.status == "succeeded" and qc_report.passed:
            break
        if attempt >= max_retries or not qc_report.retry_recommended:
            break
        attempt += 1
        prompt_spec = tighten_prompt(prompt_spec)
        last_request = build_jimeng_request(prepared_input, prompt_spec, prepared_source=prepared_source)

    if final_result is None or final_qc is None:
        raise RuntimeError("Enhancement flow ended without a provider result.")

    enhance_result = EnhanceResult(
        selected_style=prompt_spec.selected_style,
        final_prompt=asdict(prompt_spec),
        jimeng_request=last_request,
        results=final_result.images,
        qc_report=final_qc,
        provider_meta={**provider_meta, **final_result.provider_meta},
    )

    write_result_manifest(enhance_result, prepared_source)

    return enhance_result


DEFAULT_RESULT_MANIFEST_PATH = os.path.join(DEFAULT_DOWNLOAD_DIR, "last_result.json")


def write_result_manifest(
    result: EnhanceResult,
    prepared_source: Optional[PreparedSourceImage] = None,
    manifest_path: Optional[str] = None,
) -> str:
    """Write a fixed-location JSON manifest so other skills can consume the results.

    The manifest is written to ``Desktop\\upload\\last_result.json`` by default.
    Returns the path written to.
    """
    target = manifest_path or os.getenv("JIMENG_RESULT_MANIFEST_PATH", "").strip() or DEFAULT_RESULT_MANIFEST_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)

    task_id = _clean_optional_text(result.provider_meta.get("task_id")) or "unknown"
    manifest = {
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
        "status": "succeeded" if result.qc_report.passed else "failed",
        "task_id": task_id,
        "source_image": prepared_source.public_url if prepared_source else None,
        "outputs": [
            {
                "url": img.get("url"),
                "local_path": img.get("local_path"),
            }
            for img in result.results
            if img.get("url") or img.get("local_path")
        ],
        "selected_style": result.selected_style,
        "qc_passed": result.qc_report.passed,
    }

    try:
        Path(target).write_text(dumps_json(manifest), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to write result manifest to {target}: {exc}") from exc
    return target


def analyze_source_image(image: Union[str, Mapping[str, Any]]) -> ImageAnalysis:
    if isinstance(image, Mapping):
        tags = " ".join(str(item) for item in _ensure_list(image.get("tags")))
        scene_hint = str(image.get("scene_type") or image.get("category") or tags)
        scene_type = infer_scene_from_text(scene_hint)
        defects = normalize_defects(image.get("defects"))
        must_keep = normalize_must_keep(image.get("must_keep"))
    else:
        scene_type = infer_scene_from_text(image)
        defects = infer_defects_from_text(image)
        must_keep = ["subject identity", "core scene semantics"]
    if not defects:
        defects = ["low-lighting", "flat-color", "weak-composition"]
    if "subject identity" not in must_keep:
        must_keep.insert(0, "subject identity")
    if "core scene semantics" not in must_keep:
        must_keep.append("core scene semantics")
    return ImageAnalysis(
        scene_type=scene_type,
        defects=defects,
        must_keep=must_keep,
        recommended_style=recommend_style(scene_type),
    )


def normalize_analysis(
    raw_analysis: Union[str, Mapping[str, Any], ImageAnalysis],
    style_override: Optional[str] = None,
) -> ImageAnalysis:
    if isinstance(raw_analysis, ImageAnalysis):
        scene_type = normalize_scene_type(raw_analysis.scene_type)
        defects = normalize_defects(raw_analysis.defects)
        must_keep = normalize_must_keep(raw_analysis.must_keep)
        recommended_style = normalize_style(style_override) or normalize_style(raw_analysis.recommended_style) or recommend_style(scene_type)
        return ImageAnalysis(scene_type=scene_type, defects=defects, must_keep=must_keep, recommended_style=recommended_style)
    base = analyze_source_image(raw_analysis)
    if style_override:
        base.recommended_style = normalize_style(style_override) or base.recommended_style
    return base


def build_img2img_prompt(
    analysis: Union[ImageAnalysis, Mapping[str, Any]],
    user_goal: Optional[str] = None,
    style_override: Optional[str] = None,
    preserve_identity: bool = True,
    num_outputs: int = 3,
) -> PromptSpec:
    normalized = normalize_analysis(analysis, style_override)
    selected_style = normalize_style(style_override) or normalized.recommended_style
    preset = STYLE_PRESETS[selected_style]

    preserve_line = "Preserve the same subject identity, key outfit or object, and the core scene semantics."
    if not preserve_identity:
        preserve_line = "Keep the main subject recognizable and retain the core scene semantics."

    goal_line = f"Honor the user's target intent: {user_goal.strip()}." if user_goal and user_goal.strip() else ""
    candidate_line = ""
    if num_outputs > 1:
        candidate_line = f"If supported by the model, generate {num_outputs} polished candidate variations in one batch while keeping the same subject and scene."
    negative_terms = list(dict.fromkeys(list(BASE_NEGATIVE_CONSTRAINTS) + list(preset["negative_focus"])))
    avoid_line = "Avoid " + ", ".join(negative_terms) + "."

    positive_parts = [
        preserve_line,
        "Keep: " + ", ".join(normalized.must_keep) + ".",
        "Fix the source issues: " + ", ".join(normalized.defects) + ".",
        "Upgrade the image into a polished, high-quality social-media photo with better lighting, cleaner composition, clearer depth, more premium color harmony, and a believable finished-photo feel.",
        "Apply these style cues: " + ", ".join(preset["prompt_cues"]) + ".",
        goal_line,
        candidate_line,
        avoid_line,
        "Keep the result realistic, faithful to the original camera perspective, and suitable for a premium social-media post.",
    ]
    positive_prompt = " ".join(part for part in positive_parts if part)
    negative_prompt = ", ".join(negative_terms)

    strength = 0.35 if preserve_identity else 0.5
    if "busy-background" in normalized.defects or "weak-composition" in normalized.defects:
        strength += 0.05
    strength = round(min(strength, 0.6), 2)

    return PromptSpec(
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        strength=strength,
        num_outputs=num_outputs,
        selected_style=selected_style,
    )


def build_jimeng_request(
    enhance_input: Union[EnhanceInput, Mapping[str, Any]],
    prompt_spec: Union[PromptSpec, Mapping[str, Any]],
    prepared_source: Optional[PreparedSourceImage] = None,
) -> Dict[str, Any]:
    input_obj = enhance_input if isinstance(enhance_input, EnhanceInput) else EnhanceInput.from_mapping(enhance_input)
    prompt_obj = prompt_spec if isinstance(prompt_spec, PromptSpec) else PromptSpec(**prompt_spec)
    source_details = prepared_source or prepare_source_image(input_obj.source_image)
    return {
        "req_key": resolve_req_key(),
        "image_urls": [source_details.public_url],
        "prompt": prompt_obj.positive_prompt,
        "scale": prompt_obj.strength,
        "metadata": {
            "style_override": input_obj.style_override,
            "user_goal": input_obj.user_goal,
            "preserve_identity": input_obj.preserve_identity,
            "desired_num_outputs": prompt_obj.num_outputs,
            "negative_prompt": prompt_obj.negative_prompt,
            "flow_version": "volcengine-v1-single-image",
            "source_origin": source_details.source_kind,
            "source_public_url": source_details.public_url,
            "source_object_key": source_details.object_key,
            "source_uploaded_to_minio": source_details.uploaded_to_minio,
        },
    }


def submit_jimeng_job(provider_request: Mapping[str, Any], adapter: Optional[JimengAdapter] = None) -> JobHandle:
    return (adapter or JimengAdapter()).submit(provider_request)


def poll_jimeng_job(
    handle: JobHandle,
    adapter: Optional[JimengAdapter] = None,
    poll_interval_seconds: float = 2.0,
    timeout_seconds: int = 120,
) -> ProviderResult:
    return (adapter or JimengAdapter()).poll(
        handle,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


def run_quality_check(
    source: Union[str, Mapping[str, Any]],
    result: ProviderResult,
    analysis: Optional[ImageAnalysis] = None,
) -> QcReport:
    issues: List[str] = []
    if result.status != "succeeded":
        issues.append(result.error or "Provider did not return a successful result.")
        return QcReport(
            passed=False,
            issues=issues,
            retry_recommended=is_retryable_provider_failure(result),
        )

    if not result.images:
        issues.append("Provider returned no images.")
        return QcReport(passed=False, issues=issues, retry_recommended=True)

    for index, image in enumerate(result.images, start=1):
        has_url = bool(image.get("url") or image.get("image_url") or image.get("uri"))
        has_base64 = bool(image.get("base64"))
        if not has_url and not has_base64:
            issues.append(f"Result {index} is missing image output data.")
        for warning in _ensure_list(image.get("issues")):
            issues.append(f"Result {index}: {warning}")
        subject_consistency = image.get("subject_consistency")
        if isinstance(subject_consistency, (int, float)) and subject_consistency < 0.7:
            issues.append(f"Result {index} has low subject consistency.")
        artifact_score = image.get("artifact_score")
        if isinstance(artifact_score, (int, float)) and artifact_score > 0.4:
            issues.append(f"Result {index} shows elevated artifact risk.")

    if analysis and analysis.scene_type == "portrait":
        for index, image in enumerate(result.images, start=1):
            if image.get("face_distortion"):
                issues.append(f"Result {index} shows face distortion.")

    retry_recommended = any(
        phrase in issue.lower()
        for issue in issues
        for phrase in ["consistency", "artifact", "missing", "distortion"]
    )
    return QcReport(passed=not issues, issues=issues, retry_recommended=retry_recommended)


def tighten_prompt(prompt_spec: PromptSpec) -> PromptSpec:
    reinforcement = (
        " Stay even closer to the original photo, keep the same face and same body proportions, "
        "and reduce any stylistic deviation that changes the source identity or scene."
    )
    return PromptSpec(
        positive_prompt=prompt_spec.positive_prompt + reinforcement,
        negative_prompt=prompt_spec.negative_prompt,
        strength=max(round(prompt_spec.strength - 0.1, 2), 0.2),
        num_outputs=prompt_spec.num_outputs,
        selected_style=prompt_spec.selected_style,
    )


def infer_scene_from_text(text: str) -> str:
    lowered = (text or "").lower()
    for token, normalized in SCENE_ALIASES.items():
        if token in lowered:
            return normalized
    return "daily"


def infer_defects_from_text(text: str) -> List[str]:
    lowered = (text or "").lower()
    defects = [normalized for token, normalized in DEFECT_ALIASES.items() if token in lowered]
    return list(dict.fromkeys(defects))


def normalize_scene_type(scene_type: str) -> str:
    return SCENE_ALIASES.get((scene_type or "").strip().lower(), "daily")


def normalize_defects(raw_defects: Optional[Union[str, Iterable[Any]]]) -> List[str]:
    if raw_defects is None:
        return []
    items = [raw_defects] if isinstance(raw_defects, str) else list(raw_defects)
    normalized: List[str] = []
    for item in items:
        token = str(item).strip().lower()
        if not token:
            continue
        normalized.append(DEFECT_ALIASES.get(token, token.replace(" ", "-")))
    return list(dict.fromkeys(normalized))


def normalize_must_keep(raw_must_keep: Optional[Union[str, Iterable[Any]]]) -> List[str]:
    if raw_must_keep is None:
        return ["subject identity", "core scene semantics"]
    items = [raw_must_keep] if isinstance(raw_must_keep, str) else list(raw_must_keep)
    normalized = [str(item).strip() for item in items if str(item).strip()]
    return list(dict.fromkeys(normalized)) or ["subject identity", "core scene semantics"]


def normalize_style(style_name: Optional[str]) -> Optional[str]:
    if not style_name:
        return None
    lowered = style_name.strip().lower()
    alias_map = {
        "portrait": "clear-portrait",
        "clear portrait": "clear-portrait",
        "cafe": "warm-cafe",
        "warm cafe": "warm-cafe",
        "travel": "airy-travel",
        "airy travel": "airy-travel",
        "daily": "daily-atmosphere",
        "daily atmosphere": "daily-atmosphere",
        "xiaohongshu": "daily-atmosphere",
        "instagram": "daily-atmosphere",
    }
    candidate = alias_map.get(lowered, lowered)
    return candidate if candidate in STYLE_PRESETS else None


def recommend_style(scene_type: str) -> str:
    scene = normalize_scene_type(scene_type)
    for style_name, preset in STYLE_PRESETS.items():
        if style_name != "daily-atmosphere" and scene in preset["scene_types"]:
            return style_name
    return "daily-atmosphere"


def normalize_provider_status(status: str) -> str:
    lowered = status.strip().lower()
    if lowered in {"queued", "pending", "submitted", "in_queue"}:
        return "queued"
    if lowered in {"running", "processing", "in_progress", "generating"}:
        return "running"
    if lowered in {"succeeded", "success", "completed", "done"}:
        return "succeeded"
    if lowered in {"failed", "error", "cancelled", "canceled", "not_found", "expired"}:
        return "failed"
    return lowered or "unknown"


def is_retryable_provider_code(code: Optional[int]) -> bool:
    if code is None:
        return False
    if code in VOLCENGINE_RETRYABLE_CODES:
        return True
    if code in VOLCENGINE_NON_RETRYABLE_CODES:
        return False
    return False


def is_retryable_provider_failure(result: ProviderResult) -> bool:
    if result.provider_meta.get("retryable") is True:
        return True
    code = _coerce_int(result.provider_meta.get("code"))
    if is_retryable_provider_code(code):
        return True
    lowered_error = (result.error or "").lower()
    return "timed out" in lowered_error or "network" in lowered_error


def extract_result_images(response_data: Mapping[str, Any]) -> List[Dict[str, Any]]:
    images: List[Dict[str, Any]] = []
    for url in _ensure_list(response_data.get("image_urls")):
        value = _clean_optional_text(url)
        if value:
            images.append({"url": value})
    if images:
        return images
    for item in _ensure_list(response_data.get("binary_data_base64")):
        value = _clean_optional_text(item)
        if value:
            images.append({"base64": value})
    return images


def response_meta(response: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "code": _coerce_int(response.get("code") or response.get("status")),
        "message": _clean_optional_text(response.get("message")),
        "request_id": _clean_optional_text(response.get("request_id")),
        "time_elapsed": _clean_optional_text(response.get("time_elapsed")),
    }


def build_public_source_url(
    object_key: str,
    public_base_url: Optional[str] = None,
    bucket: Optional[str] = None,
) -> str:
    key = object_key.strip().lstrip("/")
    if not key:
        raise ValueError("object_key must be non-empty.")
    prefix = resolve_source_url_prefix(public_base_url=public_base_url, bucket=bucket)
    return prefix + key


def resolve_req_key() -> str:
    return os.getenv("JIMENG_REQ_KEY", "jimeng_t2i_v40").strip() or "jimeng_t2i_v40"


def resolve_source_url_prefix(
    public_base_url: Optional[str] = None,
    bucket: Optional[str] = None,
) -> str:
    explicit_prefix = os.getenv("JIMENG_SOURCE_URL_PREFIX", "").strip()
    if explicit_prefix:
        return explicit_prefix.rstrip("/") + "/"
    base_url = (public_base_url or resolve_minio_public_base_url()).rstrip("/")
    active_bucket = (bucket or resolve_minio_bucket()).strip("/")
    return f"{base_url}/{active_bucket}/"


def resolve_minio_bucket() -> str:
    return os.getenv("MINIO_BUCKET", DEFAULT_MINIO_BUCKET).strip() or DEFAULT_MINIO_BUCKET


def resolve_minio_public_base_url() -> str:
    return os.getenv("MINIO_PUBLIC_BASE_URL", DEFAULT_MINIO_PUBLIC_BASE_URL).strip().rstrip("/")


def resolve_minio_object_prefix() -> str:
    return os.getenv("MINIO_OBJECT_PREFIX", DEFAULT_MINIO_OBJECT_PREFIX).strip().strip("/")


def resolve_download_dir() -> str:
    return os.getenv("JIMENG_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR).strip() or DEFAULT_DOWNLOAD_DIR


def download_result_images(
    images: Sequence[Mapping[str, Any]],
    task_id: str,
    download_dir: Optional[str] = None,
    fetcher: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    target_dir = download_dir or resolve_download_dir()
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        raise ResultDownloadError(f"Failed to create result directory {target_dir}: {exc}") from exc

    active_fetcher = fetcher or request.urlopen
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    localized: List[Dict[str, Any]] = []
    safe_task_id = _sanitize_filename_fragment(task_id or "unknown-task")

    for index, image in enumerate(images, start=1):
        image_copy = dict(image)
        if image_copy.get("url"):
            local_path = _download_remote_image(
                url=str(image_copy["url"]),
                target_dir=target_dir,
                file_stem=f"{timestamp}_{safe_task_id}_{index}",
                fetcher=active_fetcher,
            )
        elif image_copy.get("base64"):
            local_path = _write_base64_image(
                encoded=str(image_copy["base64"]),
                target_dir=target_dir,
                file_stem=f"{timestamp}_{safe_task_id}_{index}",
            )
        else:
            raise ResultDownloadError(f"Result {index} is missing both url and base64 output.")
        image_copy["local_path"] = local_path
        localized.append(image_copy)

    return localized


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _is_supported_source_input(value: str) -> bool:
    return _is_public_source_url(value) or _is_web_url(value) or Path(value).expanduser().is_file()


def _is_public_source_url(value: str) -> bool:
    return _is_web_url(value) and value.strip().startswith(resolve_source_url_prefix())


def _is_web_url(value: str) -> bool:
    parsed = parse.urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return True


def _download_source_payload(source_url: str) -> Dict[str, Any]:
    try:
        with request.urlopen(source_url, timeout=60) as response:
            content = response.read()
            content_type = ""
            headers = getattr(response, "headers", None)
            if headers is not None:
                if hasattr(headers, "get_content_type"):
                    content_type = headers.get_content_type()
                else:
                    content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip()
    except error.HTTPError as exc:
        raise MinioUploadError(f"Failed to fetch source image from {source_url}: HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise MinioUploadError(f"Failed to fetch source image from {source_url}: {exc.reason}") from exc
    filename = os.path.basename(parse.urlparse(source_url).path) or f"source{_infer_extension_from_content_type(content_type) or '.jpg'}"
    return {
        "content": content,
        "content_type": content_type or "image/jpeg",
        "filename": filename,
        "source_kind": "remote-url",
    }


def _download_remote_image(
    url: str,
    target_dir: str,
    file_stem: str,
    fetcher: Callable[..., Any],
) -> str:
    try:
        with fetcher(url, timeout=60) as response:
            content = response.read()
            content_type = ""
            headers = getattr(response, "headers", None)
            if headers is not None:
                if hasattr(headers, "get_content_type"):
                    content_type = headers.get_content_type()
                else:
                    content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip()
    except Exception as exc:  # noqa: BLE001
        raise ResultDownloadError(f"Failed to download generated image from {url}: {exc}") from exc

    extension = _infer_extension_from_url(url) or _infer_extension_from_content_type(content_type) or ".png"
    local_path = os.path.join(target_dir, file_stem + extension)
    try:
        with open(local_path, "wb") as file_obj:
            file_obj.write(content)
    except OSError as exc:
        raise ResultDownloadError(f"Failed to write generated image to {local_path}: {exc}") from exc
    return local_path


def _write_base64_image(encoded: str, target_dir: str, file_stem: str) -> str:
    try:
        content = base64.b64decode(encoded)
    except Exception as exc:  # noqa: BLE001
        raise ResultDownloadError(f"Failed to decode generated base64 image: {exc}") from exc
    local_path = os.path.join(target_dir, file_stem + ".png")
    try:
        with open(local_path, "wb") as file_obj:
            file_obj.write(content)
    except OSError as exc:
        raise ResultDownloadError(f"Failed to write generated image to {local_path}: {exc}") from exc
    return local_path


def _infer_extension_from_url(url: str) -> str:
    path = parse.urlparse(url).path
    return _normalized_extension(path)


def _infer_extension_from_content_type(content_type: str) -> str:
    if not content_type:
        return ""
    guessed = mimetypes.guess_extension(content_type)
    return guessed or ""


def _sanitize_filename_fragment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)


def _normalized_extension(filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    if extension in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        return extension
    return ""
