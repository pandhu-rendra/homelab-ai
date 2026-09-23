@echo off
:: Shortcut commands that restore the caller's directory after HomeLab AI exits.
doskey agent=pushd D:\project\homelab-ai ^& "D:\project\homelab-ai\.venv\Scripts\python.exe" -m homelab_ai $* ^& popd
doskey homelab=pushd D:\project\homelab-ai ^& "D:\project\homelab-ai\.venv\Scripts\python.exe" -m homelab_ai $* ^& popd