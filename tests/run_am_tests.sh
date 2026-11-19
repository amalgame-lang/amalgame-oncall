#!/usr/bin/env bash
# Build + run every tests/*.am against the working tree.
#
# Usage : ./tests/run_am_tests.sh [amc-binary]
#
# The working tree is staged in the amc package cache as a dev version
# (tag v0.0.0-dev, rev localdev) and a scratch project pins it in its
# amalgame.lock ; the other packages come from GitHub. Stand-in services
# (tests/fake_services.py, python3 + cryptography) : a Web Push service
# that checks VAPID and decrypts each push with the phone's key, and an
# SMS gateway. A VAPID key is made with openssl. Each test gets
# <port> <dir> <vapid.key> <vapid.pub>. A test fails if it prints a
# [FAIL] line, exits non-zero or runs longer than 120 s.
#
# Env : ONLY=<test name> runs one test ; KEEP=1 keeps the scratch project.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AMC="${1:-$(command -v amc)}"
if [ ! -x "$AMC" ]; then
    echo "no amc binary (pass it as the first argument)" >&2
    exit 1
fi

DEV_TAG="v0.0.0-dev"
DEV_REV="localdev"
PKG_ROOT="$HOME/.amalgame/packages/github.com/amalgame-lang/amalgame-oncall"
DEV_DIR="$PKG_ROOT/${DEV_TAG}_${DEV_REV}"

# amc caches compiled facades as /tmp/amc-pkg-<first class>.o, whatever the
# package version : after an upgrade the old one would be linked. Clear them.
rm -rf "$DEV_DIR" /tmp/amc-pkg-*
for L in c d e f g h; do [ -d "/$L/tmp" ] && rm -rf "/$L/tmp"/amc-pkg-*; done
mkdir -p "$DEV_DIR"
cp "$ROOT/facade.am" "$ROOT/facade-stub.h" "$ROOT/amalgame.toml" "$DEV_DIR/"

WORK="$(mktemp -d)"
DATA="$WORK/data"
mkdir -p "$DATA"
openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null | openssl pkcs8 -topk8 -nocrypt -out "$DATA/vapid.key"
openssl ec -in "$DATA/vapid.key" -pubout -outform DER 2>/dev/null | tail -c 65 | base64 | tr -d '\n=' | tr '+/' '-_' > "$DATA/vapid.pub"
python3 "$ROOT/tests/fake_services.py" keys "$DATA" d1 d2
PORT=$(( 20000 + RANDOM % 20000 ))
python3 "$ROOT/tests/fake_services.py" serve "$PORT" "$DATA" &
SVC=$!
if [ -n "${KEEP:-}" ]; then
    trap 'kill $SVC 2>/dev/null' EXIT
    echo "work dir : $WORK"
else
    trap 'kill $SVC 2>/dev/null; rm -rf "$WORK" "$DEV_DIR"' EXIT
fi
cd "$WORK"
: > amalgame.toml
# net-sms and net-webpush v0.1.2 by their full URL : before (and after) their index entries.
for dep in crypto@v0.8.0 tls net-http@v0.29.6 threading@v0.1.0 datetime@v0.2.2 net-smtp@v0.2.7 \
           github.com/amalgame-lang/amalgame-net-webpush@v0.1.2 github.com/amalgame-lang/amalgame-net-sms@v0.1.0; do
    "$AMC" package add "$dep" >/dev/null 2>&1 || { echo "cannot install $dep" >&2; exit 1; }
done
cat >> amalgame.toml <<TOML

[dependencies.oncall]
git = "github.com/amalgame-lang/amalgame-oncall"
tag = "${DEV_TAG}"
TOML
cat >> amalgame.lock <<LOCK

[[package]]
name = "oncall"
git  = "github.com/amalgame-lang/amalgame-oncall"
tag  = "${DEV_TAG}"
rev  = "${DEV_REV}"
LOCK

fail=0
for src in "$ROOT"/tests/${ONLY:-*}.am; do
    name="$(basename "$src" .am)"
    cp "$src" .
    echo "== $name"
    if ! "$AMC" build "$name.am" -o "$name" > "$name.build.log" 2>&1; then
        grep -iE "error|undefined" "$name.build.log" | head -20 || true
        echo "FAIL $name (build)"; fail=1; continue
    fi
    if grep -q "int-conversion" "$name.build.log"; then
        grep "int-conversion" "$name.build.log" | head -5
        echo "FAIL $name (int-conversion : an error with gcc 14)"; fail=1; continue
    fi
    rm -f "$DATA/push.jsonl" "$DATA/sms.jsonl"
    if ! timeout 120 "./$name" "$PORT" "$DATA" "$DATA/vapid.key" "$DATA/vapid.pub" > "$name.log" 2>&1; then
        tail -20 "$name.log"; echo "FAIL $name (exit)"; fail=1; continue
    fi
    if grep -qE '^\[FAIL\]' "$name.log"; then
        grep -E '^\[FAIL\]' "$name.log"; echo "FAIL $name"; fail=1; continue
    fi
    echo "ok   $name ($(grep -c '^\[PASS\]' "$name.log") checks)"
done
exit $fail
