"""Package init for the engine app."""
# Keep in lockstep with engine/pyproject.toml [project] version, the root
# package.json and desktop/src-tauri/tauri.conf.json. It drifted to 1.2.6
# across the v1.2.7/v1.2.8 releases, so /health and diagnostics reported a
# stale engine version in the field (caught during the v1.2.8 rebuild E2E).
__version__ = "1.2.9"
