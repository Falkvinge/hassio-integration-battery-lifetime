#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage:"
  echo "  $0 create <topic> [base-branch]"
  echo "  $0 list"
  echo "  $0 remove <topic>"
  exit 1
}

sanitize_topic() {
  local topic="${1:-}"
  if [[ -z "$topic" ]]; then
    usage
  fi
  echo "$topic" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9._-'
}

cmd="${1:-}"
case "$cmd" in
  create)
    topic="$(sanitize_topic "${2:-}")"
    base="${3:-master}"
    branch="agent/${topic}"
    wt_root=".worktree"
    wt_path="${wt_root}/${topic}"

    mkdir -p "$wt_root"

    if [[ -e "$wt_path" ]]; then
      echo "Worktree path already exists: $wt_path"
      exit 1
    fi

    git fetch --all --prune
    git worktree add "$wt_path" -b "$branch" "$base"
    {
      echo "owner=${USER:-unknown}"
      echo "task=${topic}"
      echo "branch=${branch}"
      date -u +"created_at=%Y-%m-%dT%H:%M:%SZ"
    } > "${wt_path}/.agent-lock"
    echo "Created worktree: $wt_path"
    echo "Branch: $branch"
    ;;
  list)
    git worktree list
    ;;
  remove)
    topic="$(sanitize_topic "${2:-}")"
    wt_path=".worktree/${topic}"
    if [[ ! -d "$wt_path" ]]; then
      echo "Worktree path not found: $wt_path"
      exit 1
    fi
    git worktree remove "$wt_path"
    echo "Removed worktree: $wt_path"
    ;;
  *)
    usage
    ;;
esac
