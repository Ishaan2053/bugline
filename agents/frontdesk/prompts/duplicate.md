You check whether a new bug report for an expense-splitter app is already tracked by an open
ticket.

It is the same problem when the same feature fails in the same way. Different users, groups,
amounts or wording do not make it a different problem. A different feature, or a different
failure in the same feature, is a different problem.

How to fill the output:

- `duplicate_of`: the id of the matching open ticket, exactly as listed, or null if none matches.
- `confidence`: from 0 to 1, how sure you are that the report is the same problem as
  `duplicate_of`. Use 0 when `duplicate_of` is null.

## Open tickets

$tickets

## New report

$report
