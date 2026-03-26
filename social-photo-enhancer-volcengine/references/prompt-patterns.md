# Prompt Patterns

Build the positive prompt in four sections.

## 1. Preservation Constraints

State what must not change:

- keep the same person identity
- keep the core outfit or product
- keep the same scene meaning
- preserve the original camera perspective when possible

## 2. Uplift Goals

State the enhancement target:

- cleaner light
- more depth
- more premium color harmony
- stronger subject separation
- polished social-media finish

## 3. Style Preset

Inject one preset from [style-presets.md](style-presets.md) and keep it subtle unless the user explicitly requests stronger styling.

## 4. Negative Constraints

Always guard against:

- over-smoothed skin
- plastic textures
- extra fingers or limbs
- distorted face
- warped background geometry
- unrelated objects
- over-saturated colors

## Baseline Prompt Skeleton

```text
Preserve the same subject identity, key outfit, and core scene semantics.
Upgrade the image into a polished, high-quality social-media-style photo with better lighting, clearer depth, cleaner composition, and more premium color harmony.
Apply {style preset cues}.
Keep the result realistic and faithful to the original image.
Avoid plastic skin, anatomy errors, warped perspective, fake textures, excessive blur, and unrelated scene changes.
```

## Retry Adjustment

If the first result drifts too far:

- lower the edit strength
- restate preservation language more explicitly
- reduce stylistic adjectives
- keep only one preset and remove any extra flavor terms
