"""API tests for the expense splitter. Amounts are chosen to divide evenly."""


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_group_members_and_expense(client, trip, pay):
    group = trip["group"]
    assert group["name"] == "Weekend trip"
    assert group["share_token"]

    expense = pay("Asha", 300)
    assert expense["group_id"] == group["id"]
    assert sorted(expense["split"].values()) == [100.0, 100.0, 100.0]


def test_split_by_shares(trip, pay):
    ids = trip["ids"]
    expense = pay("Ravi", 400, split="shares", shares={ids["Asha"]: 1, ids["Ravi"]: 3})
    assert expense["split"] == {str(ids["Asha"]): 100.0, str(ids["Ravi"]): 300.0}


def test_balances_for_even_split(client, trip, pay):
    pay("Asha", 300)
    body = client.get(f"/groups/{trip['group']['id']}/balances").json()
    assert body["total_spent"] == 300.0
    by_name = {member["name"]: member for member in body["members"]}
    asha = by_name["Asha"]
    assert (asha["paid"], asha["owes"], asha["net"]) == (300.0, 100.0, 200.0)
    assert by_name["Ravi"]["net"] == -100.0
    assert by_name["Meera"]["net"] == -100.0


def test_settle_for_even_split(client, trip, pay):
    pay("Asha", 600)
    pay("Ravi", 300)
    body = client.get(f"/groups/{trip['group']['id']}/settle").json()
    # Each owes 300: Asha is owed 300, Ravi is square, Meera owes 300.
    assert body["transfers"] == [{"from": "Meera", "to": "Asha", "amount": 300.0}]


def test_share_summary_when_everyone_has_paid(client, trip, pay):
    pay("Asha", 300)
    pay("Asha", 100)
    pay("Ravi", 90)
    pay("Meera", 60)
    body = client.get(f"/share/{trip['group']['share_token']}").json()
    assert body["group"] == "Weekend trip"
    assert body["members"][0] == {
        "name": "Asha",
        "total_paid": 400.0,
        "expenses_paid": 2,
        "average_expense": 200.0,
    }


def test_unknown_group_and_share_link_return_404(client):
    assert client.post("/groups/999/members", json={"name": "Asha"}).status_code == 404
    assert client.get("/groups/999/balances").status_code == 404
    assert client.get("/groups/999/settle").status_code == 404
    assert client.get("/share/no-such-token").status_code == 404


def test_invalid_expenses_are_rejected(client, trip):
    url = f"/groups/{trip['group']['id']}/expenses"
    asha = trip["ids"]["Asha"]
    base = {"payer_id": asha, "amount": 100, "description": "test"}
    assert client.post(url, json={**base, "amount": -5}).status_code == 422
    assert client.post(url, json={**base, "split": "halves"}).status_code == 422
    assert client.post(url, json={**base, "payer_id": 999}).status_code == 400
    assert client.post(url, json={**base, "split": "shares"}).status_code == 400
    assert (
        client.post(url, json={**base, "split": "shares", "shares": {"999": 1}}).status_code == 400
    )


def test_equal_split_shares_add_up_to_the_amount(client, trip, pay):
    expense = pay("Asha", 1000)
    assert round(sum(expense["split"].values()), 2) == 1000.0
    body = client.get(f"/groups/{trip['group']['id']}/balances").json()
    assert round(sum(member["owes"] for member in body["members"]), 2) == body["total_spent"]
