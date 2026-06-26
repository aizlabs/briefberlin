# GitHub Pages Setup

This repository deploys already-committed public Jekyll output from `output/`.

Do not run private/manual article generation in GitHub Actions. Manual source articles must stay local and ignored.

Use `.github/workflows/deploy-pages.yml` only for building and deploying committed public output.

## Enable GitHub Pages

1. Push the repository to GitHub.
2. In GitHub, open **Settings → Pages**.
3. Set **Source** to **GitHub Actions**.
4. Save the Pages settings.

The workflow has the required Pages permissions:

- `pages: write`
- `id-token: write`
- `contents: read`

## Trigger A Deploy

Deploys run automatically when a commit pushed to `main` changes files under `output/**`.

To trigger manually:

1. Open **Actions** in GitHub.
2. Select **Deploy Jekyll Site to GitHub Pages**.
3. Click **Run workflow**.
4. Select branch `main`.
5. Click **Run workflow**.

From the command line, after `origin` is configured:

```bash
git push origin main
```

## Custom Domain

The production domain is `briefberlin.de`.

Repository-side config:

- `output/_config.yml` uses `url: "https://briefberlin.de"`.
- `output/CNAME` contains `briefberlin.de`.

GitHub setup:

1. Open **Settings → Pages**.
2. Under **Custom domain**, enter `briefberlin.de`.
3. Save and wait for GitHub's DNS check.
4. Enable **Enforce HTTPS** after the certificate is ready.

DNS setup at the domain provider:

- For the apex domain `briefberlin.de`, add GitHub Pages `A` records:
  - `185.199.108.153`
  - `185.199.109.153`
  - `185.199.110.153`
  - `185.199.111.153`
- If using `www.briefberlin.de`, add a `CNAME` record from `www` to `<github-username>.github.io`.

Keep the GitHub Pages custom-domain setting, DNS records, `output/CNAME`, and `output/_config.yml` aligned if the domain changes.
