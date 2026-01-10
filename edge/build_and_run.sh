#!/bin/bash
set -e

# Run the separated build script
./build.sh

echo "Launching app..."
open -W edge.app

echo "Done. Check ../crate/my_library.json for output."
