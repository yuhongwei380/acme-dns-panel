#!/usr/bin/env bash
# Sourced by install.sh. Never change the system's python3 symlink.
select_panel_python() {
  local candidate
  if [[ -n "${ACME_PANEL_PYTHON:-}" ]]; then
    candidate="$ACME_PANEL_PYTHON"
    if ! command -v "$candidate" >/dev/null || ! "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' >/dev/null 2>&1; then
      echo "指定的 Python 不可用或版本低于 3.8：$candidate" >&2
      return 1
    fi
    PYTHON_BIN="$(command -v "$candidate")"
    return 0
  fi
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "$candidate")"
      return 0
    fi
  done
  echo '未找到 Python 3.8+。请先安装兼容版本，或通过 ACME_PANEL_PYTHON=/usr/bin/python3.12 指定解释器。' >&2
  return 1
}
