# HACS Release and README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Tuya Smart Lock installable as a release-backed HACS custom repository, document installation accurately, and publish verified release `v1.1.0`.

**Architecture:** Keep the standard HACS integration layout and serve it directly from a GitHub release. Fix the known Hassfest failure by routing the public Tuya URL through a config-flow description placeholder, then make the README custom-repository flow the recommended installation path. Treat GitHub CI for the exact `main` commit as a hard gate before creating the tag and release.

**Tech Stack:** Home Assistant config flows, Python 3.14, pytest, Ruff, JSON translations, Markdown, HACS validation, Hassfest, Git, GitHub Actions, GitHub CLI.

---

## File Responsibility Map

- `custom_components/tuya_smart_lock/const.py`: fixed public Tuya URL.
- `custom_components/tuya_smart_lock/config_flow.py`: safe form placeholders.
- `custom_components/tuya_smart_lock/strings.json`: canonical source strings.
- `custom_components/tuya_smart_lock/translations/en.json`: synchronized English translation.
- `tests/test_config_flow.py`: config-flow placeholder behavior.
- `tests/test_manifest_and_translations.py`: translation, HACS, README, and release contracts.
- `README.md`: user-facing HACS and manual installation instructions.

## Task 1: Fix the Hassfest Translation Contract

**Files:**
- Modify: `tests/test_config_flow.py:18-26,127-143,360-427,497-516`
- Modify: `tests/test_manifest_and_translations.py:82-119`
- Modify: `custom_components/tuya_smart_lock/const.py:5-20`
- Modify: `custom_components/tuya_smart_lock/config_flow.py:11-18,64-79`
- Modify: `custom_components/tuya_smart_lock/strings.json:3-11`
- Modify: `custom_components/tuya_smart_lock/translations/en.json:3-11`

- [ ] **Step 1: Write failing config-flow placeholder tests**

Import a not-yet-defined constant:

```python
from custom_components.tuya_smart_lock.const import TUYA_IOT_PLATFORM_URL
```

First assert the constant itself, then compare form output with the literal so
an incorrect production constant cannot make the test pass:

```python
assert TUYA_IOT_PLATFORM_URL == "https://iot.tuya.com"
assert result["description_placeholders"] == {
    "tuya_iot_url": "https://iot.tuya.com"
}
```

Add these assertions to all five existing user-form tests:

- `test_user_step_shows_credentials_form`
- `test_credential_failure_shows_actionable_safe_error`
- `test_token_endpoint_outage_is_cannot_connect_not_invalid_auth`
- `test_discovery_failure_returns_to_user_with_actionable_safe_error`
- `test_remote_auth_failure_restarts_with_corrected_credentials`

- [ ] **Step 2: Write the failing translation contract test**

Add to `tests/test_manifest_and_translations.py`:

```python
def test_user_description_uses_safe_tuya_url_placeholder() -> None:
    strings = _load_json(INTEGRATION / "strings.json")
    english = _load_json(INTEGRATION / "translations" / "en.json")
    expected = (
        "Enter your Tuya IoT Platform credentials.\n\n"
        "You need an active **IoT Core** and **Smart Lock Open Service** "
        "subscription on [iot.tuya.com]({tuya_iot_url})."
    )
    assert strings["config"]["step"]["user"]["description"] == expected
    assert english["config"]["step"]["user"]["description"] == expected
    assert "https://" not in expected
```

- [ ] **Step 3: Run the focused tests and observe RED**

```bash
.venv/bin/python -m pytest \
  tests/test_config_flow.py::test_user_step_shows_credentials_form \
  tests/test_config_flow.py::test_credential_failure_shows_actionable_safe_error \
  tests/test_config_flow.py::test_token_endpoint_outage_is_cannot_connect_not_invalid_auth \
  tests/test_config_flow.py::test_discovery_failure_returns_to_user_with_actionable_safe_error \
  tests/test_config_flow.py::test_remote_auth_failure_restarts_with_corrected_credentials \
  tests/test_manifest_and_translations.py::test_user_description_uses_safe_tuya_url_placeholder \
  -q
```

