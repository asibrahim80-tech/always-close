#!/bin/bash

if [ -z "$GITHUB_TOKEN" ]; then
  echo "GITHUB_TOKEN is not set — GitHub sync disabled."
  exit 0
fi

REPO_URL="https://${GITHUB_TOKEN}@github.com/asibrahim80-tech/always-close.git"
git remote set-url origin "$REPO_URL"

while true
do
  git add .
  git commit -m "auto backup $(date '+%Y-%m-%d %H:%M:%S')" || echo "no changes"
  git push origin main && echo "pushed to GitHub" || echo "push failed"
  sleep 300
done
