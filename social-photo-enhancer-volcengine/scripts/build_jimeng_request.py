from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from social_photo_skill import (
    EnhanceInput,
    JobHandle,
    analyze_source_image,
    build_img2img_prompt,
    build_jimeng_request,
    dumps_json,
    enhance_social_photo,
    normalize_analysis,
    poll_jimeng_job,
    submit_jimeng_job,
)


def load_json(path: str | None) -> Dict[str, Any]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def command_build(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    enhance_input = EnhanceInput.from_mapping(payload)
    raw_analysis = payload.get("analysis") or analyze_source_image(enhance_input.source_image)
    analysis = normalize_analysis(raw_analysis, style_override=enhance_input.style_override)
    prompt_spec = build_img2img_prompt(
        analysis=analysis,
        user_goal=enhance_input.user_goal,
        style_override=enhance_input.style_override,
        preserve_identity=enhance_input.preserve_identity,
        num_outputs=enhance_input.num_outputs,
    )
    request_payload = build_jimeng_request(enhance_input, prompt_spec)
    print(
        dumps_json(
            {
                "analysis": asdict(analysis),
                "prompt_spec": asdict(prompt_spec),
                "jimeng_request": request_payload,
            }
        )
    )
    return 0


def command_submit(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    handle = submit_jimeng_job(payload)
    print(dumps_json(asdict(handle)))
    return 0


def command_poll(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    handle = JobHandle(**payload)
    result = poll_jimeng_job(handle, poll_interval_seconds=args.interval, timeout_seconds=args.timeout)
    print(dumps_json(asdict(result)))
    return 0


def command_enhance(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    result = enhance_social_photo(
        payload,
        raw_analysis=payload.get("analysis"),
        poll_interval_seconds=args.interval,
        timeout_seconds=args.timeout,
    )
    print(dumps_json(result.to_dict()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and submit Volcengine Jimeng async img2img jobs for social-photo enhancement, uploading the source image to MinIO first when needed. Supports local file paths, skill public URLs, and external image URLs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build normalized analysis, prompt, and a Volcengine submit payload. Supports local paths, skill public URLs, and external image URLs.")
    build_parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    build_parser.set_defaults(func=command_build)

    submit_parser = subparsers.add_parser("submit", help="Submit an already-built Volcengine task payload.")
    submit_parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    submit_parser.set_defaults(func=command_submit)

    poll_parser = subparsers.add_parser("poll", help="Poll a Volcengine Jimeng task handle.")
    poll_parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    poll_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds.")
    poll_parser.add_argument("--timeout", type=int, default=120, help="Polling timeout in seconds.")
    poll_parser.set_defaults(func=command_poll)

    enhance_parser = subparsers.add_parser("enhance", help="Run the full single-image enhancement flow with optional MinIO upload against Volcengine Jimeng.")
    enhance_parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    enhance_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds.")
    enhance_parser.add_argument("--timeout", type=int, default=120, help="Polling timeout in seconds.")
    enhance_parser.set_defaults(func=command_enhance)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
