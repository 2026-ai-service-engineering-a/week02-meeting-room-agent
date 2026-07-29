"""겹침 판정 overlaps() 유닛테스트 — DB 없이 도는 순수 함수 테스트.

빠르고 많은 테스트는 이 순수 계층에, 느리고 적은 테스트는 통합 계층에.
"""

from datetime import datetime

from app.services.reservations import overlaps


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 1, hour, minute)


def test_complete_overlap():
    assert overlaps(ts(10), ts(11), ts(10), ts(11))


def test_partial_overlap_front():
    assert overlaps(ts(10), ts(11), ts(10, 30), ts(11, 30))


def test_partial_overlap_back():
    assert overlaps(ts(10, 30), ts(11, 30), ts(10), ts(11))


def test_containment_both_ways():
    assert overlaps(ts(9), ts(12), ts(10), ts(11))
    assert overlaps(ts(10), ts(11), ts(9), ts(12))


def test_boundary_touch_is_not_overlap():
    # 딱 붙는 예약(10~11시 다음에 11~12시)은 겹침이 아닙니다 — 허용
    assert not overlaps(ts(10), ts(11), ts(11), ts(12))
    assert not overlaps(ts(11), ts(12), ts(10), ts(11))


def test_disjoint():
    assert not overlaps(ts(9), ts(10), ts(14), ts(15))
