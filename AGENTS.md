# Bugline — instructions for OpenCode

Read `CLAUDE.md` in this directory and follow it in full. It is the single source of truth for this
repo: what we are building, the architecture, repo layout, conventions, Switch protocol facts,
Gemini free-tier rules, working rules, and the day-by-day checklist.

Non-negotiables, repeated here so they are never missed:

- **DRY** — do not repeat yourself; one definition per fact, referenced everywhere else.
- **Feature branches only.** Never commit to `main`. Work on `feat/`, `fix/` or `docs/` branches,
  open a PR to `main` with a proper title, description and labels, and **squash-merge** so `main`
  stays one clean commit per PR.
- **Newest compatible versions** of every library, tool and base image, pinned exactly.
- **Context7 MCP** for the latest documentation of every library and tool before writing code
  against it; Switch's own docs MCP (`https://docs.switchagents.ai/mcp`) for Switch.
- The intake agent is `@frontdesk`; never use the word "triage" anywhere in the repo.
- Never commit secrets. Never disconnect a chat app in Switch (it deletes every room on it).