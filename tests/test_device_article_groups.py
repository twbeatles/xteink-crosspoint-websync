from websync.upload.device_ids import group_articles_by_pending_targets


def test_groups_devices_by_their_exact_missing_article_set():
    articles = [{"url": "u1"}, {"url": "u2"}]
    targets = [
        {"ip": "10.0.0.1", "history_key": "d1", "alias_keys": ["d1"]},
        {"ip": "10.0.0.2", "history_key": "d2", "alias_keys": ["d2"]},
        {"ip": "10.0.0.3", "history_key": "d3", "alias_keys": ["d3"]},
    ]

    def is_synced(url, device):
        return (device, url) in {("d1", "u1"), ("d3", "u1")}

    groups = group_articles_by_pending_targets(
        is_synced, lambda _url: False, articles, targets
    )
    normalized = [(ips, [article["url"] for article in items]) for ips, items in groups]
    assert normalized == [
        (["10.0.0.1", "10.0.0.3"], ["u2"]),
        (["10.0.0.2"], ["u1", "u2"]),
    ]
