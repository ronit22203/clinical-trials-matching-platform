# CI Pipeline — How It Works

This document explains the CI setup in `.github/workflows/ci.yml`: what it does, why
it's shaped the way it is, and how to work with it day-to-day. Written for anyone
new to CI/GitHub Actions — no prior knowledge assumed.

---

## 1. What CI actually is

**CI = Continuous Integration.** Every time someone proposes a change (opens or
updates a Pull Request), GitHub automatically runs a set of checks — lint and tests —
on a brand-new, clean virtual machine. This happens *before* a human reviews the
code, and *before* anything merges into `main`.

The goal: catch broken code automatically, consistently, every time — instead of
relying on someone remembering to run tests locally before merging.

**Key mental model:** each CI run happens on a machine that starts completely empty.
It has no idea your repo exists, no Python packages installed, nothing. Every job
starts from scratch — this is intentional. It's what guarantees "if CI passes, it'll
work for anyone," not just "it works on my machine."

---

## 2. The building blocks

| Term | What it means |
|---|---|
| **Workflow** | The whole `.github/workflows/ci.yml` file — instructions for what to run and when |
| **Trigger** (`on:`) | What causes the workflow to run — here: opening/updating a PR, or pushing to `main` |
| **Job** | One unit of work, run on its own fresh VM. Our workflow has 4: `changes`, `python-lint-test`, `ui-lint-build`, `ci-summary` |
| **Step** | One command inside a job, run top to bottom. If a step fails, the job stops there |
| **Action** (`uses:`) | A reusable, pre-built step someone else wrote (e.g. `actions/checkout@v4` clones your repo onto the fresh VM) |
| **`needs:`** | How one job waits for and reads output from another |

---

## 3. What each job does, and why

### `changes` — figures out what actually changed
Uses `dorny/paths-filter` to check the PR's diff and answer: did anything under
`data-acquisition/`, `data-ingestion/`, or `agentic-reasoning/` change? Did anything
under `palantir-blueprint/` change? This produces true/false flags the other jobs
read to decide whether they need to run at all.

**Why this exists:** this is a monorepo with a Python backend and a separate
Next.js frontend. Running the full Python test suite on a PR that only touched the
UI would be slow and pointless — path filtering keeps CI fast by only running what's
relevant to the actual change.

### `python-lint-test` — checks each Python module independently
Runs as a **matrix**: one independent leg per module (`data-acquisition`,
`data-ingestion`, `agentic-reasoning`). Each leg:
1. Checks out the repo
2. `cd`s into its own module directory (`working-directory:`) — critical, because
   each module has its own `src/` folder; running from the repo root breaks all
   the imports
3. Installs that module's dependencies
4. Runs `ruff check .` (lint)
5. Runs `pytest -m "not integration" --tb=short` (tests, excluding anything that
   needs live cloud credentials)

Each leg only runs if `paths-filter` detected a change in that specific module
(`fail-fast: false` means one module failing doesn't cancel the others — they're
independent, so their results should be too).

