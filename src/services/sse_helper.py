"""SSE 헬퍼 — sse-starlette 기반.

기존 `_sse()` + `StreamingResponse` 패턴을 최소 변경으로 대체.
EventSourceResponse가 연결 끊김 감지, graceful shutdown, 재연결을 자동 처리.

마이그레이션 가이드:
  Before:
    def _sse(obj): return "data: " + json.dumps(obj) + "\\n\\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

  After:
    from src.services.sse_helper import sse_dict as _sse, SSEResponse
    return SSEResponse(generate())
"""
import json

from sse_starlette import EventSourceResponse


# EventSourceResponse 재노출 (라우터에서 직접 import 편의)
SSEResponse = EventSourceResponse


def sse_dict(obj):
    """기존 _sse() 대체 — EventSourceResponse가 이해하는 dict 반환.

    EventSourceResponse는 generator가 yield하는 dict의
    "data", "event", "id", "retry" 키를 SSE 프레임으로 변환.

    주의: event 키를 포함하면 "event: xxx\ndata: {...}\n\n" 형태가 되어
    프론트엔드의 buf.split('\\n\\n') → startsWith('data: ') 파싱이 깨짐.
    data 키만 사용하여 "data: {...}\n\n" 형태를 유지.
    """
    return {
        "data": json.dumps(obj, ensure_ascii=False),
    }
