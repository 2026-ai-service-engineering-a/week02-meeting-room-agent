"""PostgreSQL 연결 헬퍼 — DATABASE_URL 환경변수 하나로 연결합니다."""

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


@contextmanager
def get_conn() -> Iterator[Connection]:
    """요청 단위의 짧은 연결. 블록이 정상 종료되면 커밋, 예외면 롤백합니다."""
    with psycopg.connect(_database_url(), row_factory=dict_row) as conn:
        yield conn
