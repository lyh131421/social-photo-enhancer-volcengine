# Upload Contract

Use this document when wiring the Volcengine skill so it can stage one input image into MinIO before calling Jimeng.

## Upload Flow

1. Receive one user image input.
2. If the input is already a public URL under `https://www.huashidai1.com/oss/skill/`, skip upload.
3. Otherwise, the skill generates a stable object key under the `skill` bucket.
4. The skill uploads the image to MinIO through the internal endpoint:

```text
http://huashidai1.com:9000
```

5. The same object is exposed through the public domain:

```text
https://www.huashidai1.com/oss/skill/<object-key>
```

6. The skill passes that public URL as `source_image` to Volcengine Jimeng.

Accepted input forms:
- a skill public URL (skips upload)
- a readable local file path (e.g. saved from a chat attachment by the agent)
- another remote `http` or `https` image URL that can be downloaded and re-uploaded

## Object Key Convention

Use a date-based layout and a unique suffix. Example:

```text
input/2026/03/24/2d53dbaf-1a5f-4f1d-b2e1-demo.png
```

This keeps uploads traceable and avoids collisions.

## Public URL Rules

- Use the `skill` bucket only.
- The URL must begin with `https://www.huashidai1.com/oss/skill/`.
- The URL must be directly reachable by Volcengine Jimeng.
- v1 uses public URLs, not signed URLs.

## Preflight Check

Before calling Jimeng:

- confirm the public URL returns the uploaded image
- confirm the object is not blocked by private ACLs or a missing gateway route
- stop the request if the URL is not externally reachable

## Result Handling

The skill downloads generated images to:

```text
C:\Users\Administrator\Desktop\upload
```

The skill returns both:
- the provider URL
- the local downloaded file path

## Environment

The upload stage expects:
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_ENDPOINT=http://huashidai1.com:9000`
- `MINIO_BUCKET=skill`
- `MINIO_REGION=us-east-1`
- `MINIO_SERVICE=s3`
- `MINIO_PUBLIC_BASE_URL=https://www.huashidai1.com/oss`
- `MINIO_OBJECT_PREFIX=input`
