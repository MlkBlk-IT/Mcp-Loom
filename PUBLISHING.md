# Publishing `mcp-loom-mcp`

Two ways to publish. Pick one — both produce the same artifacts.

The package name, the repository name and the GitHub URL are all `mcp-loom-mcp`.

> **Why not `mcp-loom`?** That name is held by two unrelated projects — on PyPI a server for
> Loom's internal GraphQL API, on npm an unrelated DuckDB proxy — and a registry never releases
> a name. The repository was renamed from `Mcp-Loom` to match (the old URL redirects).

---

## A. GitHub Actions (recommended — nothing secret on your machine)

**PyPI — trusted publishing (OIDC). No API token is stored anywhere.**

One-time setup on pypi.org → *MlkBlk-IT* → *Publishing* → *Add a new pending publisher*:

| Field | Value |
|---|---|
| PyPI project name | `mcp-loom-mcp` |
| Owner | `MlkBlk-IT` |
| Repository | `MlkBlk-IT/mcp-loom-mcp` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Then create the GitHub environment: repo → *Settings* → *Environments* → new environment `pypi`.

**npm — classic automation token.**

1. npmjs.com → *Access Tokens* → *Generate new token* (scope: **publish**).
2. Repo → *Settings* → *Secrets and variables* → *Actions* → new repository secret `NPM_TOKEN`.

Then bump the version in `pyproject.toml` and `package.json`, commit, tag, and run
*Actions* → *Publish* → *Run workflow*.

---

## B. From your machine

```bash
# build
python -m build
python -m twine check dist/*

# PyPI — needs TWINE_USERNAME=__token__ and TWINE_PASSWORD=pypi-XXXX
python -m twine upload dist/*

# npm — needs `npm login` first
npm publish --access public
```

`python -m build` produces `dist/mcp_loom_mcp-<version>-py3-none-any.whl` and
`dist/mcp_loom_mcp-<version>.tar.gz`.

---

## Notes

- The console scripts are `loom-mcp` (the MCP server clients spawn) and `loom` (the admin CLI).
  The import package is `loom`. The distribution name is `mcp-loom-mcp`.
- The npm package exposes the `mcp-loom-mcp` binary.
- The repository is **not** production-ready yet — see the WIP banner in the README and
  `PROGRESS.md`. Publishing says nothing about readiness.
