# Style Presets

Use these presets when building the enhancement prompt. Keep the user identity, main objects, and scene meaning intact.

## clear-portrait

- Best for: portraits, selfies, casual people shots
- Visual intent: clean skin tone, bright but natural light, soft depth, refined composition
- Prompt cues: clear skin texture, natural glow, soft directional light, tidy background separation, realistic facial details
- Avoid: plastic skin, over-whitening, reshaped face, exaggerated blur

## warm-cafe

- Best for: cafe, restaurant, table shots, lifestyle indoor scenes
- Visual intent: warm whites, cleaner table styling, richer depth, cozy premium atmosphere
- Prompt cues: warm ambient light, controlled highlights, neat composition, appetizing detail, premium lifestyle mood
- Avoid: fake food texture, extreme yellow cast, missing table items that define the scene

## airy-travel

- Best for: travel snapshots, street scenes, scenic outdoor photos
- Visual intent: transparent light, layered depth, gentle contrast, cinematic openness
- Prompt cues: airy light, crisp environmental detail, natural sky tone, stronger subject separation, travel editorial feel
- Avoid: unrealistic sky replacement, changed landmarks, over-dramatic grading

## daily-atmosphere

- Best for: generic daily moments, home, casual lifestyle, mixed scenes
- Visual intent: cleaner frame, balanced tone, subtle atmosphere, polished but believable finish
- Prompt cues: natural lighting uplift, cleaner visual hierarchy, calm premium color palette, realistic texture
- Avoid: heavy filters, strong scene rewrite, gimmicky style effects

## Style Selection Rule

Choose the preset in this order:

1. Honor `style_override` if it matches a known preset.
2. Map from `scene_type`:
   - `portrait` -> `clear-portrait`
   - `cafe` or `food` -> `warm-cafe`
   - `travel` -> `airy-travel`
   - everything else -> `daily-atmosphere`
3. If the image looks fragile or heavily flawed, stay on the gentlest compatible preset.
