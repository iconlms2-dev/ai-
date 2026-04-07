"""공통 헬퍼 함수"""
import re
from fastapi.responses import JSONResponse
from src.services.config import NOISE_WORDS


def error_response(message, status=500, details=None):
    """표준 에러 응답"""
    body = {'ok': False, 'error': message}
    if details:
        body['details'] = str(details)
    return JSONResponse(body, status_code=status)


def valid_kw(text):
    text = text.strip()
    if not text or len(text) < 2 or len(text) > 40:
        return False
    if not re.search(r'[가-힣]', text):
        return False
    for n in NOISE_WORDS:
        if n in text:
            return False
    return True
