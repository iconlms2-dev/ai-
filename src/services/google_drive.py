"""Google Drive 업로드 서비스.

OAuth 2.0으로 사용자 기존 구글 계정 연동.
최초 1회 브라우저 로그인 → google_token.json 저장 → 이후 자동 갱신.
"""
import os
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.services.config import BASE_DIR

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CREDENTIALS_FILE = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'google_token.json')
DRIVE_FOLDER_NAME = '숏츠_output'

_service = None
_folder_id = None


def _get_service():
    """Drive API 서비스 인스턴스 반환. 토큰 자동 갱신."""
    global _service
    if _service:
        return _service

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.warning("토큰 로드 실패: %s", e)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning("토큰 갱신 실패: %s — 재인증 필요", e)
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Google OAuth credentials.json이 없습니다.\n"
                    f"Google Cloud Console에서 OAuth 2.0 클라이언트 ID를 만들고\n"
                    f"credentials.json을 다운로드해서 {CREDENTIALS_FILE}에 저장하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=9090, open_browser=True)

        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

    _service = build('drive', 'v3', credentials=creds)
    return _service


def _ensure_folder() -> str:
    """Drive에 '숏츠_output' 폴더가 있으면 ID 반환, 없으면 생성."""
    global _folder_id
    if _folder_id:
        return _folder_id

    service = _get_service()
    query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        _folder_id = files[0]['id']
    else:
        metadata = {
            'name': DRIVE_FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        folder = service.files().create(body=metadata, fields='id').execute()
        _folder_id = folder['id']
        logger.info("Drive 폴더 생성: %s (%s)", DRIVE_FOLDER_NAME, _folder_id)

    return _folder_id


MIME_TYPES = {
    '.mp3': 'audio/mpeg',
    '.srt': 'text/plain',
    '.txt': 'text/plain',
}


def upload_file(filepath: str) -> dict:
    """파일을 Google Drive에 업로드.

    Returns:
        {"id": "파일ID", "name": "파일명", "url": "웹 링크"}
    """
    service = _get_service()
    folder_id = _ensure_folder()

    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, 'application/octet-stream')

    metadata = {
        'name': filename,
        'parents': [folder_id],
    }
    media = MediaFileUpload(filepath, mimetype=mime, resumable=True)

    file = service.files().create(
        body=metadata, media_body=media, fields='id, name, webViewLink',
    ).execute()

    logger.info("Drive 업로드 완료: %s → %s", filename, file.get('webViewLink'))

    return {
        'id': file['id'],
        'name': file['name'],
        'url': file.get('webViewLink', ''),
    }


def upload_shorts_files(audio_path: str, srt_path: str, txt_path: str, delete_local: bool = True) -> dict:
    """숏츠 TTS 파일 3개를 Drive에 업로드.

    Returns:
        {"audio": {...}, "srt": {...}, "txt": {...}}
    """
    result = {}

    for key, path in [('audio', audio_path), ('srt', srt_path), ('txt', txt_path)]:
        if path and os.path.exists(path):
            try:
                uploaded = upload_file(path)
                result[key] = uploaded
                if delete_local:
                    os.remove(path)
                    logger.info("로컬 파일 삭제: %s", path)
            except Exception as e:
                logger.error("Drive 업로드 실패 [%s]: %s", key, e)
                result[key] = {'error': str(e)}

    return result


def is_configured() -> bool:
    """Google Drive 연동이 설정되어 있는지 확인."""
    return os.path.exists(CREDENTIALS_FILE)
