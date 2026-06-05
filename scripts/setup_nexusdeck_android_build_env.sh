#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="$PROJECT_ROOT/nexusdeck-android"
OPT_DIR="${HOME}/.local/opt"
CACHE_DIR="${HOME}/.cache/nexusdeck-build"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${OPT_DIR}/android-sdk}"
GRADLE_VERSION="${GRADLE_VERSION:-8.11.1}"
GRADLE_HOME="${OPT_DIR}/gradle-${GRADLE_VERSION}"
JDK_HOME="${JDK_HOME:-${OPT_DIR}/java-21-openjdk}"
CMDLINE_ZIP="commandlinetools-linux-11076708_latest.zip"
GRADLE_ZIP="gradle-${GRADLE_VERSION}-bin.zip"

mkdir -p "$OPT_DIR" "$CACHE_DIR" "$ANDROID_SDK_ROOT/cmdline-tools"

download() {
  local url="$1"
  local target="$2"
  curl -L --fail --retry 5 --connect-timeout 20 -C - -o "$target" "$url"
}

ensure_zip() {
  local url="$1"
  local target="$2"
  if [ -f "$target" ] && unzip -t "$target" >/dev/null 2>&1; then
    return 0
  fi
  rm -f "$target"
  download "$url" "$target"
}

ensure_jdk() {
  if command -v javac >/dev/null 2>&1; then
    return 0
  fi

  if [ -x "$JDK_HOME/bin/javac" ]; then
    export JAVA_HOME="$JDK_HOME"
    export PATH="$JAVA_HOME/bin:$PATH"
    return 0
  fi

  if ! command -v dnf >/dev/null 2>&1 || ! command -v rpm2cpio >/dev/null 2>&1 || ! command -v cpio >/dev/null 2>&1; then
    echo "javac is missing, and dnf/rpm2cpio/cpio are not all available to install a user-local JDK." >&2
    exit 1
  fi

  local rpm_dir="$CACHE_DIR/jdk-rpms"
  local extract_dir="$CACHE_DIR/jdk-rpm-full"
  rm -rf "$rpm_dir" "$extract_dir"
  mkdir -p "$rpm_dir" "$extract_dir"

  env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u https_proxy -u http_proxy -u all_proxy \
    dnf download --destdir "$rpm_dir" \
    java-21-openjdk-headless.x86_64 \
    java-21-openjdk-devel.x86_64

  (
    cd "$extract_dir"
    for rpm in "$rpm_dir"/java-21-openjdk-headless-*.rpm "$rpm_dir"/java-21-openjdk-devel-*.rpm; do
      rpm2cpio "$rpm" | cpio -idmu >/dev/null
    done
  )

  rm -rf "${JDK_HOME}.tmp" "$JDK_HOME"
  cp -a "$extract_dir/usr/lib/jvm/java-21-openjdk" "${JDK_HOME}.tmp"
  rm -f "${JDK_HOME}.tmp/conf"
  cp -a "$extract_dir/etc/java/java-21-openjdk/java-21-openjdk/conf" "${JDK_HOME}.tmp/conf"
  if [ -L "${JDK_HOME}.tmp/lib/security" ]; then
    rm -f "${JDK_HOME}.tmp/lib/security"
    cp -a "$extract_dir/etc/java/java-21-openjdk/java-21-openjdk/lib/security" "${JDK_HOME}.tmp/lib/security"
  fi
  mv "${JDK_HOME}.tmp" "$JDK_HOME"

  export JAVA_HOME="$JDK_HOME"
  export PATH="$JAVA_HOME/bin:$PATH"
}

ensure_jdk

if [ ! -x "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  cd "$CACHE_DIR"
  ensure_zip "https://dl.google.com/android/repository/${CMDLINE_ZIP}" "$CMDLINE_ZIP"
  rm -rf "$CACHE_DIR/cmdline-tools" "$ANDROID_SDK_ROOT/cmdline-tools/latest"
  unzip -q -o "$CMDLINE_ZIP" -d "$CACHE_DIR"
  mv "$CACHE_DIR/cmdline-tools" "$ANDROID_SDK_ROOT/cmdline-tools/latest"
fi

if [ ! -x "$GRADLE_HOME/bin/gradle" ]; then
  cd "$CACHE_DIR"
  ensure_zip "https://services.gradle.org/distributions/${GRADLE_ZIP}" "$GRADLE_ZIP"
  unzip -q -o "$GRADLE_ZIP" -d "$OPT_DIR"
fi

SDKMANAGER="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
yes | "$SDKMANAGER" --sdk_root="$ANDROID_SDK_ROOT" --licenses >/dev/null || true
"$SDKMANAGER" --sdk_root="$ANDROID_SDK_ROOT" \
  "platform-tools" \
  "platforms;android-35" \
  "build-tools;35.0.0"

cat > "$APP_ROOT/local.properties" <<EOF
sdk.dir=${ANDROID_SDK_ROOT}
EOF

cd "$APP_ROOT"
if [ ! -x "./gradlew" ]; then
  "$GRADLE_HOME/bin/gradle" wrapper --gradle-version "$GRADLE_VERSION" --distribution-type bin
fi

echo "NexusDeck Android build environment is ready."
echo "SDK: $ANDROID_SDK_ROOT"
echo "Gradle: $GRADLE_HOME/bin/gradle"
echo "JDK: ${JAVA_HOME:-$(dirname "$(dirname "$(command -v javac)")")}"
