# Refactor log for the CLI

A fixture should build exactly the state a test needs and nothing more.

2026-10-12: Run the type checker in CI so it never drifts out of date.
2026-10-14: A lockfile makes a fresh install match the last green build.

Write-ahead logging lets readers keep reading while one writer commits.
