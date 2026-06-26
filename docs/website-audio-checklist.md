# Website Audio Checklist

This plan is scoped to website playback first. Telegram audio delivery and podcast feeds stay out of the first milestone.

## Implementation Checklist

- [x] Add audio configuration and environment-variable contract.
- [x] Add provider-neutral audio models and an optional `article.audio` field.
- [x] Add a local audio-preparation stage that builds narration scripts and manifests for approved articles.
- [x] Add post frontmatter support for website audio metadata.
- [x] Add website rendering support so articles show a player only when `audio_url` exists.
- [ ] Add real TTS provider integration.
- [ ] Add S3 upload implementation.
- [ ] Enable CI production uploads behind GitHub repository secrets.
- [ ] Verify end-to-end playback from `https://media.spaili.com/...` on the website.

## When The AWS Setup Becomes Mandatory

The S3 + CloudFront setup is not required to start coding or to run local tests.

It becomes required at the moment you want to enable both of these in CI:

- `AUDIO_ENABLED=true`
- `AUDIO_UPLOAD_ENABLED=true`

Until then, the code can generate local narration scripts and manifests under `output/audio/` without publishing live audio URLs.

## AWS Setup For `media.spaili.com`

1. Create a private S3 bucket, for example `spaili-audio-prod`.
2. Create a CloudFront distribution with that bucket as the origin.
3. Configure Origin Access Control so CloudFront can read the private bucket.
4. Request an ACM certificate for `media.spaili.com`.
5. Point `media.spaili.com` to the CloudFront distribution in DNS.
6. Ensure CloudFront allows `GET` and `HEAD` requests for audio objects.
7. Create an IAM user or role limited to the audio bucket/prefix.
8. Store the IAM access key in GitHub repository secrets.

## GitHub Actions Variables

Add these repository variables before enabling CI uploads:

- `AUDIO_ENABLED`
- `AUDIO_PROVIDER`
- `AUDIO_VOICE`
- `AUDIO_FORMAT`
- `AUDIO_UPLOAD_ENABLED`
- `AUDIO_PUBLIC_BASE_URL`
- `AUDIO_S3_BUCKET`
- `AUDIO_S3_PREFIX`
- `AWS_REGION`

## GitHub Repository Secrets

Add these repository secrets before enabling CI uploads:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Recommended values:

- `AUDIO_PROVIDER=openai`
- `AUDIO_VOICE=alloy`
- `AUDIO_PUBLIC_BASE_URL=https://media.spaili.com`
- `AUDIO_S3_PREFIX=articles`

## CI Wiring

The generation workflow should export the audio secrets as environment variables for `uv run spai-pipeline`.

The first production-ready upload milestone is:

1. TTS provider returns an audio file.
2. Pipeline uploads it to S3.
3. Frontmatter stores the CloudFront URL.
4. Jekyll renders the website player.
