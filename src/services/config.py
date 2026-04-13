"""공유 설정 — 환경변수, 상수, 공통 인스턴스"""
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

# ── 환경변수 ──
NAVER_AD_API_KEY  = os.environ.get('NAVER_AD_API_KEY', '')
NAVER_AD_SECRET   = os.environ.get('NAVER_AD_SECRET', '')
NAVER_AD_CUSTOMER = os.environ.get('NAVER_AD_CUSTOMER', '')
NOTION_TOKEN      = os.environ.get('NOTION_TOKEN', '')
KEYWORD_DB_ID     = os.environ.get('KEYWORD_DB_ID', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GEMINI_API_KEY    = os.environ.get('GEMINI_API_KEY', '')
CONTENT_DB_ID     = os.environ.get('CONTENT_DB_ID', '')
CAFE24_CLIENT_ID  = os.environ.get('CAFE24_CLIENT_ID', '')
CAFE24_CLIENT_SECRET = os.environ.get('CAFE24_CLIENT_SECRET', '')
CAFE24_MALL_ID    = os.environ.get('CAFE24_MALL_ID', '')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')
WHISK_API_KEY      = os.environ.get('WHISK_API_KEY', '')
YOUTUBE_CLIENT_SECRET_FILE = os.environ.get('YOUTUBE_CLIENT_SECRET_FILE', '')
YOUTUBE_TOKEN_FILE = os.environ.get('YOUTUBE_TOKEN_FILE', '')
CAPCUT_DRAFTS_DIR  = os.environ.get('CAPCUT_DRAFTS_DIR', '')
THREADS_APP_ID     = os.environ.get('THREADS_APP_ID', '')
THREADS_APP_SECRET = os.environ.get('THREADS_APP_SECRET', '')
REDIRECT_BASE_URL = os.environ.get('REDIRECT_BASE_URL', 'http://localhost:8000')

# ── 파일 경로 ──
PROGRESS_FILE       = os.path.join(BASE_DIR, "keyword_progress.json")
CAFE24_TOKEN_FILE   = os.path.join(BASE_DIR, "cafe24_token.json")
SHORTS_DIR          = os.path.join(BASE_DIR, "shorts_output")
THREADS_ACCOUNTS_FILE = os.path.join(BASE_DIR, "threads_accounts.json")
THREADS_QUEUE_FILE  = os.path.join(BASE_DIR, "threads_queue.json")
VIRAL_ACCOUNTS_FILE = os.path.join(BASE_DIR, "viral_accounts.json")
API_USAGE_FILE      = os.path.join(BASE_DIR, "api_usage.json")
PERF_DATA_FILE      = os.path.join(BASE_DIR, "performance_data.json")
PERF_SCHEDULE_FILE  = os.path.join(BASE_DIR, "performance_schedule.json")
WORK_INBOX_FILE     = os.path.join(BASE_DIR, "work_inbox.json")

os.makedirs(SHORTS_DIR, exist_ok=True)

# ── 섹션 코드 매핑 ──
SECTION_MAP = {
    'pwl_nop':'파워링크','shp_gui':'쇼핑','shp_dui':'네이버가격비교',
    'shs_lis':'네이버플러스스토어','urB_coR':'신뢰도통합','urB_imM':'이미지',
    'urB_boR':'VIEW/블로그','ugB_adR':'브랜드콘텐츠','ugB_pkR':'브랜드콘텐츠',
    'ugB_bsR':'인기글','ugB_b1R':'신뢰도통합','ugB_b2R':'신뢰도통합',
    'ugB_b3R':'신뢰도통합','ugB_ipR':'인플루언서','ugB_qpR':'기타',
    'heL_htX':'AI브리핑','heB_ceR':'관련경험카페글','nws_all':'뉴스',
    'web_gen':'웹사이트','kwX_ndT':'함께많이찾는','exB_soT':'함께보면좋은',
    'kwL_ssT':'연관검색어','ldc_btm':'지식백과','bok_lst':'도서',
    'nmb_hpl':'플레이스','sit_4po':'웹사이트내검색','brd_brd':'브랜드서치',
    'abL_baX':'AI브리핑','abL_rtX':'AI브리핑','rrB_hdR':'리랭킹',
    'rrB_bdR':'리랭킹','nco_x58':'기타','ink_mik':'기타','nmb_rnk':'기타','ink_kid':'기타',
}
CONTENT_CODES = {'urB_coR','urB_boR','ugB_b1R','ugB_b2R','ugB_b3R','heB_ceR','ink_kid','ugB_bsR'}
NOISE_WORDS = ['더보기','클릭','전체보기','닫기','FAQ','인플루언서 참여','콘텐츠더보기','바로가기','자세히보기','관련검색어']

# ── 환각 탐지 설정 ──
HALLUCINATION_CONFIG = {
    "blog":         {"l3_enabled": True,  "threshold": 70},
    "cafe-seo":     {"l3_enabled": True,  "threshold": 70},
    "cafe-viral":   {"l3_enabled": True,  "threshold": 75},
    "jisikin":      {"l3_enabled": True,  "threshold": 80},
    "youtube":      {"l3_enabled": False, "threshold": 60},
    "tiktok":       {"l3_enabled": False, "threshold": 60},
    "shorts":       {"l3_enabled": False, "threshold": 60},
    "community":    {"l3_enabled": True,  "threshold": 75},
    "powercontent": {"l3_enabled": True,  "threshold": 70},
    "threads":      {"l3_enabled": False, "threshold": 60},
}

# ── 공유 인스턴스 ──
executor = ThreadPoolExecutor(max_workers=3)
selenium_semaphore = asyncio.Semaphore(1)
