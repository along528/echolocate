#!/bin/bash
set -e
cd "$(dirname "$0")"

# Build using xcodebuild
# We rely on default DerivedData or user configuration, so we need to find where the binary goes.
# We'll assign the build settings to variables.

# Build using xcodebuild
# We use -derivedDataPath to ensure a known output directory structure.
# This prevents issues where SYMROOT breaks dependency resolution and allows us to predict the artifact path.

xcodebuild -scheme edge -configuration Debug -destination 'platform=macOS' \
  CODE_SIGN_STYLE="Manual" \
  CODE_SIGN_IDENTITY="Apple Development: along528@bu.edu (HSVR2RH68L)" \
  CODE_SIGN_ENTITLEMENTS="entitlements.plist" \
  CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION="YES" \
  PROVISIONING_PROFILE_SPECIFIER="" \
  -derivedDataPath ".build-xcode" \
  build

echo "Packaging app..."
mkdir -p edge.app/Contents/MacOS
# Artifact location with -derivedDataPath is predictable
cp ".build-xcode/Build/Products/Debug/edge" edge.app/Contents/MacOS/edge
cp Info.plist edge.app/Contents/Info.plist

# No need to manually code sign if xcodebuild did it, but xcodebuild might verify it.
# If xcodebuild signing fails on command line with Package.swift (which sometimes happens),
# we might need to resign. But let's assume xcodebuild handles it if arguments are passed.
# Just in case, we can verify signature.

echo "Verifying signature..."
codesign -dv --entitlements - edge.app/Contents/MacOS/edge

echo "Build complete."
cp Info.plist edge.app/Contents/Info.plist

# No need to manually code sign if xcodebuild did it, but xcodebuild might verify it.
# If xcodebuild signing fails on command line with Package.swift (which sometimes happens),
# we might need to resign. But let's assume xcodebuild handles it if arguments are passed.
# Just in case, we can verify signature.

echo "Verifying signature..."
codesign -dv --entitlements - edge.app/Contents/MacOS/edge

echo "Build complete."