Expected: collection or assertions fail because the constant and placeholder
do not exist and the literal URL remains.

- [ ] **Step 4: Add the fixed URL constant**

Add to `const.py`:

```python
TUYA_IOT_PLATFORM_URL = "https://iot.tuya.com"
```

- [ ] **Step 5: Supply it from the shared user-form helper**

Import the constant and update `_show_user_form`:

```python
return self.async_show_form(
    step_id="user",
    data_schema=vol.Schema(...),
    errors=errors or {},
    description_placeholders={"tuya_iot_url": TUYA_IOT_PLATFORM_URL},
)
```

Do not change `_show_reauth_form`; it uses only the existing `name` placeholder.

- [ ] **Step 6: Replace the literal URL in both JSON files**

Use this exact value in both files:

```json
"Enter your Tuya IoT Platform credentials.\n\nYou need an active **IoT Core** and **Smart Lock Open Service** subscription on [iot.tuya.com]({tuya_iot_url})."
```

- [ ] **Step 7: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_config_flow.py tests/test_manifest_and_translations.py -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
git diff --check
git add custom_components/tuya_smart_lock/const.py \
  custom_components/tuya_smart_lock/config_flow.py \
  custom_components/tuya_smart_lock/strings.json \
  custom_components/tuya_smart_lock/translations/en.json \
  tests/test_config_flow.py tests/test_manifest_and_translations.py
git commit -m "fix: satisfy Hassfest URL translation rules"
```

Expected: focused tests and static checks pass; commit succeeds.

## Task 2: Publish Accurate HACS Installation Documentation

**Files:**
- Modify: `tests/test_manifest_and_translations.py:20-53,185-end`
- Modify: `README.md:1-115`

- [ ] **Step 1: Write the failing README/HACS contract test**

```python
HACS_MY_LINK = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=ahmadtawakol&repository=tuya-smart-lock&category=integration"
)


def test_readme_documents_release_backed_hacs_installation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert HACS_MY_LINK in readme
    assert "https://my.home-assistant.io/badges/hacs_repository.svg" in readme
    assert REPOSITORY in readme
    assert "**Integration**" in readme
    assert "Home Assistant 2026.7.2 or newer" in readme
    assert "Restart Home Assistant" in readme
    assert "Settings > Devices & services" in readme
    assert "Future published releases appear as updates in HACS" in readme
    assert "not installable from HACS yet" not in readme
    assert "Neither default-branch publication" not in readme
    assert "HACS default" not in readme
```

Extend the manifest metadata test:

```python
assert f"v{manifest['version']}" == "v1.1.0"
```

- [ ] **Step 2: Run the new test and observe RED**

```bash
.venv/bin/python -m pytest \
  tests/test_manifest_and_translations.py::test_readme_documents_release_backed_hacs_installation \
  tests/test_manifest_and_translations.py::test_manifest_describes_release_and_fork_ownership \
  -q
```

Expected: README assertions fail because the one-click link and upgrade wording
are absent and stale publication wording remains.

- [ ] **Step 3: Rewrite the README installation section**

Make HACS the recommended method:

```markdown
## Installation

### HACS custom repository (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ahmadtawakol&repository=tuya-smart-lock&category=integration)

1. Verify Home Assistant 2026.7.2 or newer is installed.
2. Use the button above, or open HACS, select **Custom repositories**, add
   `https://github.com/ahmadtawakol/tuya-smart-lock`, and choose
   **Integration**.
3. Install **Tuya Smart Lock**.
4. Restart Home Assistant.
5. Open **Settings > Devices & services > Add integration** and select
   **Tuya Smart Lock**.

