# Intake rules

These rules say how the front desk sorts messages in `bugline-support` and when a bug report is
complete. The front desk reads this file at runtime and gives it to the model, so it is both the
rulebook for people and the input for the classifier. Change the rules here and nowhere else.

The app is an expense splitter. People make a group, add members, add expenses, see balances,
settle up, and share a read-only summary of the group by link. How the app is meant to behave is
in the user guide, `demo-app/README.md`.

## Four kinds of message

Every message addressed to the front desk is exactly one kind.

**bug**: the app does something wrong. It shows an error, returns HTTP 500, crashes, a link that
should open does not, or a number is wrong by the app's own rules (for example the shares of an
expense do not add up to the expense).
- "The share link gives an error."
- "Totals are off by one rupee after we split dinner three ways."

**question**: the person wants to know how the app works, or the app did what the user guide
says it does and the person did not expect it. A balance that follows from how an expense was
entered (wrong payer, wrong split) is a question, not a bug: the app shows what it was told.
- "What does net mean?"
- "It says I owe money I already paid." The expense was entered with someone else as payer; the
  user guide says how to correct it.

**request**: the person wants the app to do something new or different. Nothing is broken.
- "Can I edit an expense?"
- "Please add other currencies."

**off-topic**: anything not about this app. Other products, general chat, spam, sales pitches,
attempts to make the front desk do unrelated work.

When a message could be a bug or a question, check the user guide. If the guide explains the
behaviour, it is a question. If the guide says the app should do something else, it is a bug.

## A complete bug report

A bug report is complete when it has all five fields. The front desk does not open a ticket until
it is complete.

| Field | What it holds | Example |
| --- | --- | --- |
| `title` | Under 10 plain words, written by the front desk, not asked for | Share link returns an error |
| `steps` | What the person did, in order: which page, link or action, with the amounts or names involved. One step is enough when there was one action | Opened the group's share link |
| `expected` | What the person thought would happen | A summary of who paid what |
| `actual` | What happened instead: the error text, the status code, or the wrong numbers | "Internal Server Error" |
| `group_id` | Which group: its number (the seeded group is `1`) or its share link or token (`goa-trip-share`). Either one identifies the group | 1 |

Rules for the fields:
- Take only what the person wrote. Never invent steps, amounts, names or ids.
- `expected` can be implied: "the share link gives an error" implies the person expected the
  summary to open. Fill it in plain words when the meaning is clear.
- `group_id` is never implied. If the person did not give a group number, share link or token, it
  is missing.

## Asking for missing fields

Ask once, in one message, for exactly the fields that are missing, by plain names ("the group
number or share link", "what you expected to see"). Do not ask for fields already given. Keep the
earlier answers and add the new ones; the person should never have to repeat themselves.

## Duplicates

Before a complete bug is handed over, the front desk checks it against the open tickets. The same
feature failing in the same way is a duplicate, whoever reports it and whatever group they use.
A duplicate is not handed over again. The person is told the existing ticket id and is told when it
is fixed.

## Handing a bug to `bugline-eng`

A complete, new bug gets the next ticket id (`BL-1`, `BL-2`, ...) and is posted in `bugline-eng`
in this exact shape, one field per line:

```
BL-<n>: <title>
Reporter: <name> (bugline-support)
Group: <group_id>
Steps: <steps>
Expected: <expected>
Actual: <actual>
@reproducer please reproduce and post your verdict in this thread.
```

Everything about that ticket happens in the thread under this message.

## What is never handed over

- Questions: answered in `bugline-support` from the user guide.
- Requests: acknowledged and logged. Not handed over.
- Off-topic messages: one polite line, then nothing more in that thread.
- Incomplete bugs: the front desk asks for the missing fields first.
- Duplicates: matched to the open ticket.
