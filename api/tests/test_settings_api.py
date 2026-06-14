def test_settings_set_and_list(client):
    assert client.get("/settings/").json() == []

    r = client.put("/settings/whisper_model", params={"value": "small"})
    assert r.status_code == 200
    assert r.json() == {"key": "whisper_model", "value": "small"}

    r = client.put("/settings/whisper_model", params={"value": "medium"})
    assert r.json()["value"] == "medium"

    listed = client.get("/settings/").json()
    assert listed == [{"key": "whisper_model", "value": "medium"}]
