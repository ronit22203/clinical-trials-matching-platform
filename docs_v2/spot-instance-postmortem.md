# Spot Instance Startup Postmortem

## Summary

We were able to bring up the platform's **infrastructure and partial application stack**, but we did **not** reach a fully runnable production environment on this spot instance.

Successful components:

- Qdrant on `:6333`
- Neo4j on `:7474`
- agentic-reasoning API on `:8000`
- palantir-blueprint production preview on `:4173`

Blocked components:

- `core-llm-inference` / SGLang on `:30000`
- `data-ingestion` runtime / API on `:8001`

The main wall was **environment and package footprint**, not missing source code. This machine has a small root filesystem, while the production install path writes Python virtual environments, pip temp files, and large CUDA/Torch wheels to that root volume.

---

## Environment observed

At the time of the stop decision:

- root filesystem: `20G` total, `18G` used, `2.1G` free
- workspace mount: very large and healthy, but not used by the default install targets for venv/temp/cache placement

Service health checks were good for the components that did start:

- `http://localhost:8000/docs` → `200`
- `http://localhost:4173` → `200`
- `http://localhost:6333/collections` → `200`
- `http://localhost:7474` → `200`

---

## What worked

### 1. Infrastructure startup

The production startup path in `docs_v2/prod-startup.md` correctly points operators toward native service startup for Qdrant and Neo4j on Ubuntu/L4 machines. In practice, both services came up and stayed healthy.

### 2. Reasoning API

The reasoning API was started successfully and served FastAPI docs on port `8000`.

### 3. Production UI

The React production bundle built and previewed successfully on port `4173`.

These results show that the repository, service topology, and baseline machine access were all workable. The failure was in the heavyweight runtime-install path that remained.

---

## Where we hit the wall

### 1. Python version assumptions are brittle in the install targets

`agentic-reasoning` and `core-llm-inference` both declare `requires-python = ">=3.12"` in their package metadata, but the root `Makefile` uses host interpreter assumptions during venv creation instead of pinning the matching interpreter everywhere.

- `agentic-reasoning/pyproject.toml` requires Python `>=3.12`
- `core-llm-inference/pyproject.toml` requires Python `>=3.12`
- `Makefile` creates `agentic-reasoning/.venv` with `python3 -m venv .venv`

On a machine where `python3` resolves to `3.11`, that target is fragile immediately.

### 2. `inference-install` is too large for a small root volume

The root `Makefile` defines `inference-install` as:

1. create `.venv` under `core-llm-inference/`
2. install `torch` from the CUDA 12.4 index
3. install `sglang[all]`
4. install the package itself

That path downloads and expands multi-GB GPU packages into the local venv and pip temp/cache locations. On this machine, those installs repeatedly failed with storage exhaustion instead of reaching a runnable SGLang server.

Observed errors during install attempts included:

- `ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device`
- `ERROR: Could not install packages due to an OSError: [Errno 122] Disk quota exceeded`

### 3. `data-ingestion` pulls an unexpectedly heavy Torch/CUDA chain

`data-ingestion/requirements.txt` includes:

- `marker-pdf==1.10.1`

During resolution, that package pulled:

- `torch<3.0.0,>=2.7.0`
- CUDA 13 component packages

The install log showed pip proceeding toward a very large GPU download set, including:

- `torch-2.12.0-...whl`
- multiple NVIDIA CUDA runtime libraries

That meant ingestion was not a lightweight API install on this host; it was another GPU-heavy environment build that also exhausted local storage.

### 4. The production docs assume a happier host than the real one

`docs_v2/prod-startup.md` describes `bash scripts/pre_requisites.sh` and the follow-up make targets as the standard production path, including:

- reasoning venv creation
- ingestion dependency install
- inference venv + torch + `sglang[all]`

That flow is directionally correct, but it assumes the machine can absorb the full package footprint on its local writable filesystem. This spot instance could not.

---

## Root cause

The root cause was a **mismatch between repository startup assumptions and this instance's writable storage profile**.

More specifically:

1. the install targets place venvs under the repo and use default pip temp/cache locations
2. the remaining blocked services require very large GPU-oriented Python dependencies
3. the root overlay filesystem is only `20G`, with little free space left during installation
4. the larger `/workspace` mount was available, but the default startup targets do not redirect package installation, temp, or cache usage there

This was enough to let lightweight components start, but not enough to complete the last-mile runtime installation for inference and ingestion.

---

## Impact

We did **not** achieve a full production-ready machine image from this session.

What we did achieve:

- validated that the repo can partially boot on this host
- confirmed that infrastructure and UI/reasoning surfaces are reachable
- isolated the failure to install/runtime-footprint issues rather than network reachability or missing code paths

Why we are stopping here:

- continuing on this exact spot instance is likely to repeat the same storage failures
- the remaining work is environmental, not exploratory
- termination is reasonable once the blockers are documented for the next attempt

---

## Recommendations for the next machine

1. Use an image or startup process that guarantees:
   - Python `3.12` for `agentic-reasoning` and `core-llm-inference`
   - enough local writable storage for large CUDA/Torch/SGLang installs

2. Redirect heavyweight install paths to `/workspace`, including:
   - pip cache
   - pip temp directory
   - any large model / wheel staging directories

3. Split the bootstrap path into:
   - infrastructure and lightweight app startup
   - heavyweight GPU runtime provisioning

4. Revisit `data-ingestion` packaging expectations:
   - if the production host only needs the ingestion API occasionally, avoid forcing the full OCR/GPU stack during first boot
   - consider a lighter runtime profile or prebuilt image for `marker-pdf` + Torch dependencies

5. Make the interpreter requirement explicit in root orchestration:
   - avoid generic `python3 -m venv` for packages that require `>=3.12`

---

## Key evidence

- `docs_v2/prod-startup.md`
- `Makefile`
- `agentic-reasoning/pyproject.toml`
- `core-llm-inference/pyproject.toml`
- `data-ingestion/requirements.txt`
- session install logs showing `No space left on device` / `Disk quota exceeded`

---

## Final decision

This spot instance was good enough to prove partial startup, but not good enough to finish the full production install path safely and repeatably.

Terminating it after preserving this postmortem is the right call.
