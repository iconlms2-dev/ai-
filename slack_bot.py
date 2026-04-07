"""Slack 봇 — 마케팅 자동화 허브.

채널별 에이전트 + 배치 오케스트레이터 + 데일리 다이제스트 + 스케줄러.

실행: python3 slack_bot.py
환경변수: SLACK_BOT_TOKEN, SLACK_APP_TOKEN (.env)
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler

# ─────────────────────────── CONFIG ───────────────────────────

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
SLACK_APP_TOKEN = os.environ.get('SLACK_APP_TOKEN', '')

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    print("SLACK_BOT_TOKEN, SLACK_APP_TOKEN 환경변수 필요.")
    print("1. https://api.slack.com/apps 에서 앱 생성")
    print("2. .env에 SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... 추가")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "job_state.json")
SCHEDULE_FILE = os.path.join(BASE_DIR, "weekly_schedule.json")
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")

app = App(token=SLACK_BOT_TOKEN)
executor = ThreadPoolExecutor(max_workers=3)

# ─────────────────────────── 채널 설정 ───────────────────────────

CHANNELS = {
    "shorts": {"name": "shorts", "emoji": ":movie_camera:", "module": "src.pipeline_v2.shorts"},
    "blog": {"name": "blog", "emoji": ":memo:", "module": "src.pipeline_v2.blog"},
    "cafe-seo": {"name": "cafe-seo", "emoji": ":coffee:", "module": "src.pipeline_v2.cafe_seo"},
    "cafe-viral": {"name": "cafe-viral", "emoji": ":fire:", "module": "src.pipeline_v2.cafe_viral"},
    "jisikin": {"name": "jisikin", "emoji": ":question:", "module": "src.pipeline_v2.jisikin"},
    "youtube": {"name": "youtube", "emoji": ":tv:", "module": "src.pipeline_v2.youtube"},
    "tiktok": {"name": "tiktok", "emoji": ":musical_note:", "module": "src.pipeline_v2.tiktok"},
    "community": {"name": "community", "emoji": ":busts_in_silhouette:", "module": "src.pipeline_v2.community"},
    "powercontent": {"name": "powercontent", "emoji": ":zap:", "module": "src.pipeline_v2.powercontent"},
    "threads": {"name": "threads", "emoji": ":speech_balloon:", "module": "src.pipeline_v2.threads"},
}

# Slack 채널 ID 캐시 (채널명 → ID)
_channel_cache = {}


def _get_channel_id(channel_name: str) -> str:
    """Slack 채널 ID 조회 (캐시)."""
    if channel_name in _channel_cache:
        return _channel_cache[channel_name]
    try:
        result = app.client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in result["channels"]:
            _channel_cache[ch["name"]] = ch["id"]
        return _channel_cache.get(channel_name, "")
    except Exception:
        return ""


def _post(channel: str, text: str, thread_ts: str = None):
    """Slack 메시지 전송."""
    ch_id = _get_channel_id(channel) or channel
    kwargs = {"channel": ch_id, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    try:
        app.client.chat_postMessage(**kwargs)
    except Exception as e:
        print(f"Slack 전송 실패 [{channel}]: {e}")


def _post_blocks(channel: str, blocks: list, text: str = ""):
    """Slack Block Kit 메시지 전송."""
    ch_id = _get_channel_id(channel) or channel
    try:
        app.client.chat_postMessage(channel=ch_id, blocks=blocks, text=text)
    except Exception as e:
        print(f"Slack 블록 전송 실패 [{channel}]: {e}")


# ─────────────────────────── 파이프라인 실행기 ───────────────────────────

def run_pipeline(channel_key: str, args_str: str, slack_channel: str = None, thread_ts: str = None):
    """파이프라인을 subprocess로 실행하고 결과를 Slack에 보고."""
    ch = CHANNELS.get(channel_key)
    if not ch:
        _post(slack_channel or "general", f"알 수 없는 채널: {channel_key}")
        return

    target_channel = slack_channel or ch["name"]
    _post(target_channel, f"{ch['emoji']} *{channel_key}* 파이프라인 시작...", thread_ts)

    cmd = f"cd {BASE_DIR} && python3 -m {ch['module']} {args_str}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=600,
            cwd=BASE_DIR,
        )
        output = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
        if result.returncode == 0:
            # "최종 보고" 섹션 추출
            report = _extract_report(output)
            _post(target_channel, f"{ch['emoji']} *{channel_key}* 완료\n```\n{report}\n```", thread_ts)
        else:
            error = result.stderr[-1000:] if result.stderr else output[-1000:]
            _post(target_channel, f":x: *{channel_key}* 실패\n```\n{error}\n```", thread_ts)
    except subprocess.TimeoutExpired:
        _post(target_channel, f":warning: *{channel_key}* 타임아웃 (10분 초과)", thread_ts)
    except Exception as e:
        _post(target_channel, f":x: *{channel_key}* 에러: {e}", thread_ts)


def _extract_report(output: str) -> str:
    """출력에서 '최종 보고' 또는 마지막 섹션 추출."""
    markers = ["최종 보고", "v2 최종 보고", "====="]
    for marker in markers:
        idx = output.rfind(marker)
        if idx >= 0:
            return output[idx:].strip()[:2000]
    # 마지막 500자
    return output[-500:].strip()


# ─────────────────────────── 배치 오케스트레이터 ───────────────────────────

def parse_batch_command(text: str) -> list:
    """배치 명령 파싱. '블로그 3개 숏츠 2개' → [('blog', 3), ('shorts', 2)]

    지원 형식:
    - '블로그 3개 숏츠 2개'
    - 'blog 3 shorts 2'
    - '블로그 3, 숏츠 2'
    """
    channel_names_kr = {
        "숏츠": "shorts", "블로그": "blog", "카페seo": "cafe-seo", "카페SEO": "cafe-seo",
        "카페바이럴": "cafe-viral", "지식인": "jisikin", "유튜브": "youtube",
        "틱톡": "tiktok", "커뮤니티": "community", "파워컨텐츠": "powercontent",
        "쓰레드": "threads",
    }

    tasks = []
    # 패턴: (채널명)(공백)(숫자)(개)?
    pattern = r'(숏츠|블로그|카페seo|카페SEO|카페바이럴|지식인|유튜브|틱톡|커뮤니티|파워컨텐츠|쓰레드|shorts|blog|cafe-seo|cafe-viral|jisikin|youtube|tiktok|community|powercontent|threads)\s*(\d+)\s*개?'
    matches = re.findall(pattern, text, re.IGNORECASE)
    for name, count in matches:
        ch_key = channel_names_kr.get(name, name.lower())
        tasks.append((ch_key, int(count)))
    return tasks


def run_batch(tasks: list, default_args: dict, slack_channel: str, thread_ts: str = None):
    """배치 작업 실행. 각 채널 × 개수만큼 순차 실행."""
    total = sum(c for _, c in tasks)
    _post(slack_channel, f":rocket: 배치 시작: 총 {total}개 ({', '.join(f'{ch}×{n}' for ch, n in tasks)})", thread_ts)

    completed = 0
    failed = 0
    for channel_key, count in tasks:
        args_str = _build_args_str(channel_key, default_args)
        for i in range(count):
            try:
                _post(slack_channel, f"[{completed+failed+1}/{total}] {channel_key} #{i+1} 실행 중...", thread_ts)
                run_pipeline(channel_key, args_str, slack_channel, thread_ts)
                completed += 1
            except Exception as e:
                failed += 1
                _post(slack_channel, f":x: {channel_key} #{i+1} 실패: {e}", thread_ts)

    _post(slack_channel, f":checkered_flag: 배치 완료: {completed}/{total} 성공, {failed} 실패", thread_ts)


def _build_args_str(channel_key: str, args: dict) -> str:
    """채널별 기본 인자 문자열 생성."""
    # 공통 제품 정보
    product = args.get("product", {})
    base = ""
    if channel_key == "shorts":
        base = (f'--product "{product.get("name", "")}" '
                f'--target "{product.get("target", "")}" '
                f'--problem "{product.get("problem", "")}" '
                f'--emotion "{product.get("emotion", "")}" '
                f'--trust "{product.get("trust", "")}" '
                f'--cta "{product.get("cta", "")}"')
    elif channel_key in ("blog", "cafe-seo", "jisikin", "tiktok", "powercontent"):
        keyword = args.get("keyword", "")
        base = (f'--keyword "{keyword}" '
                f'--product-name "{product.get("name", "")}" '
                f'--brand-keyword "{product.get("brand_keyword", "")}" '
                f'--usp "{product.get("usp", "")}" '
                f'--target "{product.get("target", "")}" '
                f'--ingredients "{product.get("ingredients", "")}"')
    elif channel_key == "cafe-viral":
        base = (f'--category "{args.get("category", "")}" '
                f'--target "{product.get("target", "")}" '
                f'--topic "{args.get("topic", "")}" '
                f'--concern "{args.get("concern", "")}" '
                f'--product-category "{args.get("product_category", "")}" '
                f'--brand-keyword "{product.get("brand_keyword", "")}" '
                f'--product-name "{product.get("name", "")}" '
                f'--usp "{product.get("usp", "")}" '
                f'--ingredients "{product.get("ingredients", "")}"')
    elif channel_key == "youtube":
        base = (f'--keyword "{args.get("keyword", "")}" '
                f'--brand-keyword "{product.get("brand_keyword", "")}"')
    elif channel_key == "community":
        base = (f'--community "{args.get("community", "뽐뿌")}" '
                f'--strategy "{args.get("strategy", "1")}" '
                f'--keyword "{args.get("keyword", "")}" '
                f'--appeal "{args.get("appeal", "")}" '
                f'--buying-one "{args.get("buying_one", "")}" '
                f'--product-name "{product.get("name", "")}" '
                f'--brand-keyword "{product.get("brand_keyword", "")}" '
                f'--usp "{product.get("usp", "")}" '
                f'--target "{product.get("target", "")}" '
                f'--ingredients "{product.get("ingredients", "")}"')
    elif channel_key == "threads":
        base = (f'--type "{args.get("type", "traffic")}" '
                f'--keyword "{args.get("keyword", "")}" '
                f'--product-name "{product.get("name", "")}" '
                f'--brand-keyword "{product.get("brand_keyword", "")}" '
                f'--usp "{product.get("usp", "")}" '
                f'--target "{product.get("target", "")}" '
                f'--ingredients "{product.get("ingredients", "")}"')
    return base


# ─────────────────────────── 데일리 다이제스트 ───────────────────────────

def daily_digest():
    """매일 아침 데일리 다이제스트 → #report 채널."""
    try:
        # job_state.json에서 어제 생산량 집계
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        jobs = []
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                jobs = data.get("jobs", [])

        # 어제 + 오늘 작업 필터
        recent_jobs = [j for j in jobs if j.get("created_at", "").replace("-", "")[:8] in (yesterday, today)]

        # v2 프로젝트 폴더도 스캔
        v2_projects = []
        if os.path.isdir(PROJECTS_DIR):
            for channel in os.listdir(PROJECTS_DIR):
                ch_dir = os.path.join(PROJECTS_DIR, channel)
                if os.path.isdir(ch_dir):
                    for proj in os.listdir(ch_dir):
                        status_file = os.path.join(ch_dir, proj, "status.json")
                        if os.path.exists(status_file):
                            with open(status_file, "r") as f:
                                status = json.load(f)
                            if status.get("created_at", "").replace("-", "")[:8] in (yesterday, today):
                                v2_projects.append(status)

        # 채널별 집계
        channel_counts = {}
        for j in recent_jobs:
            ch = j.get("channel", "unknown")
            channel_counts[ch] = channel_counts.get(ch, 0) + 1
        for p in v2_projects:
            ch = p.get("channel", "unknown") + "_v2"
            channel_counts[ch] = channel_counts.get(ch, 0) + 1

        total = sum(channel_counts.values())

        # 에러 집계
        errors = [j for j in recent_jobs if j.get("revision_count", 0) > 2]
        v2_errors = [p for p in v2_projects if p.get("revision_count", 0) > 2]

        # 메시지 구성
        lines = [
            f":sunrise: *데일리 다이제스트* — {datetime.now().strftime('%Y-%m-%d %A')}",
            "",
            f"*어제~오늘 생산량: {total}건*",
        ]
        if channel_counts:
            for ch, cnt in sorted(channel_counts.items()):
                emoji = CHANNELS.get(ch, {}).get("emoji", ":pushpin:")
                lines.append(f"  {emoji} {ch}: {cnt}건")
        else:
            lines.append("  (생산 없음)")

        if errors or v2_errors:
            lines.append(f"\n:warning: *리비전 3회 초과: {len(errors) + len(v2_errors)}건*")
            for j in errors[:5]:
                lines.append(f"  - {j.get('job_id', '?')}: 리비전 {j.get('revision_count', '?')}회")

        # 오늘 스케줄
        lines.append(f"\n:calendar: *오늘 스케줄*")
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r") as f:
                schedule = json.load(f)
            daily = schedule.get("daily", {})
            for key, item in daily.items():
                if item.get("enabled"):
                    lines.append(f"  {item.get('time', '')} — {item.get('label', key)}")

        _post("report", "\n".join(lines))

    except Exception as e:
        _post("report", f":x: 다이제스트 생성 실패: {e}")


