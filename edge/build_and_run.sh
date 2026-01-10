#!/bin/bash
set -e

echo "Building Swift package..."
swift build

echo "Packaging app..."
mkdir -p edge.app/Contents/MacOS
cp .build/debug/edge edge.app/Contents/MacOS/edge

echo "Signing app..."
codesign -s - --entitlements entitlements.plist -f edge.app/Contents/MacOS/edge

echo "Launching app..."
open edge.app

echo "Done. Check ../crate/my_library.json for output."

