#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_LOG="$ROOT_DIR/logs/bootstrap.log"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "このツールは Ubuntu 24.04 上での利用を前提にしています。"
  echo "Linux 環境で ./start.sh を実行してください。"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 が見つかりません。Ubuntu 側で python3 を導入してから再実行してください。"
  exit 1
fi

mkdir -p "$ROOT_DIR/.state" "$ROOT_DIR/cache" "$ROOT_DIR/logs" "$ROOT_DIR/workspace"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
RUNNER=(python3)

install_python_bootstrap_packages() {
  if [[ ! -f /etc/os-release ]] || ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    return 1
  fi
  echo "python3-venv / python3-pip を自動導入します。sudo パスワードを求められたら入力してください。"
  {
    echo "[$(date -Is)] installing python bootstrap packages"
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip
  } >>"$BOOTSTRAP_LOG" 2>&1
}

create_or_refresh_venv() {
  if ! python3 -m venv "$VENV_DIR" >>"$BOOTSTRAP_LOG" 2>&1; then
    return 1
  fi
  if ! "$VENV_PYTHON" -m pip install --upgrade pip >>"$BOOTSTRAP_LOG" 2>&1; then
    echo "pip の更新に失敗しました。"
    echo "詳細ログ: $BOOTSTRAP_LOG"
    exit 1
  fi
  if ! "$VENV_PYTHON" -m pip install -e "$ROOT_DIR" >>"$BOOTSTRAP_LOG" 2>&1; then
    echo "CLI 本体のインストールに失敗しました。"
    echo "詳細ログ: $BOOTSTRAP_LOG"
    exit 1
  fi
}

ensure_venv_dependencies() {
  if "$VENV_PYTHON" - <<'PY' >>"$BOOTSTRAP_LOG" 2>&1
import mujina_assist
import textual
PY
  then
    return 0
  fi
  echo "Python 依存関係を補完します。"
  if ! "$VENV_PYTHON" -m pip install -e "$ROOT_DIR" >>"$BOOTSTRAP_LOG" 2>&1; then
    echo "Python 依存関係のインストールに失敗しました。"
    echo "詳細ログ: $BOOTSTRAP_LOG"
    exit 1
  fi
}

if [[ -x "$VENV_PYTHON" ]]; then
  if "$VENV_PYTHON" -m pip --version >>"$BOOTSTRAP_LOG" 2>&1; then
    RUNNER=("$VENV_PYTHON")
    ensure_venv_dependencies
  else
    echo "既存の Python 仮想環境が壊れている可能性があるため作り直します。"
    rm -rf "$VENV_DIR"
  fi
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "起動用の Python 仮想環境を準備します。"
  if create_or_refresh_venv; then
    RUNNER=("$VENV_PYTHON")
  else
    echo "python3-venv がまだ使えません。Ubuntu の標準パッケージを導入してから再試行します。"
    if install_python_bootstrap_packages && create_or_refresh_venv; then
      RUNNER=("$VENV_PYTHON")
    else
      echo "Python 仮想環境を自動準備できませんでした。"
      echo "手動で直す場合: sudo apt install -y python3-venv python3-pip"
      echo "その後にもう一度 ./start.sh を実行してください。"
      echo "詳細ログ: $BOOTSTRAP_LOG"
      exit 1
    fi
  fi
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
    echo "注意: このツールは Ubuntu 24.04 を前提に設計されています。"
    echo "現在の OS: ${PRETTY_NAME:-unknown}"
  fi
fi

if [[ "$#" -eq 0 ]]; then
  exec "${RUNNER[@]}" -m mujina_assist.main tui
fi

exec "${RUNNER[@]}" -m mujina_assist.main "$@"