# ─────────────────────────── 소재 프리셋 관리 ───────────────────────────

PRESET_FILE = os.path.join(BASE_DIR, "slack_presets.json")


def load_presets() -> dict:
    if os.path.exists(PRESET_FILE):
        with open(PRESET_FILE, "r") as f:
            return json.load(f)
    return {}


def save_presets(presets: dict):
    with open(PRESET_FILE, "w") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)


# ─────────────────────────── Slack 이벤트 핸들러 ───────────────────────────

@app.message(re.compile(r"^!상태$", re.IGNORECASE))
def handle_status(message, say):
    """현재 시스템 상태 보고."""
    # 서버 상태
    try:
        import requests
        r = requests.get("http://localhost:8000", timeout=3)
        server_status = ":white_check_mark: 서버 정상" if r.status_code == 200 else f":x: 서버 에러 ({r.status_code})"
    except Exception:
        server_status = ":x: 서버 꺼짐"

    # job 수
    job_count = 0
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            job_count = len(json.load(f).get("jobs", []))

    # v2 프로젝트 수
    v2_count = 0
    if os.path.isdir(PROJECTS_DIR):
        for ch in os.listdir(PROJECTS_DIR):
            ch_dir = os.path.join(PROJECTS_DIR, ch)
            if os.path.isdir(ch_dir):
                v2_count += len([d for d in os.listdir(ch_dir) if os.path.isdir(os.path.join(ch_dir, d))])

    say(f"{server_status}\n"
        f"v1 작업: {job_count}건\n"
        f"v2 프로젝트: {v2_count}건\n"
        f"채널: {len(CHANNELS)}개 파이프라인 대기 중")


