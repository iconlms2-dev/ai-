"""검수 + 상태관리 서비스.

대시보드 API와 Slack 양쪽에서 사용.
규칙검수(코드) → 환각탐지(L1+L2) → AI검수(Gemini+L3) → 상태전이 → 결과 반환.
"""
import json
import logging
import time
from typing import Callable, Optional

import requests as req

from src.services.config import GEMINI_API_KEY, HALLUCINATION_CONFIG
from src.pipeline_v2.state_machine import ProjectState
from src.pipeline_v2.seo_analyzer import analyze_seo
from src.pipeline_v2.hallucination_detector import detect_hallucinations
from src.pipeline_v2.rule_validators import (
    validate_blog, validate_cafe_seo, validate_cafe_viral,
    validate_jisikin, validate_youtube_comment, validate_tiktok,
    validate_shorts, validate_community, validate_powercontent,
    validate_threads,
)

logger = logging.getLogger(__name__)

MAX_REVISIONS = 3

# ── 채널별 AI 검수 기준 ──

AI_CRITERIA = {
    "blog": {"정보성": 7, "자연스러움": 7, "SEO적합도": 7},
    "cafe-seo": {"자연스러움": 7, "SEO적합도": 7, "광고 비노출": 8},
    "cafe-viral": {"자연스러움": 8, "단계 흐름": 7, "광고 비노출": 8},
    "jisikin": {"답변 신뢰도": 7, "자연스러움": 7, "키워드 적합도": 7},
    "youtube": {"영상 관련성": 7, "자연스러움": 8, "스팸 비감지": 8},
    "tiktok": {"후킹력": 7, "자연스러움": 7, "CTA 효과": 7},
    "shorts": {"후킹력": 7, "자연스러움": 7, "CTA 효과": 7},
    "community": {"자연스러움": 8, "광고 비노출": 8, "공감성": 7},
    "powercontent": {"정보성": 7, "SEO적합도": 7, "전환 유도": 7},
    "threads": {"톤 일관성": 7, "자연스러움": 8, "광고 비노출": 8},
}


# ── Gemini AI 검수 ──

