"""Splitting expenses and settling up.

Pure functions with no HTTP or database code, so the arithmetic can be read on its own.
Amounts are rupees as floats, kept to two decimal places (paisa).
"""


def split_equal(amount: float, member_ids: list[int]) -> dict[int, float]:
    """Everyone in the group owes the same part of the expense.

    Works in whole paisa; when the amount does not divide evenly, the first members in the list
    each owe one paisa more, so the shares always add up to the amount.
    """
    base, leftover = divmod(round(amount * 100), len(member_ids))
    return {
        member_id: (base + (1 if index < leftover else 0)) / 100
        for index, member_id in enumerate(member_ids)
    }


def split_by_shares(amount: float, shares: dict[int, int]) -> dict[int, float]:
    """Each member owes in proportion to their share count, e.g. {1: 1, 2: 2} is a 1:2 split."""
    total_shares = sum(shares.values())
    return {
        member_id: round(amount * count / total_shares, 2) for member_id, count in shares.items()
    }


def settle_up(net: dict[int, float]) -> list[tuple[int, int, float]]:
    """Turn net balances into (from, to, amount) transfers.

    Positive net means the member is owed money, negative means they owe it. The member who
    owes the most pays the member who is owed the most, until one of them is square; repeat.
    """
    debts = {member: -value for member, value in net.items() if value < 0}
    credits = {member: value for member, value in net.items() if value > 0}
    transfers = []
    while debts and credits:
        debtor = max(debts, key=debts.get)
        creditor = max(credits, key=credits.get)
        amount = round(min(debts[debtor], credits[creditor]), 2)
        transfers.append((debtor, creditor, amount))
        debts[debtor] = round(debts[debtor] - amount, 2)
        credits[creditor] = round(credits[creditor] - amount, 2)
        if debts[debtor] == 0:
            del debts[debtor]
        if credits[creditor] == 0:
            del credits[creditor]
    return transfers