@app.message(re.compile(r"^!비용$|^!비용\s+(.+)", re.IGNORECASE))
def handle_cost(message, say, context):
    """API 비용 조회."""
    usage_file = os.path.join(BASE_DIR, "api_usage.json")
    if not os.path.exists(usage_file):
        say(":information_source: 아직 사용량 기록이 없습니다. 서버에서 콘텐츠를 생성하면 자동으로 기록됩니다.")
        return

    with open(usage_file, "r") as f:
        usage = json.load(f)

    records = usage.get("records", [])
    if not records:
        say(":information_source: 사용량 기록이 비어있습니다.")
        return

    # 기간 파싱 (기본: 이번 달)
    today = datetime.now()
    month_str = today.strftime("%Y-%m")

    # 이번 달 필터
    month_records = [r for r in records if r.get("date", "").startswith(month_str)]

    # 오늘
    today_str = today.strftime("%Y-%m-%d")
    today_records = [r for r in records if r.get("date") == today_str]

    # 어제
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_records = [r for r in records if r.get("date") == yesterday_str]

    # 집계
    def summarize(recs):
        total_input = sum(r.get("input_tokens", 0) for r in recs)
        total_output = sum(r.get("output_tokens", 0) for r in recs)
        total_cost = sum(r.get("cost_usd", 0) for r in recs)
        return total_input, total_output, total_cost, len(recs)

    m_in, m_out, m_cost, m_cnt = summarize(month_records)
    t_in, t_out, t_cost, t_cnt = summarize(today_records)
    y_in, y_out, y_cost, y_cnt = summarize(yesterday_records)

    # 채널별 이번 달
    channel_costs = {}
    for r in month_records:
        ch = r.get("channel", "unknown")
        channel_costs[ch] = channel_costs.get(ch, 0) + r.get("cost_usd", 0)

    # 일별 추이 (최근 7일)
    daily_costs = {}
    for i in range(7):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        day_recs = [r for r in records if r.get("date") == d]
        if day_recs:
            daily_costs[d] = sum(r.get("cost_usd", 0) for r in day_recs)

    lines = [
        f":moneybag: *API 비용 리포트*",
        f"",
        f"*이번 달 ({month_str})*",
        f"  총 비용: *${m_cost:.2f}*",
        f"  호출 횟수: {m_cnt}회",
        f"  입력: {m_in:,} 토큰 / 출력: {m_out:,} 토큰",
        f"",
        f"*오늘* — ${t_cost:.2f} ({t_cnt}회)",
        f"*어제* — ${y_cost:.2f} ({y_cnt}회)",
    ]

    if channel_costs:
        lines.append(f"\n*채널별 (이번 달)*")
        for ch, cost in sorted(channel_costs.items(), key=lambda x: -x[1]):
            lines.append(f"  {ch}: ${cost:.2f}")

    if daily_costs:
        lines.append(f"\n*일별 추이 (최근 7일)*")
        for d in sorted(daily_costs.keys()):
            bar = ":small_blue_diamond:" * max(1, int(daily_costs[d] / 0.1))
            lines.append(f"  {d}: ${daily_costs[d]:.2f} {bar}")

    # 전체 누적
    all_cost = sum(r.get("cost_usd", 0) for r in records)
    lines.append(f"\n*전체 누적: ${all_cost:.2f}* ({len(records)}회)")

    say("\n".join(lines))


