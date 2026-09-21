# Cloudflare Pages

## Dashboard settings
- Framework preset: **None**
- Build command: `bash scripts/cf_pages_build.sh`
- Build output directory: `dist`
- Optional env: `PYTHON_VERSION=3.11`
- Optional env (after first success): `DEPLOY_HOOK_URL` = Deploy Hook URL

## Do not add wrangler.toml
A root `wrangler.toml` makes Pages run **wrangler deploy**, which often fails in Git-connected builds with:
`Failed: error occurred while running deploy command`
and a wrangler log under `/opt/buildhome/.config/.wrangler/logs/`.

Pages Functions still work from the `functions/` directory without wrangler.toml.

## Refresh live
Create a Deploy Hook in the Pages project, set `DEPLOY_HOOK_URL`, redeploy once.
