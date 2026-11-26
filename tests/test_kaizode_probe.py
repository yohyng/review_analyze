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