@app.message(re.compile(r"^!다이제스트$", re.IGNORECASE))
def handle_digest(message, say):
    """수동 다이제스트 실행."""
    say(":mag: 다이제스트 생성 중...")
    executor.submit(daily_digest)


@app.message(re.compile(r"^!배치\s+(.+)", re.IGNORECASE))
def handle_batch(message, say, context):
    """/배치 블로그 3개 숏츠 2개"""
    text = context["matches"][0]
    tasks = parse_batch_command(text)
    if not tasks:
        say(":question: 파싱 실패. 예시: `/배치 블로그 3개 숏츠 2개`")
        return

    presets = load_presets()
    default_args = presets.get("default", {})
    if not default_args.get("product"):
        say(":warning: 소재 프리셋이 없습니다. `!소재설정` 먼저 실행하세요.\n"
            "예: `!소재설정 제품명=루테인 영양제, 브랜드=아이클리어, USP=마리골드 추출 루테인 20mg, 타겟=40대 직장인, 성분=루테인 지아잔틴, 키워드=루테인 효과`")
        return

    thread_ts = message.get("ts")
    say(f":rocket: 배치 작업 시작: {', '.join(f'{ch}×{n}' for ch, n in tasks)}")
    executor.submit(run_batch, tasks, default_args, message["channel"], thread_ts)


