"""Tests for the classification scheme routes in routers/settings.py."""

URL = "/api/settings/classification-schemes"
RVK = {"scheme": "rvk", "name": "Regensburger Verbundklassifikation", "filing": "lcc"}


def test_any_member_may_list_them_built_in_first(client, member):
    res = client.get(URL, headers=member["headers"])

    assert res.status_code == 200
    assert [row["scheme"] for row in res.json()] == ["ddc", "lcc", "gnd", "lcsh"]
    assert all(row["built_in"] for row in res.json())


def test_a_member_may_not_define_one(client, member):
    assert client.post(URL, json=RVK, headers=member["headers"]).status_code == 403


def test_an_admin_defines_one_and_it_is_listed(client, admin):
    created = client.post(URL, json=RVK, headers=admin["headers"])

    assert created.status_code == 201
    assert created.json() == RVK | {"built_in": False}
    assert client.get(URL, headers=admin["headers"]).json()[-1]["scheme"] == "rvk"


def test_a_code_outside_the_pattern_is_refused(client, admin):
    assert client.post(URL, json=RVK | {"scheme": "RVK 1"}, headers=admin["headers"]).status_code == 422


def test_an_admin_renames_one(client, admin):
    client.post(URL, json=RVK, headers=admin["headers"])
    res = client.patch(f"{URL}/rvk", json={"name": "RVK"}, headers=admin["headers"])

    assert res.status_code == 200
    assert res.json()["name"] == "RVK"


def test_renaming_a_built_in_one_is_a_409(client, admin):
    assert client.patch(f"{URL}/ddc", json={"name": "Dewey"}, headers=admin["headers"]).status_code == 409


def test_deleting_one_a_book_quotes_is_a_409_naming_the_count(client, admin, make_book):
    client.post(URL, json=RVK, headers=admin["headers"])
    make_book(admin["headers"], classifications=[{"scheme": "rvk", "number": "ST 250"}])

    res = client.delete(f"{URL}/rvk", headers=admin["headers"])

    assert res.status_code == 409
    assert res.json()["detail"] == {
        "message": "1 book you can see still uses this scheme, so it cannot be deleted.",
        "code": "scheme_in_use",
        "count": 1,
    }


def test_deleting_an_unknown_one_is_a_404(client, admin):
    assert client.delete(f"{URL}/udc", headers=admin["headers"]).status_code == 404
