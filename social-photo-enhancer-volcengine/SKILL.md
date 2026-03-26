---
name: social-photo-enhancer-volcengine
description: "Improve a user-provided existing photo into a polished high-quality social-media-style image, OR generate creative advertising images using a product photo as reference, through the Volcengine Jimeng async image API. Use when: (1) the user uploads one image and wants it enhanced — clearer, better lit, more atmospheric, more premium, influencer-style, Xiaohongshu-style, Instagram-style, or more like a finished photo while preserving the original subject and scene; OR (2) the user uploads a product photo and wants advertising creative images generated from it — product ads, promotional visuals, marketing materials, or campaign imagery."
---

# Social Photo Enhancer Volcengine

This skill has two modes:

1. **Photo Enhancement** — the user provides one photo and wants it to look better while preserving the subject and scene.
2. **Product Ad Creative** — the user provides a product photo and wants new advertising images generated using the product as the hero element.

For Photo Enhancement: use when the intent is style enhancement or quality uplift. Do not use for cropping, adding text, collage, background replacement, batch processing, or local repair-only edits.

For Product Ad Creative: use when the user wants advertising, promotional, or marketing images featuring their product. The product photo serves as the visual reference for the AI to incorporate into new creative scenes.

## Image Intake

When the user sends an image in chat, the agent must save it to a local file before invoking the skill:

1. Receive the image attachment from the chat message.
2. Save the image to a local staging directory (default `C:\Users\Administrator\Desktop\upload\input`).
3. Use a timestamped filename to avoid collisions, e.g. `20260324_161900_source.jpg`.
4. Pass the saved local file path as `source_image` to the skill.

### Saving Chat Images to Local Files

Chat-inline images are stored as base64 in the OpenClaw session JSONL file but are **not** automatically saved to disk. The agent must extract them at runtime using inline code — no external scripts required.

**Steps the agent must follow:**

1. Find the active `.jsonl` session file (the one without `.reset.` in its name) under `<openclaw_home>/agents/main/sessions/`. On Windows the default home is `~/.openclaw`.
2. Parse each line as JSON; look for entries where `message.content[]` contains `{"type":"image","data":"<base64>"}`.
3. Take the **last** (most recent) match.
4. Detect format from the base64 prefix: `/9j/` → `.jpg`, `iVBOR` → `.png`, `R0lGOD` → `.gif`, `UklGR` → `.webp`. Default to `.png` if unknown.
5. Base64-decode and write to the staging directory with a timestamped filename, e.g. `<staging_dir>/<YYYYMMDD_HHMMSS>_source.<ext>`.

**Reference inline Python snippet** (the agent should write this to a temp file and execute it):

```python
import json, base64, os, sys, glob
from datetime import datetime
from pathlib import Path

session_dir = os.path.join(Path.home(), ".openclaw", "agents", "main", "sessions")
output_dir = os.path.join(Path.home(), "Desktop", "upload", "input")
os.makedirs(output_dir, exist_ok=True)

# Find active session JSONL (no .reset. in name, not sessions.json)
candidates = sorted(
    [p for p in Path(session_dir).glob("*.jsonl")
     if ".reset." not in p.name and p.name != "sessions.json"],
    key=lambda p: p.stat().st_mtime, reverse=True,
)
if not candidates:
    print("ERROR: No active session found", file=sys.stderr); sys.exit(1)

# Extract last image
image_data, timestamp = None, ""
with open(candidates[0], "r", encoding="utf-8") as f:
    for line in f:
        if '"type":"image"' not in line:
            continue
        try:
            obj = json.loads(line.strip())
            for c in obj.get("message", {}).get("content", []):
                if c.get("type") == "image" and c.get("data"):
                    image_data = c["data"]
                    timestamp = obj.get("timestamp", "")
        except (json.JSONDecodeError, KeyError):
            pass

if not image_data:
    print("ERROR: No image found in session", file=sys.stderr); sys.exit(1)

ext = ".jpg" if image_data[:4] == "/9j/" else ".png" if image_data[:5] == "iVBOR" else ".png"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = os.path.join(output_dir, f"{ts}_source{ext}")
with open(out_path, "wb") as f:
    f.write(base64.b64decode(image_data))
print(out_path)  # stdout: saved file path for the next step
```

