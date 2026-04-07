"""마케팅 자동화 대시보드 — 백엔드 서버 (진입점)"""
from src.api import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
