"""KAIZODE の発注前判定（probe_facility）。"""
from __future__ import annotations

from src import kaizode


class _Client:
    def __init__(self, datasets, counts=None, boom_count=False):
        self._ds = datasets
        self._counts = counts or {}
        self._boom = boom_count
        self.counted: list = []

    def list_datasets(self):
        return self._ds

    def count_reviews(self, dataset_id, published_since=None):
        self.counted.append(dataset_id)
        if self._boom:
            raise kaizode.KaizodeError("500")
        return self._counts.get(dataset_id)


def _ds(did, name, status=kaizode.STATUS_DONE):
    return {"dataset_id": did, "dataset_name": name, "status": status}


def test_no_match_asks_for_no_count():
    c = _Client([_ds("a", "別の施設")])
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert not pr.has_existing
    assert pr.known_count is None and pr.probe_cost == 0
    assert c.counted == []


def test_done_dataset_gives_an_exact_count():
    c = _Client([_ds("a", "名古屋市美術館")], {"a": 1240})
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.known_count == 1240
    assert pr.probe_cost == 1          # 聞くのに1件引かれる


def test_running_dataset_is_not_counted():
    """走っている最中のものはまだ増える。確定値にしない。"""
    c = _Client([_ds("a", "名古屋市美術館", status=10)])
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.has_existing and not pr.ready
    assert pr.known_count is None and c.counted == []


def test_several_done_datasets_are_summed():
    c = _Client([_ds("a", "名古屋市美術館 本館"), _ds("b", "名古屋市美術館 別館")],
                {"a": 800, "b": 440})
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.known_count == 1240 and pr.probe_cost == 2


def test_unreadable_total_falls_back_to_estimate():
    """1つでも読めなければ合計を名乗らない。**0 に潰さない。**"""
    c = _Client([_ds("a", "名古屋市美術館"), _ds("b", "名古屋市美術館 別館")],
                {"a": 800, "b": None})
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.known_count is None
    assert pr.probe_cost == 2          # 引かれたぶんは残す


def test_api_error_is_reported_not_raised():
    c = _Client([_ds("a", "名古屋市美術館")], boom_count=True)
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.error and pr.known_count is None


# ── 一覧の review_count を使う（マニュアル /manual/api/ で確認） ──────── #
def _ds_with_urls(did, counts, status=kaizode.STATUS_DONE):
    return {"dataset_id": did, "dataset_name": "名古屋市美術館", "status": status,
            "urls": [{"url": f"u{i}", "review_count": c} for i, c in enumerate(counts)]}


def test_saved_count_sums_the_urls():
    assert kaizode.saved_count(_ds_with_urls("a", [800, 440])) == 1240


def test_saved_count_is_none_when_any_url_lacks_it():
    ds = _ds_with_urls("a", [800, 440])
    del ds["urls"][1]["review_count"]
    assert kaizode.saved_count(ds) is None
    assert kaizode.saved_count({"dataset_id": "a"}) is None


def test_probe_uses_the_list_count_and_costs_nothing():
    """一覧に件数があれば count_reviews を呼ばない（枠を使わない）。"""
    c = _Client([_ds_with_urls("a", [1240])])
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.known_count == 1240
    assert pr.probe_cost == 0 and c.counted == []


def test_probe_falls_back_to_counting_when_the_list_has_no_count():
    c = _Client([_ds("a", "名古屋市美術館")], {"a": 1240})
    pr = kaizode.probe_facility(c, "名古屋市美術館")
    assert pr.known_count == 1240 and pr.probe_cost == 1


def test_zero_in_the_list_is_an_empty_collection():
    pr = kaizode.probe_facility(_Client([_ds_with_urls("a", [0])]), "名古屋市美術館")
    assert pr.empty_ready and not pr.usable and pr.known_count is None


# ── 取り直しは二重に走らせない ────────────────────────────────────── #
class _Resp:
    status_code = 202

    def json(self):
        return {"data": {"status": 10}}


class _Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return _Resp()


def test_rerun_sends_the_same_uuid_as_operation_id_and_idempotency_key():
    cl = kaizode.KaizodeClient(api_key="k")
    cl._session = _Session()
    cl.min_interval = 0
    cl.rerun_dataset("ds1")
    call = cl._session.calls[0]
    assert call["url"].endswith("/datasets/ds1/rerun")
    op = call["json"]["operationId"]
    assert call["headers"]["Idempotency-Key"] == op
    assert call["headers"]["x-api-key"] == "k"
    assert "urls" not in call["json"]          # 省略時は登録済み URL で再実行