This snippet is self-contained, has no dependencies beyond the Python standard library, and works on any machine running OpenClaw. The agent should adapt paths if the OS or home directory differs.

If the user provides a public URL or a skill public URL (`https://www.huashidai1.com/oss/skill/...`) instead of an attachment, pass it directly as `source_image` — no local save is needed.

Accepted `source_image` forms:
- A readable local file path (preferred for chat-uploaded images)
- A public URL under `https://www.huashidai1.com/oss/skill/` (skip upload to MinIO)
- Any other `http` or `https` image URL (will be downloaded and re-uploaded to MinIO)

## Quick Workflow

1. Confirm there is exactly one input image or image URL.
2. If the input is a chat attachment, save it to a local file first (see "Saving Chat Images to Local Files" above).
3. If the source is not already a skill public URL, the skill uploads it to MinIO and verifies the resulting public URL is reachable.
4. Extract or infer the user's goal.
5. Analyze the image into `scene_type`, `defects`, `must_keep`, and `recommended_style`.
6. Build a preservation-first img2img prompt with preservation constraints, uplift goals, one style preset, negative constraints, and a soft target of three candidates.
7. Submit the task to Volcengine Jimeng with `CVSync2AsyncSubmitTask`.
8. Poll `CVSync2AsyncGetResult` until the task succeeds or fails.
9. Review the returned images and reject results with obvious identity drift, broken anatomy, fake texture, or scene corruption.
10. **Cleanup**: Delete all temporary files created during the flow (e.g. the input JSON request file, the inline extraction script). Only keep the source image and the generated result images.

## Trigger Guidance

Strong triggers (Photo Enhancement):
- "Make this photo look more premium"
- "Turn this into Xiaohongshu style"
- "Give this a polished influencer vibe"
- "Keep the person but improve lighting and atmosphere"
- "Make this casual shot look like a finished photo"

Strong triggers (Product Ad Creative):
- "Design an ad for this product"
- "Generate advertising images for this"
- "帮我为这个产品设计广告"
- "用这张图生成宣传海报"
- "Create promotional visuals"
- "Make marketing materials featuring this"

