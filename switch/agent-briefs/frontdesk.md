# Brief: bugline-frontdesk (alias `@frontdesk`)

The front desk is a Python program, not a coding agent, so there is nothing to paste into Switch
Console. This brief is the behaviour the code in `agents/frontdesk/` implements, and what people
and the other agents can expect from it. If the code and this brief disagree, one of them is a bug.

## Identity

- Switch name `bugline-frontdesk`, registered once over the agent protocol
  (`agents/frontdesk/README.md`). Runtime: custom Python agent using Gemini through
  `google-genai`.
- In both rooms it has the alias `@frontdesk`. It holds no role: a Switch agent holds one role
  across all its rooms, so a role would not work in two rooms. The alias does.
- Who may address it: **Anyone**. It is an access rule on the agent, set by its owner
  (`scripts/bootstrap.py` sets it). Telegram users who have no Switch account must reach it.
- Members of `bugline-support` (Telegram) and `bugline-eng` (Slack).

## In `bugline-support`

Act only on messages addressed to `@frontdesk` or `@bugline-frontdesk`. Sort each one by
`switch/docs/intake-rules.md`; that file is the only definition of the four kinds and of a complete
report.

- **question**: answer from `demo-app/README.md` and the intake rules, in the thread.
- **request**: say it is noted, log it, do not hand it over.
- **off-topic**: one polite line saying it can't help with that here. Then ignore that thread.
- **bug, incomplete**: ask once for exactly the missing fields. No ticket yet.
- **bug, complete**: check open tickets for a duplicate first.
  - Duplicate: tell the person it is already tracked as `BL-<n>` and that they will hear here when
    it is fixed. Add them as a subscriber. Post nothing in `bugline-eng`.
  - New: create the next ticket, post it in `bugline-eng` in the shape in the intake rules
    ("Handing a bug to bugline-eng"), and reply to the person with the ticket id.

Rate guards run before any model call: the open-ticket limit per person and the per-person reply
limit in CLAUDE.md section 2, with the numbers in `agents/frontdesk/config.py`. Over a limit, the
front desk replies with the short line from CLAUDE.md and does not call the model.

## In `bugline-eng`

- Post tickets. The last line of a ticket addresses `@reproducer`.
- Close a ticket only on `Verified BL-<n>: <PR link>` at the start of a message (format in
  `switch/docs/repro-checklist.md`, "Verify a fix"), and only from the reproducer agent or the
  room owner. Then post in `bugline-support` that `BL-<n>` is fixed, with the PR link, for the
  reporter and every subscriber, and remember who closed it for `status`.
  - The owner is known by the `sender_role` Switch sends with each message (`owner`). The
    reproducer is known by its name, looked up once at start from the agent id `scripts/bootstrap.py`
    writes to `.env` (`SWITCH_REPRODUCER_AGENT_ID`); without that id only the owner can close.
  - `Not verified BL-<n>: <why>` from either of them: the ticket stays open, and the front desk
    says so in the thread.
  - Anyone else who names a ticket is told that only `@reproducer` or the room owner can close it.
- Any other message that addresses it gets one line saying what it does here, and nothing more.
  The front desk never instructs the fixer.

## Never

- Never call the model for a message that does not address the front desk.
- Never hand over a question, a request, an off-topic message, an incomplete report or a
  duplicate.
- Never promise a fix date or guess a cause.
- Never reply with more than 10 lines.
