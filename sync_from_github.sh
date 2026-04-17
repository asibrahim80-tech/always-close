#!/bin/bash

# Git identity (required for merge commits)
export GIT_AUTHOR_NAME="sync-bot"
export GIT_AUTHOR_EMAIL="sync-bot@always-close.app"
export GIT_COMMITTER_NAME="sync-bot"
export GIT_COMMITTER_EMAIL="sync-bot@always-close.app"

echo "=== GitHub Auto Sync Started ==="
echo "Repository: https://github.com/asibrahim80-tech/always-close"
echo "Strategy: git pull (merge, prefer remote on conflict)"
echo ""

while true
do
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$TIMESTAMP] Pulling latest changes from GitHub..."

  # Fetch latest from remote
  git fetch origin main 2>&1

  # Check if there are any changes to pull
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/main)

  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[$TIMESTAMP] Already up to date. No changes."
  else
    echo "[$TIMESTAMP] New changes detected. Pulling..."

    # Pull with merge strategy — on conflict, prefer remote (GitHub) version
    git pull --no-rebase --no-edit -X theirs origin main 2>&1

    if [ $? -eq 0 ]; then
      COMMIT_MSG=$(git log -1 --pretty=format:"%h — %s" origin/main)
      echo "[$TIMESTAMP] ✓ Synced successfully → $COMMIT_MSG"
    else
      echo "[$TIMESTAMP] ✗ Pull failed. Falling back to hard reset..."
      git reset --hard origin/main 2>&1
      echo "[$TIMESTAMP] ✓ Hard reset applied — local matches GitHub"
    fi
  fi

  echo "[$TIMESTAMP] Next sync in 5 minutes..."
  echo ""
  sleep 300
done