@app.message(re.compile(r"^!소재설정\s+(.+)", re.IGNORECASE))
def handle_preset(message, say, context):
    """/소재설정 제품명=루테인 영양제, 키워드=루테인 효과, ..."""
    text = context["matches"][0]
    presets = load_presets()

    # key=value 파싱
    pairs = re.findall(r'(\w+)\s*=\s*([^,]+)', text)
    product = presets.get("default", {}).get("product", {})
    args = presets.get("default", {})

    key_map = {
        "제품명": ("product", "name"), "브랜드": ("product", "brand_keyword"),
        "USP": ("product", "usp"), "usp": ("product", "usp"),
        "타겟": ("product", "target"), "성분": ("product", "ingredients"),
        "키워드": ("args", "keyword"), "문제": ("product", "problem"),
        "감정": ("product", "emotion"), "신뢰": ("product", "trust"),
        "CTA": ("product", "cta"), "cta": ("product", "cta"),
    }

    for k, v in pairs:
        v = v.strip()
        mapping = key_map.get(k)
        if mapping:
            if mapping[0] == "product":
                product[mapping[1]] = v
            else:
                args[mapping[1]] = v

    args["product"] = product
    presets["default"] = args
    save_presets(presets)

    say(f":white_check_mark: 소재 프리셋 저장 완료\n```\n{json.dumps(presets['default'], ensure_ascii=False, indent=2)}\n```")


