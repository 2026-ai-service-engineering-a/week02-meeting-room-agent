"""회의실 예약 서비스 API — 인증·검색·예약·취소.

자연어 통로(/reserve)는 v1.0에서 에이전트가 연결됩니다.
"""

from fastapi import FastAPI

app = FastAPI(title="회의실 예약 에이전트", version="0.1.0")
