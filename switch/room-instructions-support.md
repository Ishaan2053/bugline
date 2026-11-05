# $support_room room instructions

This room is where users of $product ask for help and report problems. The front desk
answers here. Engineering work happens in `$eng_room`, which this room links to; users never need
to go there.

## Who is here and what they do

| Who | Addressed as | Does |
| --- | --- | --- |
| Users (people on $support_app) | | Ask questions, report problems |
| `$frontdesk_agent` | `@frontdesk` (type it in full; some chat apps do not autocomplete it) | Answers questions, asks for missing details, hands complete bug reports to `$eng_room`, and reports back when they are fixed |

How the front desk sorts messages, and what a complete bug report needs, is in
`switch/docs/intake-rules.md` in the repo.

## Rules

- Write in any language. The front desk replies in it; the team gets your report in English.
- Start a message with `@frontdesk` to reach the front desk. It does not read other messages.
- The front desk replies in the thread of the message it answers. Reply there too.
- Replies are under 10 lines.
- When a report is handed over, the front desk says so and gives the ticket id (`$ticket_prefix-<n>`). When it is
  fixed, the front desk posts here with the pull request link and tells everyone who reported it.
- When the team needs more detail, the front desk asks here, in the thread of your report. Your
  next message to `@frontdesk` is passed to the team as your answer.
- If a fixed problem comes back, reply `still broken` to the front desk. It reopens the ticket and
  hands it back to the team.
- If the front desk does not know, it says so. It never guesses an answer or a fix date.
- Agents other than the front desk do not post in this room.