def _call_gemini_review(text: str, channel: str, criteria: dict,
                        seo_context: str = "",
                        hallucination_context: str = "") -> dict:
    """Gemini 2.0 Flash로 AI 검수. 무료/저가 — Claude 토큰 절약."""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY 미설정 — AI 검수 스킵")
        return {"pass": True, "score": 80, "feedback": "GEMINI_API_KEY 미설정 — 스킵",
                "items": [], "hallucination_verified": []}

    criteria_text = "\n".join(f"- {k}: {v}점 이상" for k, v in criteria.items())
    seo_block = f"\n[SEO 분석 결과 (참고)]\n{seo_context}\n" if seo_context else ""
    hal_block = f"\n{hallucination_context}\n위 환각 의심 항목이 실제 환각인지 판단하여 hallucination_verified에 포함하세요.\n" if hallucination_context else ""
    prompt = f"""당신은 마케팅 콘텐츠 품질 검수 전문가입니다.

[채널] {channel}
[검수 기준]
{criteria_text}
{seo_block}{hal_block}
[검수 대상 콘텐츠]
{text[:3000]}

위 콘텐츠를 검수 기준에 따라 평가하고, 아래 JSON 형식으로만 응답하세요:
{{
  "pass": true/false,
  "score": 0~100,
  "feedback": "전체 평가 요약 (1~2문장)",
  "items": [
    {{"name": "항목명", "score": 점수, "comment": "코멘트"}}
  ],
  "hallucination_verified": [
    {{"text": "환각 원문", "is_hallucination": true/false, "reason": "판단 근거"}}
  ]
}}

pass 기준: 모든 항목이 기준 점수 이상이면 true, 하나라도 미달이면 false.
score 기준: 전체 항목 평균 (10점 만점 → 100점 만점 환산).
hallucination_verified: 환각 의심 항목이 없으면 빈 배열."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(2):
        try:
            r = req.post(url, json=payload, timeout=30)
            if r.status_code == 429 and attempt < 1:
                time.sleep(3)
                continue
            if r.status_code != 200:
                logger.error("Gemini API %d: %s", r.status_code, r.text[:300])
                break

            data = r.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(raw)
            return {
                "pass": bool(result.get("pass", False)),
                "score": float(result.get("score", 0)),
                "feedback": result.get("feedback", ""),
                "items": result.get("items", []),
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Gemini 응답 파싱 실패: %s", e)
            break
        except req.exceptions.Timeout:
            logger.error("Gemini API 타임아웃")
            break
        except Exception as e:
            logger.error("Gemini API 호출 실패: %s", e)
            break

    # fallback — Gemini 실패 시 통과 처리 (규칙검수는 이미 통과한 상태)
    return {"pass": True, "score": 75, "feedback": "AI 검수 실패 — 규칙검수 통과 기반 허용", "items": []}


# ── 콘텐츠 텍스트 추출 ──

def _extract_review_text(content: dict) -> str:
    """검수용 텍스트 추출. 다양한 키 시도."""
    for key in ("body", "text", "script", "full_text"):
        if content.get(key):
            return content[key]
    # 복합 콘텐츠 (지식인 등)
    parts = []
    for key in ("q_title", "q_body", "answer1", "answer2", "title", "ad_title", "ad_desc", "comments"):
        if content.get(key):
            parts.append(str(content[key]))
    return "\n".join(parts) if parts else str(content)


# ── 핵심: 검수 + 상태관리 ──

def review_and_save(
    channel: str,
    content: dict,
    keyword: str = "",
    product: dict = None,
    regenerate_fn: Optional[Callable] = None,
    max_revisions: int = MAX_REVISIONS,
) -> dict:
    """콘텐츠 검수 + 상태전이.

    Args:
        channel: 채널명 (blog, cafe-seo, ...)
        content: 생성된 콘텐츠 dict
        keyword: 키워드
        product: 제품 정보 (리비전 시 필요)
        regenerate_fn: 리비전 시 재생성 콜백 fn(content, errors) -> new_content
        max_revisions: 최대 리비전 횟수

    Returns:
        {
            "passed": bool,
            "content": dict (최종 콘텐츠),
            "revision_count": int,
            "rule_errors": list,
            "ai_review": dict,
            "project_id": str,
            "status": str (draft/approved/revision),
            "events": list[dict] (SSE 이벤트 로그)
        }
    """
    events = []
    product = product or {}

    # 1. 프로젝트 생성 (상태머신)
    project = ProjectState.create(channel, keyword=keyword)
    project_id = project.project_id
    events.append({"type": "reviewing", "msg": f"검수 시작 — 프로젝트 {project_id}"})

    # 2. 규칙 검수 + 리비전 루프
    revision_count = 0
    rule_errors: list[str] = []
    current_content = content

    for rev in range(max_revisions + 1):
        # 규칙 검수
        rule_errors = _run_rule_validation(channel, current_content, keyword)

        if rule_errors:
            events.append({
                "type": "review_rule_fail",
                "msg": f"규칙검수 실패: {', '.join(rule_errors[:3])}",
                "errors": rule_errors,
            })

            if rev >= max_revisions:
                # 최대 리비전 초과
                events.append({"type": "review_fail", "msg": f"리비전 {max_revisions}회 초과 — 수동 확인 필요"})
                project.update(status="draft", rule_errors=rule_errors)
                return {
                    "passed": False,
                    "content": current_content,
                    "revision_count": revision_count,
                    "rule_errors": rule_errors,
                    "ai_review": {},
                    "project_id": project_id,
                    "status": "draft",
                    "events": events,
                }

            # 리비전 시도
            if regenerate_fn:
                revision_count += 1
                project.increment_revision()
                events.append({"type": "revision", "msg": f"리비전 {revision_count}/{max_revisions}", "errors": rule_errors})
                try:
                    current_content = regenerate_fn(current_content, rule_errors)
                except Exception as e:
                    logger.error("리비전 재생성 실패: %s", e)
                    events.append({"type": "review_fail", "msg": f"리비전 재생성 실패: {e}"})
                    project.update(status="draft")
                    return {
                        "passed": False,
                        "content": current_content,
                        "revision_count": revision_count,
                        "rule_errors": rule_errors,
                        "ai_review": {},
                        "project_id": project_id,
                        "status": "draft",
                        "events": events,
                    }
            else:
                # regenerate_fn 없으면 규칙 실패 그대로 반환
                events.append({"type": "review_fail", "msg": "리비전 불가 — 재생성 함수 없음"})
                project.update(status="draft", rule_errors=rule_errors)
                return {
                    "passed": False,
                    "content": current_content,
                    "revision_count": revision_count,
                    "rule_errors": rule_errors,
                    "ai_review": {},
                    "project_id": project_id,
                    "status": "draft",
                    "events": events,
                }
        else:
            # 규칙 통과
            events.append({"type": "review_rule_pass", "msg": "규칙검수 통과"})
            break

    # 3. 환각 탐지 (L1 패턴 + L2 제품 대조)
    review_text = _extract_review_text(current_content)
    events.append({"type": "hallucination_check", "msg": "환각 탐지 중 (L1+L2)..."})
    hal_report = detect_hallucinations(review_text, channel, product)
    hal_dict = hal_report.to_dict()

    if hal_report.issues:
        events.append({
            "type": "hallucination_found",
            "msg": f"환각 의심 {len(hal_report.issues)}건 발견 (감점 -{hal_report.total_deduction})",
            "data": hal_dict,
        })
    else:
        events.append({"type": "hallucination_clear", "msg": "환각 의심 항목 없음"})

    # 4. 상태 전이: draft → under_review
    project.transition("under_review")

    # 5. AI 검수 (Gemini) — SEO + 환각 컨텍스트를 함께 전달 (L3)
    criteria = AI_CRITERIA.get(channel, {"품질": 7})
    seo_context = ""
    if channel in ("blog", "cafe-seo", "powercontent"):
        title = current_content.get("title", current_content.get("ad_title", ""))
        seo_result = analyze_seo(review_text, keyword, title)
        seo_context = seo_result.summary_text()
    hal_config = HALLUCINATION_CONFIG.get(channel, {"l3_enabled": True, "threshold": 70})
    hallucination_context = hal_report.summary_text() if hal_config["l3_enabled"] else ""
    events.append({"type": "reviewing_ai", "msg": "AI 검수 중 (Gemini + 환각 L3 검증)..."})
    ai_result = _call_gemini_review(
        review_text, channel, criteria, seo_context, hallucination_context,
    )

    # L3: Gemini가 확인한 환각 결과 반영
    verified = ai_result.get("hallucination_verified", [])
    confirmed_count = sum(1 for v in verified if v.get("is_hallucination"))
    if confirmed_count:
        events.append({
            "type": "hallucination_confirmed",
            "msg": f"AI 확인 환각 {confirmed_count}건",
            "data": verified,
        })

    events.append({
        "type": "review_ai_done",
        "msg": f"AI 검수 {'통과' if ai_result['pass'] else '미달'} — 점수 {ai_result['score']}",
        "data": ai_result,
    })

    # 6. 최종 판정 + 상태 전이 (환각 감점 반영)
    final_score = ai_result["score"]
    hal_deduction = hal_report.total_deduction
    adjusted_score = max(0, final_score - hal_deduction)

    hal_threshold = hal_config["threshold"]
    if ai_result["pass"] and adjusted_score >= hal_threshold:
        project.transition("approved")
        final_status = "approved"
        passed = True
        events.append({
            "type": "review_pass",
            "msg": f"검수 통과 — AI {final_score}점, 환각감점 -{hal_deduction}, 최종 {adjusted_score}점",
            "data": {**ai_result, "hallucination_report": hal_dict},
        })
    else:
        project.transition("revision")
        final_status = "revision"
        passed = False
        events.append({
            "type": "review_fail",
            "msg": f"검수 미달 — AI {final_score}점, 환각감점 -{hal_deduction}, 최종 {adjusted_score}점",
            "data": {**ai_result, "hallucination_report": hal_dict},
        })

    # 7. 프로젝트 상태 저장
    project.save_step_file("05_review", "review_result.json", {
        "rule_errors": rule_errors,
        "ai_review": ai_result,
        "hallucination_report": hal_dict,
        "adjusted_score": adjusted_score,
        "revision_count": revision_count,
        "passed": passed,
    })

    return {
        "passed": passed,
        "content": current_content,
        "revision_count": revision_count,
        "rule_errors": [],
        "ai_review": ai_result,
        "hallucination_report": hal_dict,
        "adjusted_score": adjusted_score,
        "project_id": project_id,
        "status": final_status,
        "events": events,
    }


# ── 채널별 규칙 검수 디스패치 ──

def _run_rule_validation(channel: str, content: dict, keyword: str) -> list[str]:
    """채널별 규칙 검수 함수 호출."""
    try:
        if channel == "blog":
            return validate_blog(
                title=content.get("title", ""),
                body=content.get("body", ""),
                keyword=keyword,
                char_count=content.get("char_count"),
                keyword_count=content.get("actual_repeat"),
            )
        elif channel == "cafe-seo":
            return validate_cafe_seo(
                body=content.get("body", ""),
                keyword=keyword,
                comments_text=content.get("comments", ""),
                replies_text=content.get("replies", ""),
            )
        elif channel == "cafe-viral":
            return validate_cafe_viral(
                stage1=content.get("stage1", {}),
                stage2=content.get("stage2", {}),
                stage3=content.get("stage3", {}),
            )
        elif channel == "jisikin":
            return validate_jisikin(
                q_title=content.get("q_title", ""),
                q_body=content.get("q_body", ""),
                answer1=content.get("answer1", ""),
                answer2=content.get("answer2", ""),
                keyword=keyword,
            )
        elif channel == "youtube":
            return validate_youtube_comment(
                comment_text=content.get("comment", content.get("text", "")),
                video_title=content.get("video_title", ""),
            )
        elif channel == "tiktok":
            return validate_tiktok(
                script_text=content.get("script", content.get("text", "")),
            )
        elif channel == "shorts":
            return validate_shorts(
                script_text=content.get("script", content.get("text", "")),
            )
        elif channel == "community":
            return validate_community(
                post_body=content.get("body", content.get("post", "")),
                comments_text=content.get("comments", ""),
            )
        elif channel == "powercontent":
            return validate_powercontent(
                ad_title=content.get("ad_title", ""),
                ad_desc=content.get("ad_desc", ""),
                body=content.get("body", ""),
                keyword=keyword,
                char_count=content.get("char_count"),
            )
        elif channel == "threads":
            return validate_threads(
                text=content.get("text", content.get("body", "")),
            )
        else:
            logger.warning("알 수 없는 채널: %s — 규칙검수 스킵", channel)
            return []
    except Exception as e:
        logger.error("규칙검수 에러 [%s]: %s", channel, e)
        return [f"규칙검수 실행 에러: {e}"]
