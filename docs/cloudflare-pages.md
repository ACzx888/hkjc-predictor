# Cloudflare deploy (Workers UI or Pages)

## If your settings look like the Workers Build panel
(fields: Build command, Deploy command, Version command, Root directory — **no** Output directory)

| Field | Value |
|-------|--------|
| Build command | `bash scripts/cf_pages_build.sh` |
| Deploy command | `npx wrangler deploy` |
| Version command | **clear / empty** |
| Root directory | **empty** (do not use `/`) |

`wrangler.toml` must contain:

```toml
[assets]
directory = "./dist"
```

Save only after Root directory is empty — `/` often causes **Invalid request body**.

## If you create a classic Pages project instead
(Workers & Pages → Create → Pages → Connect to Git)

| Field | Value |
|-------|--------|
| Framework | None |
| Build command | `bash scripts/cf_pages_build.sh` |
| Build output directory | `dist` |
| Deploy command | empty |
| Root directory | empty |

Classic Pages has **Build output directory**; the Workers panel does not.
