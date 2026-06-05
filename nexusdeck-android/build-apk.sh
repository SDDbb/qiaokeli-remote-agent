#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$APP_ROOT/.." && pwd)"
LOCAL_JDK="${HOME}/.local/opt/java-21-openjdk"

if [ -x "$LOCAL_JDK/bin/javac" ]; then
  export JAVA_HOME="$LOCAL_JDK"
  export PATH="$JAVA_HOME/bin:$PATH"
fi

if [ ! -f "$APP_ROOT/local.properties" ] || [ ! -x "$APP_ROOT/gradlew" ]; then
  "$PROJECT_ROOT/scripts/setup_nexusdeck_android_build_env.sh"
fi

cd "$APP_ROOT"
if [ -x "${HOME}/.local/opt/gradle-8.11.1/bin/gradle" ]; then
  "${HOME}/.local/opt/gradle-8.11.1/bin/gradle" assembleDebug
else
  ./gradlew assembleDebug
fi

APK="$APP_ROOT/app/build/outputs/apk/debug/app-debug.apk"
echo "$APK"