Future published releases appear as updates in HACS.
```

Retain manual installation as fallback. Remove branch/release planning language
and all stale not-installable claims. Do not claim HACS default-catalog inclusion.

- [ ] **Step 4: Re-read the README for one coherent journey**

Confirm this order: purpose, hardware, entities, prerequisites, recommended
HACS installation, manual fallback, configuration, runtime behavior,
troubleshooting, and support. Remove duplicated steps and internal terminology.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_manifest_and_translations.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
git diff --check
git add README.md tests/test_manifest_and_translations.py
git commit -m "docs: publish HACS installation guide"
```

Expected: full tests and static checks pass; commit succeeds.

## Task 3: Validate, Merge, and Publish `v1.1.0`

**Files:**
- No source-file changes expected.
- Git/GitHub state: `main`, `origin/main`, annotated tag `v1.1.0`, and GitHub release `v1.1.0`.

- [ ] **Step 1: Audit the feature branch**

```bash
set -euo pipefail
git status --short --branch
git log --oneline origin/main..HEAD
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
git diff --check origin/main...HEAD
if git show-ref --verify --quiet refs/tags/v1.1.0; then
  echo "Local tag v1.1.0 already exists; aborting" >&2
  exit 1
fi
REMOTE_TAG=$(git ls-remote --tags origin refs/tags/v1.1.0)
if [ -n "$REMOTE_TAG" ]; then
  echo "Remote tag v1.1.0 already exists; aborting" >&2
  exit 1
fi
RELEASE_TAGS=$(gh release list \
  --repo ahmadtawakol/tuya-smart-lock \
  --limit 100 \
  --json tagName \
  --jq '.[].tagName')
if printf '%s\n' "$RELEASE_TAGS" | grep -Fxq v1.1.0; then
  echo "GitHub release v1.1.0 already exists; aborting" >&2
  exit 1
fi
```

Expected: clean worktree, green checks, and no local tag, remote tag, or GitHub
release. Any existing tag or release is a blocker and must not be overwritten.

- [ ] **Step 2: Fast-forward local `main` and reverify**

```bash
git switch main
git pull --ff-only origin main
git merge --ff-only codex/hacs-release-readme
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
git diff --check origin/main...HEAD
```

Expected: fast-forward and green checks. If `main` changed and fast-forward is
impossible, stop and reconcile on the feature branch; do not create an
unreviewed merge commit.

- [ ] **Step 3: Push and record the exact release SHA**

```bash
set -euo pipefail
git push origin main
git fetch origin main
RELEASE_SHA=$(git rev-parse HEAD)
test "$RELEASE_SHA" = "$(git rev-parse origin/main)"
git update-ref refs/codex/hacs-release-candidate "$RELEASE_SHA"
test "$RELEASE_SHA" = "$(git rev-parse refs/codex/hacs-release-candidate)"
```

Expected: push succeeds, `HEAD` equals `origin/main`, and the exact candidate
SHA is persisted as the private local Git ref
`refs/codex/hacs-release-candidate`. Later steps load this immutable candidate
instead of trusting a recomputed `HEAD`.

- [ ] **Step 4: Wait for all required jobs on that exact SHA**

```bash
set -euo pipefail
git fetch origin main
RELEASE_SHA=$(git rev-parse refs/codex/hacs-release-candidate)
test "$RELEASE_SHA" = "$(git rev-parse HEAD)"
test "$RELEASE_SHA" = "$(git rev-parse origin/main)"
RUN_ID=""
for _ in {1..30}; do
  RUN_ID=$(gh run list \
    --repo ahmadtawakol/tuya-smart-lock \
    --workflow tests.yml \
    --commit "$RELEASE_SHA" \
    --event push \
    --limit 5 \
    --json databaseId,headSha \
    --jq '.[0].databaseId // empty')
  if [ -n "$RUN_ID" ]; then
    break
  fi
  sleep 2
done
test -n "$RUN_ID"
gh run watch "$RUN_ID" \
  --repo ahmadtawakol/tuya-smart-lock \
  --exit-status
test "$(gh run view "$RUN_ID" \
  --repo ahmadtawakol/tuya-smart-lock \
  --json headSha --jq '.headSha')" = "$RELEASE_SHA"
test "$(gh run view "$RUN_ID" \
  --repo ahmadtawakol/tuya-smart-lock \
  --json conclusion --jq '.conclusion')" = "success"
for JOB in test hacs hassfest; do
  test "$(gh run view "$RUN_ID" \
    --repo ahmadtawakol/tuya-smart-lock \
    --json jobs \
    --jq ".jobs[] | select(.name == \"$JOB\") | .conclusion")" = "success"
done
```

