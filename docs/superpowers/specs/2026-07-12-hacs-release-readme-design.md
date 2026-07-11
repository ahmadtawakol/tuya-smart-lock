# HACS Release and README Design

**Date:** 2026-07-12

## Objective

Make the Tuya Smart Lock integration immediately installable as a HACS custom
repository, document that installation accurately, and publish the existing
integration version `1.1.0` as GitHub release `v1.1.0` after all local and
GitHub validation checks pass.

Submission to the HACS default catalog is not part of this change.

## Current State

- The repository is public and its default branch contains one integration at
  `custom_components/tuya_smart_lock`.
- `hacs.json` and the integration manifest already contain the required HACS
  metadata, and HACS validation passes on GitHub.
- The manifest version is `1.1.0`, but no `v1.1.0` GitHub release exists.
- The README still says the integration is not installable from HACS, even
  though the implementation is now on the default branch.
- Hassfest fails because the setup description embeds a Markdown URL directly
  in `strings.json` and `translations/en.json`. Home Assistant requires URLs in
  config-flow text to be supplied through description placeholders.

## Chosen Approach

Use the repository's standard custom-integration layout directly. Do not build
or attach a ZIP archive. HACS will install
`custom_components/tuya_smart_lock` from the GitHub release. A real release is
preferred over a default-branch-only install because it gives users a stable
semantic version and a clear upgrade target.

## Home Assistant Translation Fix

The user-step description will retain the Tuya IoT Platform link, but replace
the literal URL with a named placeholder. Both `strings.json` and
`translations/en.json` will use the same placeholder name and Markdown link
syntax.

`config_flow.py` will pass the fixed public Tuya URL in
`description_placeholders` whenever it renders the user credentials form,
including normal setup and any recovery path that returns to that form. The
placeholder value is a constant controlled by the integration, never user or
API data.

This resolves Hassfest without changing the credentials, validation, or error
handling behavior.

## HACS Installation Documentation

The README installation section will lead with HACS as the recommended method.
It will include:

1. A one-click My Home Assistant link that opens the HACS custom-repository
   flow for `ahmadtawakol/tuya-smart-lock` as an integration.
2. Manual custom-repository steps as a fallback:
   - open HACS;
   - open custom repositories;
   - add the repository URL with category **Integration**;
   - install **Tuya Smart Lock**;
   - restart Home Assistant;
   - add the integration from **Settings > Devices & services**.
3. A clear minimum Home Assistant requirement of `2026.7.2`.
4. A short upgrade note explaining that future published releases appear as
   HACS updates.
5. A manual installation section retained as a fallback.

The stale statements that the branch is unpublished or not installable will be
removed. The README must not claim inclusion in HACS's default catalog.

## Release

After the branch is merged or fast-forwarded to `main` and pushed:

1. Wait for the GitHub **Tests**, **HACS**, and **Hassfest** jobs for the exact
   release commit to pass.
2. Create annotated tag `v1.1.0` at that verified commit.
3. Publish a non-draft, non-prerelease GitHub release named `v1.1.0`.
4. Include concise release notes covering videolock lock/unlock control,
   physical-state confirmation, battery and duress telemetry, event entities,
   credential reauthentication, and HACS installation.
5. Confirm that the public release and tag resolve to the same commit and that
   the repository remains clean.

The release must not be created if any required GitHub job fails. No release
asset is required because HACS supports the standard integration directory
layout directly.

## Testing and Verification

Automated regression coverage will verify:

- the setup description contains the expected placeholder instead of a raw
  URL;
- `config_flow.py` supplies the exact safe placeholder value on every user-form
  rendering path;
- `strings.json` and `translations/en.json` remain synchronized;
- the README contains the correct repository URL, HACS category, minimum Home
  Assistant version, restart/setup steps, and no stale unpublished warning;
- the manifest version and planned release tag remain aligned at `1.1.0` and
  `v1.1.0`.

Before publication, run the complete pytest suite, Ruff lint and format checks,
`git diff --check`, HACS validation, and Hassfest. GitHub validation must then
pass on the pushed release commit before tagging.

## Safety and Rollback

- No device behavior, Tuya API behavior, credentials, or stored config-entry
  data changes.
- No secrets or private device/account identifiers are added to documentation,
  tests, release notes, or logs.
- If validation fails after push, fix it in a new commit and wait for the new
  exact commit to pass before releasing.
- If the published release is found to be defective, do not move the tag;
  publish a new patch version instead.
