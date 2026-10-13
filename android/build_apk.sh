#!/usr/bin/env bash
# Build the shareable, signed APK pointing at your deployed site.
# Usage: android/build_apk.sh https://your-app.vercel.app
set -euo pipefail
URL="${1:?Usage: android/build_apk.sh https://your-app.vercel.app}"
[[ "$URL" == https://* ]] || { echo "URL must start with https:// (the microphone only works over HTTPS)"; exit 1; }
URL="${URL%/}"
echo "Checking $URL/api/status ..."
curl -sf -m 20 "$URL/api/status" >/dev/null || { echo "⚠️  $URL/api/status is not responding — is the deployment live?"; exit 1; }
cd "$(dirname "$0")"
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
./gradlew assembleRelease -PappUrl="$URL" --console=plain -q
mkdir -p ../dist
cp app/build/outputs/apk/release/app-release.apk ../dist/KumbhSahayak.apk
echo "✅ APK ready: $(cd ../dist && pwd)/KumbhSahayak.apk  (opens $URL)"
