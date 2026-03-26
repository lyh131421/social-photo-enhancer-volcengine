from __future__ import annotations

import datetime
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import social_photo_skill as skill_module  # noqa: E402
from social_photo_skill import (  # noqa: E402
    DEFAULT_SOURCE_URL_PREFIX,
    EnhanceInput,
    JimengAdapter,
    JimengConfig,
    JobHandle,
    ProviderResult,
    build_img2img_prompt,
    build_jimeng_request,
    build_public_source_url,
    build_v4_headers,
    download_result_images,
    enhance_social_photo,
    is_retryable_provider_code,
    normalize_analysis,
    poll_jimeng_job,
    run_quality_check,
    submit_jimeng_job,
)


class SequenceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append((method, url, headers, payload, timeout))
        if not self.responses:
            raise AssertionError("No more fake responses configured.")
        return self.responses.pop(0)


class FakeHeaders(dict):
    def get_content_type(self):
        return str(self.get("Content-Type", "")).split(";", 1)[0].strip()


class FakeDownloadResponse:
    def __init__(self, content: bytes, content_type: str = "image/png"):
        self._content = content
        self.headers = FakeHeaders({"Content-Type": content_type})

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SocialPhotoSkillVolcengineTests(unittest.TestCase):
    def setUp(self):
        self.config = JimengConfig(
            access_key="test-ak",
            secret_key="test-sk",
            endpoint="https://visual.volcengineapi.com",
            region="cn-north-1",
            service="cv",
            req_key="jimeng_t2i_v40",
        )
        self.fixed_time = datetime.datetime(2026, 3, 24, 12, 0, 0)
        self.valid_source = DEFAULT_SOURCE_URL_PREFIX + "input/2026/03/24/source.png"
        self.test_root = Path(__file__).resolve().parents[1] / ".tmp-tests"
        self.test_root.mkdir(exist_ok=True)

    def test_enhance_input_rejects_non_public_url(self):
        with self.assertRaises(ValueError):
            EnhanceInput.from_mapping({"source_image": "portrait.jpg"})

    def test_enhance_input_accepts_other_public_domain_for_reupload(self):
        parsed = EnhanceInput.from_mapping({"source_image": "https://example.com/source.png"})
        self.assertEqual(parsed.source_image, "https://example.com/source.png")

    def test_build_public_source_url_uses_skill_bucket_prefix(self):
        public_url = build_public_source_url("input/2026/03/24/demo.png")
        self.assertEqual(public_url, DEFAULT_SOURCE_URL_PREFIX + "input/2026/03/24/demo.png")

    def test_v4_headers_are_stable_for_fixed_input(self):
        body = '{"req_key":"jimeng_t2i_v40","image_urls":["https://www.huashidai1.com/oss/skill/input/2026/03/24/source.png"],"prompt":"test","scale":0.35}'
        query = "Action=CVSync2AsyncSubmitTask&Version=2022-08-31"
        headers_a = build_v4_headers(self.config, query, body, current_time=self.fixed_time)
        headers_b = build_v4_headers(self.config, query, body, current_time=self.fixed_time)
        self.assertEqual(headers_a, headers_b)
        self.assertIn("Authorization", headers_a)
        self.assertEqual(headers_a["X-Date"], "20260324T120000Z")

    def test_submit_extracts_task_id(self):
        transport = SequenceTransport(
            [
                {
                    "code": 10000,
                    "data": {"task_id": "7392616336519610409"},
                    "message": "Success",
                    "request_id": "req-submit",
                    "time_elapsed": "104.8ms",
                }
            ]
        )
        adapter = JimengAdapter(config=self.config, transport=transport, clock=lambda: self.fixed_time)
        request_payload = build_jimeng_request(
            {"source_image": self.valid_source},
            {
                "positive_prompt": "good",
                "negative_prompt": "bad",
                "strength": 0.35,
                "num_outputs": 3,
                "selected_style": "daily-atmosphere",
            },
        )
        handle = submit_jimeng_job(request_payload, adapter)
        self.assertEqual(handle.job_id, "7392616336519610409")
        self.assertIn("CVSync2AsyncSubmitTask", transport.calls[0][1])
        self.assertIn("Authorization", transport.calls[0][2])

    def test_poll_maps_status_and_returns_urls(self):
        transport = SequenceTransport(
            [
                {
                    "code": 10000,
                    "data": {"status": "in_queue"},
                    "message": "Success",
                    "request_id": "req-1",
                    "time_elapsed": "1ms",
                },
                {
                    "code": 10000,
                    "data": {"status": "generating"},
                    "message": "Success",
                    "request_id": "req-2",
                    "time_elapsed": "1ms",
                },
                {
                    "code": 10000,
                    "data": {
                        "status": "done",
                        "image_urls": [
                            "https://example.com/1.png",
                            "https://example.com/2.png",
                        ],
                    },
                    "message": "Success",
                    "request_id": "req-3",
                    "time_elapsed": "508ms",
                },
            ]
        )
        adapter = JimengAdapter(config=self.config, transport=transport, clock=lambda: self.fixed_time)
        result = poll_jimeng_job(
            JobHandle(job_id="7392616336519610409", status_url="https://visual.volcengineapi.com"),
            adapter=adapter,
            poll_interval_seconds=0,
            timeout_seconds=1,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(result.images), 2)
        self.assertEqual(result.images[0]["url"], "https://example.com/1.png")

    def test_prompt_mentions_three_variations_when_requested(self):
        prompt = build_img2img_prompt(
            normalize_analysis({"scene_type": "portrait", "defects": ["dark"], "must_keep": ["subject identity"]}),
            num_outputs=3,
        )
        self.assertIn("generate 3 polished candidate variations", prompt.positive_prompt)

    def test_retryable_and_non_retryable_codes_are_mapped(self):
        self.assertTrue(is_retryable_provider_code(50429))
        self.assertTrue(is_retryable_provider_code(50511))
        self.assertFalse(is_retryable_provider_code(50413))
        self.assertFalse(is_retryable_provider_code(50500))

    def test_download_result_images_saves_local_paths(self):
        tmpdir = tempfile.mkdtemp(dir=self.test_root)
        try:
            localized = download_result_images(
                [{"url": "https://example.com/render-1.png"}],
                task_id="7392616336519610409",
                download_dir=tmpdir,
                fetcher=lambda url, timeout=60: FakeDownloadResponse(b"png-bytes", "image/png"),
            )
            self.assertEqual(len(localized), 1)
            self.assertTrue(os.path.exists(localized[0]["local_path"]))
            self.assertTrue(localized[0]["local_path"].startswith(tmpdir))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_quality_check_does_not_force_exact_candidate_count(self):
        report = run_quality_check(
            self.valid_source,
            ProviderResult(
                status="succeeded",
                images=[
                    {"url": "https://example.com/1.png"},
                    {"url": "https://example.com/2.png"},
                ],
            ),
        )
        self.assertTrue(report.passed)

    def test_provider_error_code_controls_retry(self):
        retry_report = run_quality_check(
            self.valid_source,
            ProviderResult(
                status="failed",
                images=[],
                error="Post Img Risk Not Pass (code=50511)",
                provider_meta={"code": 50511},
            ),
        )
        stop_report = run_quality_check(
            self.valid_source,
            ProviderResult(
                status="failed",
                images=[],
                error="Post Text Risk Not Pass (code=50413)",
                provider_meta={"code": 50413},
            ),
        )
        self.assertTrue(retry_report.retry_recommended)
        self.assertFalse(stop_report.retry_recommended)

    def test_end_to_end_flow_downloads_to_local_dir(self):
        transport = SequenceTransport(
            [
                {
                    "code": 10000,
                    "data": {"task_id": "7392616336519610409"},
                    "message": "Success",
                    "request_id": "req-submit",
                    "time_elapsed": "104ms",
                },
                {
                    "code": 10000,
                    "data": {"status": "done", "image_urls": ["https://example.com/1.png", "https://example.com/2.png"]},
                    "message": "Success",
                    "request_id": "req-poll",
                    "time_elapsed": "508ms",
                },
            ]
        )
        adapter = JimengAdapter(config=self.config, transport=transport, clock=lambda: self.fixed_time)
        tmpdir = tempfile.mkdtemp(dir=self.test_root)
        try:
            with mock.patch.dict(os.environ, {"JIMENG_DOWNLOAD_DIR": tmpdir}, clear=False):
                with mock.patch.object(skill_module.request, "urlopen", side_effect=lambda url, timeout=60: FakeDownloadResponse(b"image-data", "image/png")):
                    result = enhance_social_photo(
                        {
                            "source_image": self.valid_source,
                            "user_goal": "Make it premium and social-ready.",
                        },
                        adapter=adapter,
                        raw_analysis={"scene_type": "portrait", "defects": ["dark"], "must_keep": ["subject identity"]},
                        poll_interval_seconds=0,
                        timeout_seconds=1,
                    )
            self.assertEqual(result.provider_meta["task_id"], "7392616336519610409")
            self.assertEqual(len(result.results), 2)
            self.assertIn("desired_num_outputs", result.jimeng_request["metadata"])
            self.assertTrue(result.results[0]["local_path"].startswith(tmpdir))
            self.assertTrue(os.path.exists(result.results[0]["local_path"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
