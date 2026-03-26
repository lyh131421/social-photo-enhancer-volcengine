from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from social_photo_skill import dumps_json, normalize_analysis


def load_json(path: str | None) -> Dict[str, Any]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a social-photo enhancement analysis blob.")
    parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    parser.add_argument("--style-override", help="Optional style override.")
    args = parser.parse_args()

    payload = load_json(args.input)
    analysis = normalize_analysis(payload, style_override=args.style_override)
    print(dumps_json(analysis.__dict__))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
