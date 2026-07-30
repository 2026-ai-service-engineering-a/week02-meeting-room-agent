"""PostgreSQL 연결 헬퍼.

- get_conn: 앱 전용 연결 (DATABASE_URL) — 예약 서비스가 읽고 씁니다.
- get_reporting_conn: v1.5 SQL 콘솔 전용 읽기 전용 연결 (REPORTING_DATABASE_URL).
  SELECT 권한을 리포팅 뷰에만 가진 reporter 롤로 붙으므로, 여기로는 쓰기도
  민감 컬럼도 닿지 않습니다 (권한은 코드가 아니라 DB가 강제).
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/meeting"
    )


def _reporting_url() -> str:
    return os.environ.get(
        "REPORTING_DATABASE_URL", "postgresql://reporter:reporter@localhost:5432/meeting"
    )


@contextmanager
def get_conn() -> Iterator[Connection]:
    """요청 단위의 짧은 연결. 블록이 정상 종료되면 커밋, 예외면 롤백합니다."""
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        yield conn


@contextmanager
def get_reporting_conn() -> Iterator[Connection]:
    """읽기 전용 reporter 롤로 붙는 짧은 연결 — v1.5 SQL 콘솔 전용."""
    with psycopg.connect(_reporting_url(), row_factory=dict_row) as conn:
        yield conn
