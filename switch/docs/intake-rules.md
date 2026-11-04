# Intake rules

These rules say how the front desk sorts messages in `$support_room` and when a bug report is
complete. The front desk reads this file at runtime and gives it to the model, so it is both the
rulebook for people and the input for the classifier. Change the rules here and nowhere else. The
app's description, the room names and the report fields come from `bugline.toml`.

The front desk serves the users of $product. $about How the app is meant to behave is in the user
guide, `$user_guide`.

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

A bug report is complete when it has every field below that is not marked optional. The front
desk does not open a ticket until it is complete.

$report_fields

Take only what the person wrote. Never invent steps, amounts, names or ids.

## Asking for missing fields

Ask once, in one message, for exactly the fields that are missing, by plain names ("the group
number or share link", "what you expected to see"). Do not ask for fields already given. Keep the
earlier answers and add the new ones; the person should never have to repeat themselves.

## Duplicates

Before a complete bug is handed over, the front desk checks it against the open tickets. The same
feature failing in the same way is a duplicate, whoever reports it and whatever group they use.
A duplicate is not handed over again. The person is told the existing ticket id and is told when it
is fixed.

## Handing a bug to `$eng_room`

A complete, new bug gets the next ticket id (`$ticket_prefix-1`, `$ticket_prefix-2`, ...) and is posted in `$eng_room`
in this exact shape, one field per line:

```
$ticket_prefix-<n>: <title>
Reporter: <name> ($support_room)
$report_lines
@reproducer please reproduce and post your verdict in this thread.
```

Everything about that ticket happens in the thread under this message.

## What is never handed over

- Questions: answered in `$support_room` from the user guide.
- Requests: acknowledged and logged. Not handed over.
- Off-topic messages: one polite line, then nothing more in that thread.
- Incomplete bugs: the front desk asks for the missing fields first.
- Duplicates: matched to the open ticket.
