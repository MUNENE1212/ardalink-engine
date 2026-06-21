# Phase 0.5 — Pre-Restructure Backup

**Created**: 2026-06-21T19:40:26Z
**Status**: ✅ verified

## Artifact

- Path: `~/ardalink-backups/ardalink-pre-restructure-20260621T194026Z.tar.gz`
- Size: 34 MB
- SHA-256: `0c94bca6eab2d4e896040ee2b56da31aefc62a1332bb74789f028605e37133eb`
- Files: 57

## Restore

1. Extract: `tar -xzf ardalink-pre-restructure-*.tar.gz`
2. `git clone ardalink-pre-restructure/git/ardalink-ai.bundle ardalink-ai-legacy`
3. `git clone ardalink-pre-restructure/git/biophysical-engine.bundle biophysical-engine-legacy`
4. Apply working-tree patches from `working-tree-snapshot/`
5. Verify: `sha256sum -c manifests/file-manifest.sha256`

## Purge (post-cutover)

```bash
rm -rf ~/ardalink-backups/ardalink-pre-restructure-*
```