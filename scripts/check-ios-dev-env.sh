#!/usr/bin/env bash
set -euo pipefail

failures=0

check() {
  local label="$1"
  shift

  if "$@" >/tmp/sift-ios-check.out 2>/tmp/sift-ios-check.err; then
    printf "[ok] %s\n" "$label"
    if [[ -s /tmp/sift-ios-check.out ]]; then
      sed 's/^/     /' /tmp/sift-ios-check.out
    fi
  else
    printf "[missing] %s\n" "$label"
    if [[ -s /tmp/sift-ios-check.err ]]; then
      sed 's/^/     /' /tmp/sift-ios-check.err
    fi
    failures=$((failures + 1))
  fi
}

echo "Sift iOS development environment"
echo

check "macOS version" sw_vers
check "Swift compiler" swift --version
check "active developer directory" xcode-select -p
check "full Xcode xcodebuild" xcodebuild -version
check "Simulator control tool" xcrun --find simctl
check "iOS Simulator SDK" xcrun --sdk iphonesimulator --show-sdk-path
check "installed iOS Simulator runtime" bash -c 'xcrun simctl runtime list 2>/dev/null | grep -E "iOS .+\\(Ready\\)"'
check "available iOS Simulator device" bash -c 'xcrun simctl list devices available 2>/dev/null | grep -E "iPhone|iPad"'

echo
if [[ -d /Applications/Xcode.app ]]; then
  echo "[ok] /Applications/Xcode.app exists"
else
  echo "[missing] /Applications/Xcode.app"
  failures=$((failures + 1))
fi

if find ios -maxdepth 2 \( -name "*.xcodeproj" -o -name "*.xcworkspace" -o -name "Package.swift" \) | grep -q .; then
  echo "[ok] iOS project/workspace manifest exists"
else
  echo "[missing] iOS project/workspace manifest"
  echo "     Expected ios/Sift.xcodeproj."
  failures=$((failures + 1))
fi

echo
if [[ "$failures" -eq 0 ]]; then
  echo "iOS development environment is ready."
else
  echo "$failures check(s) need attention."
  echo
  echo "Expected first-time setup after installing Xcode:"
  echo "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  echo "  sudo xcodebuild -license accept"
  echo "  xcodebuild -runFirstLaunch"
fi

exit "$failures"
