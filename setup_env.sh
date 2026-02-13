#!/usr/bin/env bash
# SynchroCap micromamba 環境セットアップスクリプト
# 使い方: bash setup_env.sh
set -euo pipefail

ENV_NAME="SynchroCap"
PYTHON_VERSION="3.10"

# --- micromamba が使えるか確認 ---
if ! command -v micromamba &>/dev/null; then
  echo "ERROR: micromamba が見つかりません。先にインストールしてください。"
  echo "  https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html"
  exit 1
fi

# --- 既存環境チェック ---
if micromamba env list | grep -q "\\b${ENV_NAME}\\b"; then
  echo "環境 '${ENV_NAME}' は既に存在します。再作成する場合は先に削除してください:"
  echo "  micromamba env remove -n ${ENV_NAME}"
  exit 1
fi

echo "=== 環境 '${ENV_NAME}' を作成します (Python ${PYTHON_VERSION}) ==="
micromamba create -n "${ENV_NAME}" -c conda-forge "python=${PYTHON_VERSION}" -y

echo ""
echo "=== pip パッケージをインストールします ==="

# ---- アプリ本体 (必須) ----
micromamba run -n "${ENV_NAME}" pip install \
  "imagingcontrol4>=1.2.0" \
  imagingcontrol4pyside6

# ---- ツール類 (tools/ で使用) ----
micromamba run -n "${ENV_NAME}" pip install \
  numpy \
  opencv-python \
  pillow \
  qrcode

# ---- 開発用 (不要ならコメントアウト) ----
# micromamba run -n "${ENV_NAME}" pip install jupyterlab

echo ""
echo "=== セットアップ完了 ==="
echo "有効化:  micromamba activate ${ENV_NAME}"
echo "起動:    cd src/synchroCap && python main.py"
