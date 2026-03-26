# Quality Checklist

Review every generated image before presenting it as a primary result.

## Must Pass

- The main subject still matches the original person or object.
- The main scene still means the same thing as the original image.
- Lighting is improved without becoming fake.
- Skin, fabric, food, and surfaces keep believable texture.
- No extra fingers, limbs, duplicated objects, or broken perspective.

## Common Failures

- Identity drift: the person no longer looks like the source.
- Scene corruption: key objects disappear or the location changes meaningfully.
- AI texture: plastic skin, waxy surfaces, unnatural sharpening.
- Composition overreach: background becomes unrelated or too heavily reconstructed.
- Color overreach: saturation or warmth becomes obviously artificial.

## Retry Recommendation

Recommend one retry when:
- the result is structurally close but too stylized
- the result preserves the subject but breaks texture realism
- the provider times out or returns an incomplete image set

Do not retry endlessly. Stop after one retry and report the failure.
