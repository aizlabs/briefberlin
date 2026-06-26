# Website Audio Checklist

Audio is optional and currently disabled by default. Enable it only after the public media domain and storage are configured.

## Preflight

- [ ] `audio.enabled` is true only when audio should be generated.
- [ ] `audio.upload_enabled` is true only when S3/CloudFront delivery is ready.
- [ ] `AUDIO_PUBLIC_BASE_URL` points to the public media domain.
- [ ] Generated posts include valid audio front matter only for uploaded files.
- [ ] Playback works from the public site.

## Suggested Production Shape

- Media domain: `https://media.briefberlin.de`
- S3 bucket example: `briefberlin-audio-prod`
- Region: `eu-central-1`
- Prefix: `articles`

## Required Environment Variables

```bash
AUDIO_ENABLED=true
AUDIO_UPLOAD_ENABLED=true
AUDIO_PUBLIC_BASE_URL=https://media.briefberlin.de
AUDIO_S3_BUCKET=briefberlin-audio-prod
AUDIO_S3_REGION=eu-central-1
AUDIO_S3_PREFIX=articles
```

## Privacy Rule

Audio scripts and generated audio must be based on the public learner article only. Do not upload private source text, base article drafts, or intermediate prompts.