@app.message(re.compile(r"^!채널생성$", re.IGNORECASE))
def handle_create_channels(message, say):
    """10개 채널 + report 자동 생성."""
    created = []
    existing = []
    channels_to_create = ["headquarters"] + list(CHANNELS.keys()) + ["report"]

    for ch_name in channels_to_create:
        try:
            result = app.client.conversations_create(name=ch_name)
            created.append(ch_name)
        except Exception as e:
            if "name_taken" in str(e):
                existing.append(ch_name)
            else:
                say(f":x: #{ch_name} 생성 실패: {e}")

    lines = []
    if created:
        lines.append(f":white_check_mark: 생성: {', '.join('#' + c for c in created)}")
    if existing:
        lines.append(f":information_source: 이미 존재: {', '.join('#' + c for c in existing)}")
    say("\n".join(lines) or "채널 생성 완료")


@app.message(re.compile(r"^!도움$|^!help$", re.IGNORECASE))
def handle_help(message, say):
    say("*사용 가능한 명령어*\n\n"
        ":pushpin: *기본*\n"
        "`!상태` — 서버 + 작업 현황\n"
        "`!비용` — API 비용 조회 (이번 달/오늘/채널별)\n"
        "`!다이제스트` — 수동 리포트 생성\n"
        "`!채널생성` — 10개 채널 + #report 자동 생성\n\n"
        ":package: *소재 관리*\n"
        "`!소재설정 제품명=X, 브랜드=Y, USP=Z, 타겟=T, 성분=I, 키워드=K` — 기본 소재 저장\n"
        "`!소재확인` — 현재 소재 프리셋 확인\n\n"
        ":rocket: *실행*\n"
        "`!배치 블로그 3개 숏츠 2개` — 여러 채널 일괄 실행\n"
        "`!실행 blog --keyword \"루테인 효과\" ...` — 단일 채널 직접 실행\n\n"
        ":calendar: *스케줄*\n"
        "`!스케줄확인` — 현재 스케줄 확인\n"
        "`!스케줄설정 09:00 블로그 3개 숏츠 2개` — 매일 자동 실행 설정\n")


@app.message(re.compile(r"^!소재확인$", re.IGNORECASE))
def handle_preset_check(message, say):
    presets = load_presets()
    default = presets.get("default", {})
    if default:
        say(f"*현재 소재 프리셋*\n```\n{json.dumps(default, ensure_ascii=False, indent=2)}\n```")
    else:
        say(":information_source: 소재 프리셋이 없습니다. `!소재설정`으로 설정하세요.")


@app.message(re.compile(r"^!실행\s+(\S+)\s*(.*)", re.IGNORECASE))
def handle_run(message, say, context):
    """/실행 blog --keyword "루테인 효과" ..."""
    channel_key = context["matches"][0]
    args_str = context["matches"][1] if len(context["matches"]) > 1 else ""

    if channel_key not in CHANNELS:
        say(f":question: 알 수 없는 채널: {channel_key}\n사용 가능: {', '.join(CHANNELS.keys())}")
        return

    thread_ts = message.get("ts")
    say(f"{CHANNELS[channel_key]['emoji']} *{channel_key}* 파이프라인 시작...")
    executor.submit(run_pipeline, channel_key, args_str, message["channel"], thread_ts)


@app.message(re.compile(r"^!스케줄확인$", re.IGNORECASE))
def handle_schedule_check(message, say):
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r") as f:
            schedule = json.load(f)
        say(f"*현재 스케줄*\n```\n{json.dumps(schedule, ensure_ascii=False, indent=2)[:2000]}\n```")
    else:
        say(":information_source: 스케줄 파일이 없습니다.")