Do not trigger on:
- "Crop this"
- "Remove this object"
- "Add text" (text overlay only — but ad creative with text descriptions is OK)
- "Make a collage"
- "Change the background entirely" (unless it's part of ad creative)
- "Process these 10 photos"

## Inputs

Required:
- One source image, provided as:
  - a readable local file path (typically saved from a chat attachment), or
  - a public URL under `https://www.huashidai1.com/oss/skill/`, or
  - another `http` or `https` image URL that can be fetched and re-uploaded to MinIO

Optional:
- One short user goal
- One style override

Hard constraints:
- Accept one source image only
- Aim for three candidates by default, but accept the provider's actual return count
- Prioritize preservation over heavy restyling

## Normalized Analysis

Use the schema from `scripts/social_photo_skill.py`.

When you need the supported presets, read [references/style-presets.md](references/style-presets.md).
When you need QC rules, read [references/quality-checklist.md](references/quality-checklist.md).
When you need prompt composition details, read [references/prompt-patterns.md](references/prompt-patterns.md).
When you need the MinIO upload contract and public URL rules, read [references/upload-contract.md](references/upload-contract.md).

Minimum analysis output:

```json
{
  "scene_type": "portrait",
  "defects": ["low-lighting", "flat-color", "busy-background"],
  "must_keep": ["subject identity", "core outfit", "scene semantics"],
  "recommended_style": "clear-portrait"
}
```

## Tooling

Use these bundled scripts when useful:

- `scripts/normalize_analysis.py`
  - Normalize a rough vision analysis blob or user hints into the fixed schema.
- `scripts/build_jimeng_request.py`
  - Build prompts, create Volcengine Jimeng payloads, submit tasks, poll results, and run the end-to-end flow.

Environment variables expected by the Volcengine adapter:
- `JIMENG_ACCESS_KEY`
- `JIMENG_SECRET_KEY`
- `JIMENG_ENDPOINT` default `https://visual.volcengineapi.com`
- `JIMENG_REGION` default `cn-north-1`
- `JIMENG_SERVICE` default `cv`
- `JIMENG_REQ_KEY` default `jimeng_t2i_v40`
- `JIMENG_SUBMIT_ACTION` default `CVSync2AsyncSubmitTask`
- `JIMENG_GET_RESULT_ACTION` default `CVSync2AsyncGetResult`
- `JIMENG_API_VERSION` default `2022-08-31`

Environment variables expected by the MinIO upload stage when the input is not already a skill public URL:
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_ENDPOINT` default `http://huashidai1.com:9000`
- `MINIO_BUCKET` default `skill`
- `MINIO_REGION` default `us-east-1`
- `MINIO_SERVICE` default `s3`
- `MINIO_PUBLIC_BASE_URL` default `https://www.huashidai1.com/oss`
- `MINIO_OBJECT_PREFIX` default `input`
- `MINIO_VERIFY_PUBLIC_URL` default `true`

This skill does not use OpenRouter for image generation. It calls Volcengine Jimeng directly with V4 request signing.

## Output Format

Return a concise structured summary with:
- selected style
- final prompt
- Volcengine request summary
- provider result references when successful
- local downloaded result paths under `C:\Users\Administrator\Desktop\upload`
- QC notes for each result

If the provider fails:
- report the failure plainly
- say whether a single retry was attempted
- do not pretend the images were generated

## Retry Rule

Allow at most one retry and only for provider timeout, retryable Volcengine provider failures, obvious style drift, or obvious identity drift.

On retry:
- reduce strength
- reinforce preservation language
- keep the same style unless the failure clearly came from style overreach

---

# Product Ad Creative Mode

Use this mode when the user provides a product photo and wants advertising or promotional images generated. The product image is used as a visual reference — the AI generates new creative scenes that feature the product as the hero element.

## Mode Detection

Choose this mode when the user's intent matches any of:
- "Design an ad for this product"
- "Generate advertising images for this"
- "Create promotional visuals"
- "Make marketing materials for this product"
- "Design a campaign image"
- Keywords: 广告、宣传图、产品海报、营销图、推广图、创意图

Stay in Photo Enhancement mode when the user just wants to improve the existing photo's quality.

## Ad Creative Workflow

1. **Intake**: Same as Photo Enhancement — save the product image to a local file if it's a chat attachment (see "Saving Chat Images to Local Files" above).
2. **Upload to MinIO**: Upload the source product image via `prepare_source_image()` to get a public URL. This is the reference image for the AI.
3. **Analyze the product**: Identify what the product is (brand, type, key visual features, colors, packaging shape) from the image.
4. **Design ad concepts**: Create multiple distinct advertising concepts. Default to **5 concepts** unless the user specifies a different count. Each concept should have:
   - A descriptive name (e.g. `morning_sunshine`, `green_pasture`)
   - A detailed English prompt describing the ad scene with the product as the hero
   - A `strength` value (typically `0.6`–`0.7` for ad creatives — higher than enhancement mode because more creative freedom is needed)
5. **Submit serially**: Submit jobs **one at a time** to avoid Volcengine's concurrent request limit (code `50430`). Wait for each job to complete before submitting the next. Add a 5-second gap between jobs.
6. **Rate limit handling**: If a `50430` error occurs, retry with exponential backoff (10s, 20s, 30s...) up to 5 attempts per job.
7. **Download results**: Save generated images to the standard output directory (`C:\Users\Administrator\Desktop\upload`), NOT to a custom subdirectory.
8. **Cleanup**: Delete ALL temporary files — scripts, JSON files, intermediate data. Only keep the final generated images in the output directory. The source product image should remain in the input staging directory (`Desktop\upload\input`) if it was extracted from chat.

## Ad Prompt Guidelines

Each ad prompt should:
- Describe the product accurately (packaging, brand elements, colors)
- Place the product as the **central hero element** in the scene
- Describe the surrounding scene, lighting, mood, and props in detail
- Specify photography style (e.g. "professional commercial product photography", "8K quality")
- Include negative constraints: avoid distorting the product packaging, changing brand text, or making the product unrecognizable
- Be written in **English** regardless of the user's language (Jimeng processes English prompts)

## Recommended Ad Concept Categories

When the user doesn't specify particular styles, draw from these categories to create variety:

| Category | Description | Example Scene |
|----------|-------------|---------------|
| **Lifestyle** | Product in a natural use scenario | Breakfast table, kitchen counter, picnic |
| **Nature/Origin** | Emphasize natural or organic origins | Meadow, farm, pastoral landscape |
| **Dynamic/Action** | Eye-catching motion effects | Liquid splash, pour, burst |
| **Family/Warm** | Emotional connection, family values | Family breakfast, children, warmth |
| **Premium/Luxury** | High-end, minimalist, editorial | Dark studio, dramatic lighting, elegant props |
| **Seasonal** | Tied to a season or holiday | Summer freshness, winter warmth, spring bloom |

## Ad Creative Trigger Examples

Strong triggers:
- "帮我为这个产品设计广告"
- "Generate 5 ad images for this product"
- "用这个产品图生成宣传图"
- "Design promotional materials for this"
- "Create marketing visuals featuring this product"

## Ad Creative Output Format

Return a summary with:
- Product identification (what was detected in the image)
- Number of concepts generated
- For each concept: name, brief description of the creative direction, and the local file path of the generated image
- All images in the standard output directory: `C:\Users\Administrator\Desktop\upload`

## Cross-Skill Result Passing

After each successful enhance flow, the skill automatically writes a **result manifest** to a fixed location:

```
C:\Users\Administrator\Desktop\upload\last_result.json
```

Other skills can read this file to get the latest Jimeng output URLs and local paths without needing to parse stdout or pass parameters manually.

### Manifest Schema

```json
{
  "timestamp": "2026-03-25T09:43:36+08:00",
  "status": "succeeded",
  "task_id": "8286014737659118377",
  "source_image": "https://www.huashidai1.com/oss/skill/input/2026/03/25/xxx.jpg",
  "outputs": [
    {
      "url": "https://p9-aiop-sign.byteimg.com/...",
      "local_path": "C:\\Users\\Administrator\\Desktop\\upload\\xxx_1.png"
    }
  ],
  "selected_style": "daily-atmosphere",
  "qc_passed": true
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO-8601 string | When the manifest was written |
| `status` | `"succeeded"` or `"failed"` | Overall result status |
| `task_id` | string | Jimeng async task ID |
| `source_image` | URL or null | Public URL of the source image used |
| `outputs` | array of `{url, local_path}` | Each generated image's CDN URL and local file path |
| `selected_style` | string | Style preset used for the enhancement |
| `qc_passed` | boolean | Whether the quality check passed |

### Usage by Other Skills

1. Call the social-photo-enhancer skill (via agent or script).
2. After it completes, read `Desktop\upload\last_result.json`.
3. Use `outputs[].url` for the CDN URLs (temporary, signed — consume promptly).
4. Use `outputs[].local_path` for local file access.

### Important Notes

- The manifest is **overwritten** on each run — it always reflects the most recent result.
- CDN URLs from Jimeng are **temporary signed URLs** with expiration. If the consuming skill needs persistent URLs, it should re-upload the images (e.g. to MinIO).
- The manifest path can be overridden via the `JIMENG_RESULT_MANIFEST_PATH` environment variable.
- If the enhance flow fails QC, the manifest is still written with `"status": "failed"` and `"qc_passed": false`.

## File Organization Rules (Both Modes)

- **Source images from chat**: Save to `Desktop\upload\input\` with timestamped filenames
- **Generated result images**: Save to `Desktop\upload\` (the standard output directory)
- **Temporary files** (scripts, JSON, intermediate data): Delete after the flow completes
- **Never** mix source images, temporary files, and generated results in the same directory
- **Never** create ad-hoc subdirectories for a single run — use the standard directories above