Expected: matching `headSha`, overall `success`, and successful jobs named
`test`, `hacs`, and `hassfest`. On any failure, diagnose, fix in a new commit,
repeat all gates with the new SHA, and never release the failed SHA.

- [ ] **Step 5: Create and push the annotated tag**

```bash
set -euo pipefail
git fetch origin main
RELEASE_SHA=$(git rev-parse refs/codex/hacs-release-candidate)
test "$(git branch --show-current)" = "main"
test "$RELEASE_SHA" = "$(git rev-parse HEAD)"
test "$RELEASE_SHA" = "$(git rev-parse origin/main)"
if git show-ref --verify --quiet refs/tags/v1.1.0; then
  echo "Local tag v1.1.0 already exists; aborting" >&2
  exit 1
fi
REMOTE_TAG=$(git ls-remote --tags origin refs/tags/v1.1.0)
if [ -n "$REMOTE_TAG" ]; then
  echo "Remote tag v1.1.0 already exists; aborting" >&2
  exit 1
fi
RELEASE_TAGS=$(gh release list \
  --repo ahmadtawakol/tuya-smart-lock \
  --limit 100 \
  --json tagName \
  --jq '.[].tagName')
if printf '%s\n' "$RELEASE_TAGS" | grep -Fxq v1.1.0; then
  echo "GitHub release v1.1.0 already exists; aborting" >&2
  exit 1
fi
git tag -a v1.1.0 "$RELEASE_SHA" -m "Tuya Smart Lock v1.1.0"
git push origin v1.1.0
```

- [ ] **Step 6: Publish the GitHub release**

```bash
gh release create v1.1.0 \
  --repo ahmadtawakol/tuya-smart-lock \
  --verify-tag \
  --title "Tuya Smart Lock v1.1.0" \
  --notes $'First release of the videolock control and telemetry update.\n\n- Add confirmed lock and unlock control through Tuya Smart Lock Open Service.\n- Add battery, duress, doorbell, inside-open, alarm, and unlock event entities.\n- Add safe credential reauthentication and typed command errors.\n- Add release-backed installation through a HACS custom repository.\n\nRequires Home Assistant 2026.7.2 or newer.'
```

Expected: non-draft, non-prerelease release with no ZIP asset.

- [ ] **Step 7: Verify release integrity and clean up**

```bash
set -euo pipefail
git fetch origin main
RELEASE_SHA=$(git rev-parse refs/codex/hacs-release-candidate)
test "$RELEASE_SHA" = "$(git rev-parse HEAD)"
test "$RELEASE_SHA" = "$(git rev-parse origin/main)"
gh release view v1.1.0 --repo ahmadtawakol/tuya-smart-lock \
  --json url,tagName,isDraft,isPrerelease,targetCommitish
git fetch origin tag v1.1.0
test "$RELEASE_SHA" = "$(git rev-list -n 1 v1.1.0)"
git status --short --branch
git branch -d codex/hacs-release-readme
git update-ref -d refs/codex/hacs-release-candidate
```

Expected: published `v1.1.0`, tag dereferences to `RELEASE_SHA`, clean synced
`main`, and the merged feature branch is deleted. Never move the release tag;
publish a later patch version if a release defect is discovered.
