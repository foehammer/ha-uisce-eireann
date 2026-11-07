# Releasing

Versions follow [Semantic Versioning](https://semver.org):

- **PATCH** (0.1.0 → 0.1.1): bug fixes only.
- **MINOR** (0.1.0 → 0.2.0): new features that don't break existing setups.
- **MAJOR** (0.x → 1.0.0, then 1.x → 2.0.0): breaking changes, such as renamed entities or removed options. While the version is below 1.0.0, breaking changes may also go in a MINOR release.

## While developing

Add a line under `## [Unreleased]` in `CHANGELOG.md` as part of every change that users would notice. Use the headings **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed** and **Security**.

## To release

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty `## [Unreleased]` above it, and update the links at the bottom of the file.
2. Set `"version": "X.Y.Z"` in `custom_components/uisce_eireann/manifest.json`.
3. Commit, for example `Release X.Y.Z`, and push to `main`.
4. Tag and push the tag:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The **Release** workflow then checks that the tag matches the manifest version and has a changelog entry, and publishes a GitHub release using that entry as its notes. If a check fails, nothing is published: fix the problem, delete the tag (`git push --delete origin vX.Y.Z` and `git tag -d vX.Y.Z`), and tag again.

HACS offers an update to users once a release is published.
