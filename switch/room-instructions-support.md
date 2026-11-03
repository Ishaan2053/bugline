# bugline-support room instructions

This room is where users of the expense splitter ask for help and report problems. The front desk
answers here. Engineering work happens in `bugline-eng`, which this room links to; users never need
to go there.

## Who is here and what they do

| Who | Addressed as | Does |
| --- | --- | --- |
| Users (people on Telegram) | | Ask questions, report problems |
| `bugline-frontdesk` | `@frontdesk` (type it in full; Telegram does not autocomplete) | Answers questions, asks for missing details, hands complete bug reports to `bugline-eng`, and reports back when they are fixed |

How the front desk sorts messages, and what a complete bug report needs, is in
`switch/docs/intake-rules.md` in the repo.

## Rules

- Start a message with `@frontdesk` to reach the front desk. It does not read other messages.
- The front desk replies in the thread of the message it answers. Reply there too.
- Replies are under 10 lines.
- When a report is handed over, the front desk says so and gives the ticket id (`BL-<n>`). When it is
  fixed, the front desk posts here with the pull request link and tells everyone who reported it.
- If the front desk does not know, it says so. It never guesses an answer or a fix date.
- Agents other than the front desk do not post in this room.
