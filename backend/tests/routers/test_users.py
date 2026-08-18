"""Tests for backend/routers/users.py.

This endpoint exists so the book detail page can populate its "Loan to…"
picker, which means every signed-in member can see the member list.
"""


class TestListUsers:
    def test_lists_every_account(self, client, admin, member, other_user):
        listed = client.get("/api/users", headers=admin["headers"]).json()
        assert {u["username"] for u in listed} == {"admin", "member", "other"}

    def test_sorted_by_username(self, client, admin, member, other_user):
        listed = client.get("/api/users", headers=admin["headers"]).json()
        assert [u["username"] for u in listed] == ["admin", "member", "other"]

    def test_a_non_admin_may_also_list(self, client, admin, member):
        assert client.get("/api/users", headers=member["headers"]).status_code == 200

    def test_password_hashes_are_never_exposed(self, client, admin):
        """UserOut has no password field; this guards against it being added."""
        listed = client.get("/api/users", headers=admin["headers"]).json()
        assert all("password_hash" not in u and "password" not in u for u in listed)

    def test_exposes_the_admin_flag(self, client, admin, member):
        by_name = {
            u["username"]: u for u in client.get("/api/users", headers=admin["headers"]).json()
        }
        assert by_name["admin"]["is_admin"] is True
        assert by_name["member"]["is_admin"] is False

    def test_requires_authentication(self, client):
        assert client.get("/api/users").status_code == 401
