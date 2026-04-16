#!/bin/bash

if [ -z "$GITHUB_TOKEN" ]; then
  echo "GITHUB_TOKEN is not set — GitHub sync disabled."
  exit 0
fi

# Configure git identity (required for commits)
git config --global user.email "always-close@replit.com"
git config --global user.name "Always Close Bot"

REPO_URL="https://${GITHUB_TOKEN}@github.com/asibrahim80-tech/always-close.git"
git remote set-url origin "$REPO_URL"

echo "GitHub sync started → asibrahim80-tech/always-close"

while true; do
  git add -A
  git commit -m "auto backup $(date '+%Y-%m-%d %H:%M:%S')" 2>&1 | grep -v "^$" || echo "no changes"
  git push origin main && echo "✅ pushed to GitHub" || echo "❌ push failed"
  sleep 300
done
