# Design notes

The detail behind the [README](../README.md): what a loop costs, what went wrong in the live runs
and how it was fixed, the limits, the repo layout, and the tests and CI. For how each agent works
inside, see the [front desk](../agents/frontdesk/README.md) and [coder](../agents/coder/README.md)
READMEs. The day-by-day record is in the [build journal](build-journal.md).

## What a loop costs

From `agents/frontdesk/calls.log` and the coder logs:

| Loop | Front desk Gemini calls | Claude Code runs | Verify | Time |
| --- | --- | --- | --- | --- |
| `BL-1` (fault 1, Nov 4) | 2 (`gemini-3.5-flash-lite`, 3,053 tokens): the vague report, then the complete one | 3: reproducer 22 s (refused, see below), reproducer again 26 s, fixer 55 s | not in this run | 16 min 57 s report to "fixed", most of it the permission fix and restart between the two reproducer runs |
| `BL-2` (fault 2, Nov 4) | 1 to open it, 2 more for the second user's duplicate (classify, duplicate check) | 2: reproducer 24 s, fixer 51 s | not in this run | 2 min 25 s report to "fixed", both reporters told |
| `BL-3` (fault 1, Nov 5) | 2 | 3: reproduce, fix, verify | `Verified` by the reproducer | 70 s from the PM's approval |
| `BL-5` (fault 2, Nov 5) | 2 (classify, duplicate check), after two HTTP 503s that the front desk waited out | 4: reproduce (the report's numbers were wrong: "not reproduced"), again on the PM's pointer, fix, verify | `Verified` by the reproducer | 78 s from the PM's approval |
| `BL-1` (fault 1, Nov 7, the video) | 4: 2 for the ticket, 2 for the Mattermost duplicate (classify, duplicate check) | 3: reproduce 30 s after the ticket, fix 46 s, verify | `Verified` by the reproducer | 70 s from the PM's approval to "fixed" in Telegram |

`BL-1` and `BL-2` on Nov 4 ran before the verify step existed; it adds one Claude Code run and no
Gemini call. The Nov 4 smoke run, every seeded path, took 13 Gemini calls. The target was under 25
per loop.

## What the agents got wrong and how it was fixed

From the live runs on Nov 4 to 6:

- **The reproducer could not run a single command.** Its first try at `BL-1` replied "every
  command, even `git status`, was refused": in `dontAsk` mode every part of a chained shell
  command must be on the allow list, and ours listed single commands. The coders now allow `Bash`
  and keep each role in its lane with deny lists; the retry reproduced `BL-1` in 26 seconds.
- **The plan assumed Console features Windows does not have.** Console cannot run coding agents
  there (every provider showed "Not supported here"; its code says "SDK sessions require a POSIX
  SSH execution host"), so the coders became custom protocol agents. It serves no Gateway web UI
  either, so every setup step after the chat apps goes through the Gateway API, in
  `scripts/bootstrap.py`.
- **A typo reached nobody.** Slack's free plan gives agents no `@` autocomplete, and `@repoducer`
  went nowhere without an error. Names must be typed exactly.
- **The front desk replied in the wrong thread.** It used the id of the message that addressed it,
  not the thread's root, so a reply to a reply left the ticket's thread. It now uses the root.
- **A refusal woke the reproducer.** The front desk's reply "Only @reproducer or the room owner
  can close a ticket" named the role, so Switch addressed the reproducer and it started a run for
  nothing. The front desk's replies no longer name a role, and a test checks every one.
- **The reproducer could not write its scratch script.** Claude Code reads a relative path rule
  against the shell's current directory, so after `cd demo-app` the write rule stopped matching.
  The rules are now absolute paths under each clone, checked with the real command line.
- **A busy model meant silence.** Gemini answered 503 "high demand", and only 429 was retried, so
  the reporter got no reply. 503 is now waited out the same way (twice on `BL-5`, unseen by the
  user), and any other error gets "Something went wrong on my side".
- **A server restart replayed old approvals.** On Nov 6 Switch's own database restarted and sent
  every agent its whole history, including old `@fixer go` messages; the fixer ran none of them.
  An agent now ignores a message more than 30 minutes old and any message it already handled, and
  a connection with nothing delivered yet starts at the newest message.

What reading the Switch docs and server source changed before the first run is in
[switch-setup.md](switch-setup.md#what-the-switch-docs-and-server-source-changed).

## Limits and next steps

- The second user in the live runs (`sam`, and `dev.intern` in the recording) posted through the
  Gateway chat API, not from a second Telegram or Slack account. The refusal wording for an
  unlinked chat account may differ ([troubleshooting](switch-setup.md#troubleshooting)), and
  `approvers` is not yet run live.
- The limit of 5 open tickets per user is unit-tested but was not hit in a live run.
- An agent that was down for more than 30 minutes does not answer the messages sent meanwhile
  (its log names them). That is the cost of the replay guard above.
- `scripts/bootstrap.py` set up a second copy from nothing on Nov 5 (new agents, rooms, rules,
  links and kit, on [Mattermost](switch-setup.md#mattermost-only-no-telegram-or-slack)), but on a
  server that already had the demo, not on a newly installed Switch.
- The front desk's Docker service is not verified against Console's native server, which listens
  on 127.0.0.1 only; run the front desk natively, as in the README's part B. Its image needs a
  clone mounted at `/repo`, as in `docker-compose.yml`.
- Only tested on Windows 11 with Console 0.40.1. On macOS or Linux, Console could run the coders
  as managed agents instead; that path is not tested.
- A role mention reaches a coder only while its program is running and holds the role. The front
  desk says so in the ticket's thread when `send_targeted_message` reports no live target.
- After `ask`, the reporter's next message to the front desk is taken as the answer, wherever they
  post it. Naming the ticket (`BL-2: ...`) picks which question it answers.
- Feature requests are logged, not handed over; the PM reads them with `@frontdesk requests`.
  Turning one into planned work is up to the PM.

## Repo layout

```text
bugline.toml         the project the agents work on: repo, paths, test command, report fields, names
demo-app/            FastAPI + SQLite expense splitter with seeded faults, tests, Dockerfile
agents/common/       shared by all three agents: Switch protocol client, ticket id format, .env
                     loading, project.py (reads bugline.toml and fills the switch/ placeholders)
agents/frontdesk/    the front desk: handlers, Gemini calls and prompts, SQLite store, Dockerfile
agents/coder/        the reproducer and the fixer: one program that runs Claude Code headless
switch/              room templates, room instructions, docs/ (the bugline-kit documents), agent-briefs/
scripts/             bootstrap.py: everything in Switch after the chat-app connections, idempotent;
                     doctor.py: checks before a recording; reset_demo.py: back to BL-1
docs/                switch-setup.md (Switch walkthrough, other chat apps, troubleshooting),
                     own-repo.md, design-notes.md, build-journal.md, images/
.github/             workflows/ci.yml, workflows/release.yml, dependabot.yml
docker-compose.yml   demo app; front desk under the `agents` profile
CLAUDE.md, AGENTS.md instructions for the coding agents used to build this repo; Bugline's own
                     agents do not read them
```

## Tests and CI

[`ci.yml`](../.github/workflows/ci.yml) runs on every pull request and on `main`. Its `test` job
runs `ruff format --check`, `ruff check` and `pytest -q` for each of the five Python projects on
Python 3.14.7. Expected counts: `demo-app` 8 passed, `agents/frontdesk` 95 passed and 1 skipped
(the skipped test calls Gemini and runs only with `BUGLINE_LIVE=1`), `agents/common` 34,
`agents/coder` 28, `scripts` 35. The `docker` job builds both images and checks that the demo app
answers `/health` and `/groups/1/balances` under Compose; the `docs` job checks every relative
link and anchor in the Markdown files, offline. [`release.yml`](../.github/workflows/release.yml)
runs on a `v*.*.*` tag: the same checks, then the two images for amd64 and arm64 to GHCR, then a
GitHub Release with generated notes. Dependabot opens grouped monthly updates. The tests that
would catch faults 1 and 2 are left out on purpose; the fixer adds them during the demo.
