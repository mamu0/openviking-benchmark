#!/usr/bin/env bash
# Prepares the local environment to reproduce the benchmark.
set -euo pipefail

LAB="${LAB:-$HOME/openviking-lab}"
mkdir -p "$LAB" && cd "$LAB"

echo "==> virtualenv"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet openviking
.venv/bin/openviking-server --version || true

echo "==> configuration"
mkdir -p "$HOME/.openviking"
if [ ! -f "$HOME/.openviking/ov.conf" ]; then
  cp "$(dirname "$0")/../ov.conf.example" "$HOME/.openviking/ov.conf"
  chmod 600 "$HOME/.openviking/ov.conf"
  echo "    created ~/.openviking/ov.conf: fill in the placeholders before continuing"
  exit 1
fi

echo "==> checking configuration"
.venv/bin/openviking-server doctor

echo "==> starting server"
nohup .venv/bin/openviking-server > "$LAB/openviking.log" 2>&1 &
sleep 8

echo "==> CLI language and client configuration"
.venv/bin/ov language en
printf '{"url":"http://127.0.0.1:1933"}\n' > "$HOME/.openviking/ovcli.conf"

echo "==> status"
.venv/bin/ov status

cat <<'MSG'

Ready. Next steps:
  .venv/bin/ov add-resource <repo>/corpus --wait
  .venv/bin/ov tree viking://resources -L 3
  .venv/bin/ov abstract viking://resources/corpus/team-alpha/prd-checkout.md
MSG
