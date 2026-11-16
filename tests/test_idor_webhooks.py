"""Toggle/test/delete вебхука проверяют доступ к его проекту."""


def test_foreign_webhook_mutations_forbidden(team_ctx):
    client, _ann_id, p1, _p2 = team_ctx
    r = client.post(f"/api/projects/{p1}/webhooks",
                    json={"url": "https://example.com/hook",
                          "event_type": "annotation.saved"})
    assert r.status_code == 200, r.text
    wh_id = r.json()["id"]

    client.post("/api/auth/logout")
    client.post("/api/auth/login",
                json={"username": "ann", "password": "ann12345678"})
    assert client.post(f"/api/webhooks/{wh_id}/toggle").status_code == 403
    assert client.post(f"/api/webhooks/{wh_id}/test").status_code == 403
    assert client.delete(f"/api/webhooks/{wh_id}").status_code == 403