@app.message(re.compile(r"^!스케줄설정\s+(\d{2}:\d{2})\s+(.+)", re.IGNORECASE))
def handle_schedule_set(message, say, context):
    """/스케줄 설정 09:00 블로그 3개 숏츠 2개"""
    time_str = context["matches"][0]
    batch_text = context["matches"][1]
    tasks = parse_batch_command(batch_text)
    if not tasks:
        say(":question: 파싱 실패. 예: `/스케줄 설정 09:00 블로그 3개 숏츠 2개`")
        return

    # 스케줄 저장
    schedule_entry = {
        "time": time_str,
        "tasks": [{"channel": ch, "count": n} for ch, n in tasks],
        "enabled": True,
        "created_at": datetime.now().isoformat(),
    }

    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r") as f:
            schedule = json.load(f)
    else:
        schedule = {}

    auto_batch = schedule.get("auto_batch", [])
    auto_batch.append(schedule_entry)
    schedule["auto_batch"] = auto_batch

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    say(f":white_check_mark: 스케줄 등록: 매일 {time_str}에 {', '.join(f'{ch}×{n}' for ch, n in tasks)}")


# ─────────────────────────── HQ 총괄 에이전트 ───────────────────────────

HQ_SYSTEM_PROMPT = """당신은 마케팅 자동화 시스템의 총괄 사장(HQ)입니다.
회장(사용자)의 지시를 받아 각 채널 팀장에게 업무를 배분합니다.

## 사용 가능한 채널 (팀)
- shorts: 숏츠 대본 제작
- blog: 블로그 원고 제작
- cafe-seo: 카페SEO 원고 제작
- cafe-viral: 카페바이럴 3단계 제작
- jisikin: 지식인 Q&A 제작
- youtube: 유튜브 댓글 제작
- tiktok: 틱톡 스크립트 제작
- community: 커뮤니티 침투글 제작
- powercontent: 파워컨텐츠 제작
- threads: 쓰레드 콘텐츠 제작

## 사용 가능한 명령
- BATCH: 콘텐츠 일괄 생성. 예: BATCH blog 3 shorts 2
- STATUS: 시스템 상태 확인
- COST: API 비용 조회
- PRESET: 소재 프리셋 확인
- DIGEST: 데일리 다이제스트 생성
- NONE: 단순 대화 (명령 실행 불필요)

## 응답 형식
반드시 아래 JSON 형식으로 응답하세요:
{"action": "BATCH|STATUS|COST|PRESET|DIGEST|NONE", "params": "파라미터", "reply": "회장에게 보낼 메시지"}

예시:
사용자: "블로그 3개 숏츠 2개 만들어줘"
→ {"action": "BATCH", "params": "블로그 3개 숏츠 2개", "reply": "블로그 3개, 숏츠 2개 제작 시작합니다."}

사용자: "요즘 비용 얼마나 나오고 있어?"
→ {"action": "COST", "params": "", "reply": "비용 현황을 확인해보겠습니다."}

사용자: "오늘 날씨 좋다"
→ {"action": "NONE", "params": "", "reply": "좋은 날씨네요! 오늘 콘텐츠 제작 계획이 있으시면 말씀해주세요."}
"""


