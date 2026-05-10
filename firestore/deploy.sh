#!/bin/bash
set -e

PROJECT_ID="cloud-crate-485418"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying Firestore security rules..."
cd "$DIR"
npx -y firebase-tools deploy --only firestore:rules --project ${PROJECT_ID}
echo "Firestore rules deployed!"
