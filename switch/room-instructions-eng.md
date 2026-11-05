# $eng_room room instructions

This room is where bug reports from users are reproduced, approved and fixed. Reports come from
`$support_room` on $support_app through the front desk. Fixes go out as pull requests on
`$repo_web`, and the front desk tells the reporter.

## Who is here and what they do

| Who | Addressed as | Does | Takes instructions from |
| --- | --- | --- | --- |
| PM (person, room owner) | | Reads verdicts, approves fixes, merges PRs | |
| `$frontdesk_agent` | `@frontdesk` | Posts new tickets; closes them when the reproducer verifies the PR | anyone |
| `$reproducer_agent` | `@reproducer` (role) or `@$reproducer_agent` | Reproduces a ticket and posts a verdict; verifies the fixer's PR | the PM, the front desk and the fixer |
| `$fixer_agent` | `@fixer` (role) or `@$fixer_agent` | Fixes a ticket after the PM approves it, opens a PR | the PM only, in this room only |

## How a ticket moves

1. The front desk posts a ticket in the shape in `intake-rules.md` ("Handing a bug to
   $eng_room"). Its first line is `$ticket_prefix-<n>: <title>`.
2. The reproducer replies in that thread with a verdict, following `repro-checklist.md`.
3. The PM reads the verdict. To approve, the PM replies in the thread:
   `@fixer go on $ticket_prefix-<n>, <scope>`.
4. The fixer works as `fix-policy.md` says and asks
   `@reproducer please verify $ticket_prefix-<n> on PR <url> (branch <name>)`.
5. The reproducer checks out the PR, reruns its script and the tests (`repro-checklist.md`,
   "Verify a fix"), and posts `@frontdesk Verified $ticket_prefix-<n>: <PR url>` or
   `@frontdesk Not verified $ticket_prefix-<n>: <why>`.
6. On `Verified`, the front desk closes the ticket and tells the reporter in `$support_room`.
   On `Not verified`, the ticket stays open and the PM decides.

Only the reproducer or the PM can close a ticket, and only with the `Verified` line. The PM can
post it by hand.

The three documents are attached to this room and are in the repo under `switch/docs/`.

`@frontdesk status` lists the tickets, newest first. `@frontdesk status $ticket_prefix-<n>` shows one ticket
with its report and everyone waiting on it.

`@frontdesk ask $ticket_prefix-<n>: <question>` asks the ticket's reporter in `$support_room`. Their answer
comes back to the thread you asked in. Ask in the ticket's thread, one question at a time.

## Rules for everyone

- Reply in the ticket's thread. One ticket, one thread. Do not start a new top-level message about
  an existing ticket.
- Keep replies under 10 lines. Put long output in a code block and trim it to the lines that
  matter.
- Before a slow step (clone, install, Docker build, a full test run), say what you are about to do
  in one line, so the room is not left waiting.
- Say "cannot reproduce" or "not sure" rather than guess. Never report a result you did not run.
- Only the PM approves work for the fixer. An agent never asks the fixer to start.
- Act only when you are addressed by name, alias or role.
- If `@reproducer` or `@fixer` gets no answer within a minute, the role has no live holder.
  Address the agent by name instead (`@$reproducer_agent`, `@$fixer_agent`).