def _call_hq_agent(user_message: str) -> dict:
    """HQ 총괄 에이전트 호출. Claude API로 의도 파악."""
    import requests as _req

    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    if not ANTHROPIC_API_KEY:
        return {"action": "NONE", "params": "", "reply": "API 키가 설정되지 않았습니다."}

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
    }
    payload = {
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 300,
        'system': HQ_SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': user_message}],
    }

    try:
        r = _req.post('https://api.anthropic.com/v1/messages', headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            data = r.json()
            text = data['content'][0]['text'] if data.get('content') else '{}'
            # usage 추적 (Haiku이므로 매우 저렴)
            usage = data.get('usage', {})
            from server import _track_usage
            _track_usage('claude-haiku-4-5-20251001', usage.get('input_tokens', 0), usage.get('output_tokens', 0), 'headquarters')
            # JSON 파싱
            import json as _json
            # JSON 블록 추출
            match = re.search(r'\{[^}]+\}', text)
            if match:
                return _json.loads(match.group())
            return {"action": "NONE", "params": "", "reply": text}
        return {"action": "NONE", "params": "", "reply": f"API 에러: {r.status_code}"}
    except Exception as e:
        return {"action": "NONE", "params": "", "reply": f"HQ 에러: {e}"}


def _handle_hq_action(action: str, params: str, say, message):
    """HQ 에이전트의 판단에 따라 실행."""
    if action == "BATCH":
        tasks = parse_batch_command(params)
        if tasks:
            presets = load_presets()
            default_args = presets.get("default", {})
            if not default_args.get("product"):
                say(":warning: 소재 프리셋이 없습니다. `!소재설정`으로 먼저 등록해주세요.")
                return
            thread_ts = message.get("ts")
            executor.submit(run_batch, tasks, default_args, "headquarters", thread_ts)
        else:
            say(":question: 배치 파싱 실패. 좀 더 구체적으로 말씀해주세요. 예: '블로그 3개 숏츠 2개 만들어줘'")

    elif action == "STATUS":
        # !상태와 동일 로직
        try:
            import requests as _req
            r = _req.get("http://localhost:8000", timeout=3)
            server_status = ":white_check_mark: 서버 정상" if r.status_code == 200 else f":x: 서버 에러"
        except Exception:
            server_status = ":x: 서버 꺼짐"
        job_count = 0
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                job_count = len(json.load(f).get("jobs", []))
        say(f"{server_status}\nv1 작업: {job_count}건\n채널: {len(CHANNELS)}개 대기 중")

    elif action == "COST":
        # !비용 핸들러 재사용
        handle_cost(message, say, context={"matches": [None]})

    elif action == "PRESET":
        presets = load_presets()
        default = presets.get("default", {})
        if default:
            say(f"*현재 소재 프리셋*\n```\n{json.dumps(default, ensure_ascii=False, indent=2)}\n```")
        else:
            say(":information_source: 소재 프리셋이 없습니다. `!소재설정`으로 설정해주세요.")

    elif action == "DIGEST":
        executor.submit(daily_digest)


@app.message(re.compile(r".*"))
def handle_hq_message(message, say):
    """#headquarters 채널에서 자연어 대화 처리. 다른 채널은 무시."""
    # 이미 !명령어로 처리된 메시지는 여기 안 옴 (위에서 먼저 매칭)
    # bot 자신의 메시지 무시
    if message.get("bot_id") or message.get("subtype"):
        return

    # #headquarters 채널인지 확인
    channel_id = message.get("channel", "")
    hq_id = _get_channel_id("headquarters")
    if not hq_id or channel_id != hq_id:
        return  # headquarters가 아니면 무시

    user_text = message.get("text", "").strip()
    if not user_text:
        return

    # HQ 에이전트 호출
    result = _call_hq_agent(user_text)
    action = result.get("action", "NONE")
    params = result.get("params", "")
    reply = result.get("reply", "")

    # 응답
    if reply:
        say(f":briefcase: {reply}")

    # 액션 실행
    if action != "NONE":
        _handle_hq_action(action, params, say, message)


# ─────────────────────────── 스케줄러 (APScheduler) ───────────────────────────

scheduler = BackgroundScheduler()


def scheduled_batch_run():
    """스케줄된 배치 작업 실행."""
    if not os.path.exists(SCHEDULE_FILE):
        return

    with open(SCHEDULE_FILE, "r") as f:
        schedule = json.load(f)

    now = datetime.now().strftime("%H:%M")
    auto_batch = schedule.get("auto_batch", [])

    for entry in auto_batch:
        if not entry.get("enabled"):
            continue
        if entry.get("time") == now:
            presets = load_presets()
            default_args = presets.get("default", {})
            tasks = [(t["channel"], t["count"]) for t in entry.get("tasks", [])]
            if tasks and default_args.get("product"):
                _post("report", f":alarm_clock: 스케줄 배치 실행: {now}")
                run_batch(tasks, default_args, "report")


def scheduled_digest():
    """스케줄된 데일리 다이제스트."""
    daily_digest()


# ─────────────────────────── MAIN ───────────────────────────

def main():
    print("=" * 50)
    print("  마케팅 자동화 Slack 봇 시작")
    print("=" * 50)
    print(f"채널: {len(CHANNELS)}개 파이프라인")
    print(f"명령어: /상태, /배치, /실행, /다이제스트, /소재설정, /스케줄")
    print()

    # APScheduler: 매분 스케줄 체크
    scheduler.add_job(scheduled_batch_run, 'interval', minutes=1)
    # 매일 09:00 다이제스트
    scheduler.add_job(scheduled_digest, 'cron', hour=9, minute=0)
    scheduler.start()

    # Socket Mode로 시작
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    print("Slack Socket Mode 연결 중...")
    handler.start()


if __name__ == "__main__":
    main()
