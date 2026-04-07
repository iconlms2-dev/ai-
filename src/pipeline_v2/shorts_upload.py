"""숏츠 YouTube 업로드 — YouTube Data API v3.

OAuth2 인증 → 영상 업로드 → 썸네일 설정 → 메타데이터 설정.
"""
import json
import os
import time
from typing import Optional

from src.services.config import YOUTUBE_CLIENT_SECRET_FILE, YOUTUBE_TOKEN_FILE


def _get_youtube_service():
    """YouTube Data API 서비스 객체 생성 (OAuth2)."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request as GRequest
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "google-api-python-client, google-auth-oauthlib 패키지 필요. "
            "pip install google-api-python-client google-auth-oauthlib"
        )

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    # 저장된 토큰 로드
    if YOUTUBE_TOKEN_FILE and os.path.exists(YOUTUBE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, SCOPES)

    # 토큰 갱신 또는 새로 인증
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GRequest())
        else:
            if not YOUTUBE_CLIENT_SECRET_FILE or not os.path.exists(YOUTUBE_CLIENT_SECRET_FILE):
                raise RuntimeError(
                    "YOUTUBE_CLIENT_SECRET_FILE이 설정되지 않았거나 파일이 없습니다. "
                    "Google Cloud Console에서 OAuth2 클라이언트 JSON을 다운로드하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRET_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        if YOUTUBE_TOKEN_FILE:
            os.makedirs(os.path.dirname(YOUTUBE_TOKEN_FILE), exist_ok=True)
            with open(YOUTUBE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "22",
    privacy: str = "private",
    thumbnail_path: Optional[str] = None,
) -> dict:
    """YouTube에 영상 업로드.

    Args:
        video_path: 렌더링된 영상 파일 경로
        title: 영상 제목
        description: 설명
        tags: 태그 리스트
        category_id: YouTube 카테고리 ID (22=People & Blogs)
        privacy: 공개 설정 (private/unlisted/public)
        thumbnail_path: 썸네일 이미지 경로 (선택)

    Returns: {video_id, url, status}
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"영상 파일 없음: {video_path}")

    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise RuntimeError("google-api-python-client 패키지 필요")

    youtube = _get_youtube_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # 업로드
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"  YouTube 업로드 중: {os.path.basename(video_path)}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    진행: {int(status.progress() * 100)}%")

    video_id = response["id"]
    result = {
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}",
        "status": response.get("status", {}).get("privacyStatus", privacy),
    }

    # 썸네일 설정
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/png")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=thumb_media,
            ).execute()
            result["thumbnail_set"] = True
            print(f"  썸네일 설정 완료")
        except Exception as e:
            print(f"  썸네일 설정 실패: {e}")
            result["thumbnail_set"] = False

    print(f"  업로드 완료: {result['url']}")
    return result


def check_rendered_video(project_dir: str) -> Optional[str]:
    """프로젝트 폴더에서 렌더링된 영상 파일 탐색.

    CapCut 렌더링 후 09_upload/ 또는 프로젝트 루트에 .mp4 파일이 있는지 확인.
    """
    search_dirs = [
        os.path.join(project_dir, "09_upload"),
        os.path.join(project_dir, "08_edit"),
        project_dir,
    ]

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.endswith(".mp4") and os.path.getsize(os.path.join(d, f)) > 0:
                return os.path.join(d, f)

    return None
