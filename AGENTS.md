# AGENTS.md — Development rules for Trifold

## General

- **Issue before feature/refactor**. Before implementing a major new feature or major refactor, record it as a GitHub issue in this project (`https://github.com/jaakla/trifold`). The issue body must contain the full plan (design, API shape, affected files, benchmarks intended). Pull requests implementing the feature or refactor must reference the issue number.
- **Mandatory hydration break**. For any change that requires a GitHub issue under the rule above, stop after creating the issue and allow the human to review, enhance, and approve the GitHub issue before starting code implementation. Do not continue into implementation until that approval is explicit.
