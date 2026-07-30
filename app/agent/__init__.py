"""에이전트 루프 — '루프 하나, 도구 넷' 중 루프.

한 요청의 수명:
  1. 대화 이력을 DB에서 로드 (없으면 새 대화 생성)
  2. 모델 호출 → 도구 호출이 있으면 실행하고 결과를 이력에 붙여 다시 호출
  3. 도구 호출이 없으면(최종 답변) 새로 쌓인 메시지를 저장하고 반환

서버는 무상태입니다 — 이력은 언제나 DB에서 오고, DB로 돌아갑니다. 시스템
프롬프트는 저장하지 않고 매 요청 코드에서 새로 만듭니다(현재 시각이 들어가므로).

정중한 루프 가드·비용 로그는 3회전(feature/hardening)에서 더해집니다.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg.types.json import Json

from app.auth.deps import CurrentUser
from app.db import get_conn
from app.llm import complete
from app.tools import TOOL_SCHEMAS, run_tool

LOCAL_TZ = ZoneInfo("Asia/Seoul")

# 루프 가드 — 도구 호출 왕복의 상한. 멈춤조차 모델에게만 맡기지 않는다:
# 이 상한을 넘으면 코드가 정중히 종료해 무한 루프와 폭주 비용을 막는다.
MAX_STEPS = 8


class ConversationError(Exception):
    """대화 로드 거절 — 없는 대화(404)이거나 소유자가 아님(403)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _system_prompt() -> str:
    now = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    return (
        "당신은 사내 회의실 예약을 돕는 어시스턴트입니다.\n"
        f"현재 시각은 {now} (Asia/Seoul)입니다. "
        "'오늘'·'내일'·'오후' 같은 표현은 이 시각을 기준으로 해석하세요.\n\n"
        "쓸 수 있는 도구는 다섯 가지입니다:\n"
        "- search_rooms: 인원·설비 조건으로 회의실을 검색\n"
        "- check_availability: 특정 회의실의 특정 시간대 빈 시간을 조회\n"
        "- create_reservation: 회의실·시각·목적으로 예약을 확정\n"
        "- cancel_reservation: 예약을 취소 (본인 예약이거나 관리자만, 권한은 시스템이 검사)\n"
        "- list_reservations: 현재 사용자의 예약 내역을 조회 (예약 id 포함)\n\n"
        "사용자가 예약을 요청하면 필요한 정보(방·시간·목적)를 확인하고 "
        "create_reservation으로 확정하세요. 예약자·취소자·조회 범위는 시스템이 로그인한 "
        "본인으로 자동 지정하니 누구 이름으로 할지 묻지 마세요.\n"
        "'내 예약 보여줘' 같은 요청에는 list_reservations로 조회해 안내하세요. "
        "취소 요청에 예약 id가 없으면 사용자에게 id를 되묻지 말고, 먼저 "
        "list_reservations로 내역을 조회해 방·시간·목적이 맞는 예약의 id를 찾은 뒤 그 "
        "id로 cancel_reservation을 부르세요. 후보가 여럿이라 특정하기 어려울 때만 "
        "되물으세요.\n"
        "겹침·인원 초과·없는 방·권한 없음 등으로 거절되면 그 사유를 정중히 알리고, "
        "가능하면 다른 시간이나 방을 제안하세요. 남의 예약을 취소해 달라는 요청도 권한이 "
        "없으면 시스템이 막으니, 무리하게 우회하지 말고 사실대로 안내하세요.\n\n"
        "답변은 한국어로 간결하게 하세요."
    )


def _load_or_create(conn, conversation_id: int | None, user: CurrentUser):
    """(conversation_id, 이력) 을 돌려준다. 소유자 검사도 여기서 한다."""
    if conversation_id is None:
        row = conn.execute(
            "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (user.id,)
        ).fetchone()
        return row["id"], []

    conv = conn.execute(
        "SELECT user_id FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    if conv is None:
        raise ConversationError(404, f"대화 id={conversation_id} 는 없습니다")
    if conv["user_id"] != user.id:
        raise ConversationError(403, "본인 대화만 이어갈 수 있습니다")
    rows = conn.execute(
        "SELECT content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return conversation_id, [row["content"] for row in rows]


def _assistant_dict(message) -> dict:
    """LiteLLM 응답 메시지를 이력에 다시 넣을 수 있는 dict로 바꾼다 (도구 호출 포함)."""
    payload: dict = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return payload


def run_agent(
    *, user: CurrentUser, message: str, conversation_id: int | None = None
) -> dict:
    """자연어 한 문장을 받아 도구를 부르며 답한다. 응답에 conversation_id를 포함한다."""
    with get_conn() as conn:
        conversation_id, history = _load_or_create(conn, conversation_id, user)

        # 이번 턴에 새로 쌓이는 메시지들 (사용자 → 어시스턴트/도구 …)
        fresh: list[dict] = [{"role": "user", "content": message}]

        reply = ""
        for _ in range(MAX_STEPS):
            response = complete(
                [{"role": "system", "content": _system_prompt()}, *history, *fresh],
                tools=TOOL_SCHEMAS,
            )
            msg = response.choices[0].message
            fresh.append(_assistant_dict(msg))

            if not msg.tool_calls:
                reply = msg.content or ""
                break

            for call in msg.tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                result = run_tool(call.function.name, arguments, user=user)
                fresh.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
        else:
            # 루프 가드 발동 — 정중히 안내하고, 이 응답도 이력에 남겨 다음 턴이
            # 온전한 대화로 이어지게 한다 (도구 호출만 있고 최종 답이 없는 채로 끝내지 않는다).
            reply = (
                "요청을 처리하는 단계가 예상보다 많아졌습니다. "
                "조건을 조금 더 구체적으로 알려 주시겠어요?"
            )
            fresh.append({"role": "assistant", "content": reply})

        # 새로 쌓인 메시지를 순서대로 저장 (도구 호출·결과까지 그대로 — 루프 재개용)
        for item in fresh:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, item["role"], Json(item)),
            )

    return {"reply": reply, "conversation_id": conversation_id}
