# Contributing to EchoLocate

Thanks for contributing! This repo uses **Conventional Commits** to drive
automated versioning and releases, and gates merges to `main` on CI. A few
conventions keep that machinery working.

## Commit messages — Conventional Commits (required)

Every commit is linted on pull requests by the `commitlint` check, which is a
**required status check** — a non-conforming commit blocks the merge. Format:

```
type(scope): subject
```

- **Types**: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `build`,
  `perf`, `style`, `revert`.
- **Scopes** (optional): `vector-rs`, `sonar`, `mcp`, `embeddings`, `finetune`,
  `echoes`, `ci`, `deps`, `release`.
- Keep the subject imperative and lower-case, e.g.
  `fix(vector-rs): guard against empty index`.
- Breaking changes: add a `BREAKING CHANGE:` footer, or a `!` after the type
  (`feat!: ...`).

Footers such as `Co-Authored-By:` are fine — only the **subject** line has to
match the format.

## Versioning & releases (automatic)

The whole repo shares a single semver version. On every merge to `main`,
[`.github/workflows/release.yml`](.github/workflows/release.yml) runs
[semantic-release](https://semantic-release.gitbook.io/), which:

1. Reads the Conventional Commits since the last tag.
2. Computes the next version — `feat:` → **minor**, `fix:` → **patch**,
   `BREAKING CHANGE` → **major**. Other types (`docs`, `chore`, `ci`, …) do not
   trigger a release.
3. Creates the git tag and a **GitHub Release** with generated notes.

If a merge contains no releasable commit, no release is cut — that's expected.
The baseline tag is **`v1.0.0`**; everything releases forward from there.

To preview what a release would produce without publishing:

```bash
npx semantic-release --dry-run   # needs a GITHUB_TOKEN in the environment
```

## Pull requests & CI

- Open PRs against `main`. Direct pushes to `main` are disabled.
- [`ci.yml`](.github/workflows/ci.yml) build-and-tests only the areas your PR
  touches (`vector-rs`, `sonar`) and rolls up into a single **`ci-success`**
  check.
- **`ci-success`** and **`commitlint`** must be green before a PR can merge
  (enforced by branch protection on `main`).

## Branch protection (maintainers)

Branch protection is configured in GitHub repo settings, not in the repo.
On `main`, enable: *Require a pull request before merging*, *Require status
checks to pass* → select **`ci-success`** and **`commitlint`**, and disallow
direct pushes / bypasses. Both required checks run on every PR, so they always
report and never leave a merge blocked on a check that didn't run.
