#!/bin/bash
set -e

echo "Building Swift package..."
swift build

echo "Packaging app..."
mkdir -p edge.app/Contents/MacOS
cp .build/debug/edge edge.app/Contents/MacOS/edge
cp Info.plist edge.app/Contents/Info.plist

echo "Signing app..."
codesign -s "Apple Development: along528@bu.edu (HSVR2RH68L)" --entitlements entitlements.plist -f edge.app/Contents/MacOS/edge

echo "Build complete."