### `ui-lint-build` — checks the frontend
Runs `npm ci --legacy-peer-deps` and `npm run build` inside `palantir-blueprint/`
(this repo's actual UI folder — historically misnamed `platform-ui` in an earlier
version of this file; if you ever see that name again, it's stale).

There's no separate `npm run lint` step because this project's `package.json`
doesn't define one — `npm run build` already runs `tsc && vite build`, which
covers TypeScript type-checking, the main thing you'd want caught early anyway.

`--legacy-peer-deps` exists because `@blueprintjs/core` currently declares a peer
dependency on React 18 types, while this project uses React 19 types. This is a
known upstream lag in Blueprint's package metadata, not a bug in this repo — safe
to keep until Blueprint updates their peer dependency declaration.

### `ci-summary` — the one check to actually require
Runs `if: always()`, meaning it runs regardless of whether the jobs above ran,
passed, skipped, or failed. It checks: did anything that *did* run actually fail?
If yes, it fails too. If everything either passed or was correctly skipped, it
passes.

**Why this exists — the single most important design detail in this file:**
Branch protection (see below) needs to require *some* check before allowing a
merge. If you require `python-lint-test` directly, a PR that only touches the UI
will never trigger that job — GitHub will show it stuck as "pending" forever, and
the PR can never merge. `ci-summary` always runs, so it's always available to
require, regardless of what the PR actually touched.

---

## 4. Local vs CI — how to reproduce a CI failure on your machine

**Always match CI's working directory.** CI runs Python checks from *inside* each
module's own folder, never from the repo root. Do the same locally:

```bash
# Correct — matches what CI does
cd data-acquisition
ruff check .
pytest -m "not integration" --tb=short

# Wrong — will show unrelated failures from every module at once,
# and pytest import errors, because each module's src/ isn't visible
# from the repo root
cd ~/Developer/healthcare-platform
ruff check .        # scans everything, not just one module
pytest              # ModuleNotFoundError: No module named 'src.storage'
```

If you ever see a wall of `ModuleNotFoundError` errors mentioning `src.something`,
the near-universal cause is: you ran `pytest` from the wrong directory. `cd` into
the specific module first.

---

## 5. The `integration` marker — why some tests don't run in CI

Some tests need real infrastructure — live AWS/Azure credentials, a running Neo4j
or Qdrant instance, etc. CI has none of these, by design (a clean, credential-free
environment is what makes CI fast and safe to run on every PR from anyone).

Tests that need real infra are marked:

```python
@pytest.mark.integration
class TestS3BucketOperations:
    ...
```

or for a single test:

```python
@pytest.mark.integration
def test_connection_string_format(self, azure_blob_config):
    ...
```

CI runs `pytest -m "not integration"`, which skips anything marked this way. These
tests still exist and can be run manually, or in a future dedicated
"integration tests" workflow that has real credentials injected as secrets.

**If you add a new test that needs live credentials or a running service, mark it
`@pytest.mark.integration` immediately** — otherwise it'll fail in CI for everyone,
every time, since CI has no way to give it what it needs.

---

## 6. Branch protection — what it does and why it matters

As of this writing, `main` has **no branch protection** — anyone (including a
stray `git push --force`) can push directly to it, no checks required, no review
required. This is the next thing to set up, and it should happen once CI is fully
green on a real PR (proving there's something meaningful to require).

Once configured, branch protection means:
- No one can push directly to `main` — all changes go through a PR
- The PR can't merge until `ci-summary` passes
- (Optionally) at least one review is required before merging

To set this up: **Settings → Branches → Add branch protection rule** on GitHub,
targeting `main`, requiring the `ci-summary` status check.

---

## 7. Merge strategies — squash vs. merge commit vs. rebase

GitHub offers three ways to merge a PR:

- **Squash and merge** (recommended default for this repo): collapses every commit
  in the PR — including any "merge main into my branch" catch-up commits and
  fixup commits — into a single clean commit on `main`. Keeps `main`'s history
  readable: one entry per PR, not a blow-by-blow of every intermediate fix.
- **Create a merge commit**: preserves every commit from the branch, plus adds a
  merge commit. Most "honest" record of what happened, but noisy — catch-up
  merges and small fixup commits become permanent parts of `main`'s history.
- **Rebase and merge**: replays each commit individually onto `main`, no merge
  commit, fully linear history. Gets confusing if the branch itself contains a
  merge commit (e.g. from syncing with `main` mid-PR) — avoid this option for
  branches that have done that.

**This repo's convention: squash and merge**, unless a PR is small enough and
clean enough that preserving individual commits adds real value.

---

## 8. Common failure patterns and what they actually mean

| Symptom | Likely cause |
|---|---|
| `ModuleNotFoundError: No module named 'src.X'` | Ran pytest from repo root instead of the module's own directory |
| Ruff errors in files you never touched | Pre-existing lint debt in a module CI is checking for the first time — not caused by your change |
| `AttributeError: module 'collections' has no attribute 'Callable'` | Old `python-dateutil` version (pre-2.8.1) hit via `botocore`; upgrade the package, not the source code |
| A specific matrix leg (e.g. `data-acquisition`) runs even though you only touched `data-ingestion` | Check whether your branch has changes across multiple modules — the matrix runs per-module based on actual diffs, not assumptions |
| A required check stuck on "pending" forever | Branch protection is requiring a job that got path-filtered out for this PR — require `ci-summary` instead of an individual job |
| `ERESOLVE` npm error | Peer dependency version mismatch (e.g. Blueprint vs React version) — usually needs `--legacy-peer-deps`, confirm it's not masking a real incompatibility first |

---

## 9. Adding a new module or changing paths

If you add a new top-level Python module or rename an existing folder:

1. Add it to the `paths-filter` config in the `changes` job (both the trigger path
   and, if it's Python, the matrix list in `python-lint-test`)
2. Add it to the `matrix.module` list if it's a Python module with its own
   `requirements.txt`/`pyproject.toml` and `tests/`
3. If it's a frontend folder, update `ui-lint-build`'s `working-directory` and
   `cache-dependency-path`

Forgetting this step is exactly what happened with `palantir-blueprint/` initially
being misconfigured as `platform-ui/` — the folder existed, CI just wasn't looking
at the right name for it, so it silently skipped every UI PR's actual checks.
