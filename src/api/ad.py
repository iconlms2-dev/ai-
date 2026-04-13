"""광고 소재(메타/틱톡 DA) API 라우터"""
import asyncio
import json
import os
import re
import time

import requests as req
from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from src.services.sse_helper import sse_dict, SSEResponse
from PIL import Image, ImageDraw, ImageFont
from selenium.webdriver.common.by import By
from urllib.parse import quote

from src.services.config import executor, BASE_DIR, CONTENT_DB_ID, NOTION_TOKEN, selenium_semaphore
from src.services.common import error_response
from src.services.ai_client import call_claude
from src.services.notion_client import notion_headers
from src.services.selenium_pool import create_driver

router = APIRouter()

AD_REFS_DIR = os.path.join(BASE_DIR, "ad_refs")
AD_OUTPUTS_DIR = os.path.join(BASE_DIR, "ad_outputs")
os.makedirs(AD_REFS_DIR, exist_ok=True)
os.makedirs(AD_OUTPUTS_DIR, exist_ok=True)


# ═══════════════════════════ HELPERS ═══════════════════════════

def _crawl_meta_ads(keyword, country="KR", count=30, advertiser=""):
    """메타 광고 라이브러리 크롤링 (Selenium) -- 개선된 버전"""
    results = []
    driver = create_driver()
    try:
        q = advertiser if advertiser else keyword
        url = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=%s&media_type=image&q=%s" % (country, quote(q))
        driver.get(url)
        time.sleep(8)  # 초기 로딩 대기

        # 쿠키/로그인 팝업 닫기
        try:
            for label in ['닫기', 'Close', 'Decline optional cookies', '선택 쿠키 거부']:
                btns = driver.find_elements(By.XPATH, "//button[contains(text(), '%s') or @aria-label='%s']" % (label, label))
                for b in btns:
                    try: b.click(); time.sleep(1)
                    except Exception: pass
        except Exception:
            pass

        # 충분히 스크롤해서 광고 로드
        last_height = 0
        for scroll_i in range(max(8, count // 3)):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height and scroll_i > 3:
                break
            last_height = new_height

        # ── 전략: "게재 시작" 또는 "Started running" 텍스트를 기준으로 광고 카드 찾기 ──
        # 이 텍스트는 모든 광고 카드에 반드시 존재
        date_markers = driver.find_elements(By.XPATH,
            "//span[contains(text(),'Started running') or contains(text(),'게재 시작') or contains(text(),'시작일')]")

        print("[meta-ads] Found %d date markers" % len(date_markers))

        seen_texts = set()
        for marker in date_markers:
            if len(results) >= count:
                break
            try:
                # 날짜 마커에서 상위로 올라가면서 광고 카드 컨테이너 찾기
                container = marker
                for _ in range(15):
                    container = container.find_element(By.XPATH, "..")
                    # 광고 카드는 보통 높이가 200px 이상이고, 이미지를 포함
                    try:
                        h = container.size.get('height', 0)
                        w = container.size.get('width', 0)
                    except Exception:
                        h = w = 0
                    if h > 200 and w > 300:
                        imgs = container.find_elements(By.TAG_NAME, "img")
                        if len(imgs) >= 1:
                            break

                # 중복 체크
                card_text = container.text[:200]
                if card_text in seen_texts or len(card_text) < 20:
                    continue
                seen_texts.add(card_text)

                ad = {'headline': '', 'body': '', 'cta': '', 'advertiser': '', 'period': '', 'image_url': '', 'image_file': ''}

                # ── 이미지 추출 ──
                imgs = container.find_elements(By.TAG_NAME, "img")
                for img in imgs:
                    src = img.get_attribute("src") or ""
                    # 광고 이미지는 scontent/fbcdn URL + 실제 크기가 큰 것
                    try:
                        nw = driver.execute_script("return arguments[0].naturalWidth || 0", img)
                    except Exception:
                        nw = 0
                    if src and ("scontent" in src or "fbcdn" in src) and nw > 80:
                        ad['image_url'] = src
                        break

                # ── 텍스트 추출 (줄 단위로 파싱) ──
                full_text = container.text
                lines = [l.strip() for l in full_text.split('\n') if l.strip() and len(l.strip()) > 2]
                # 페이지 UI 텍스트 제거
                skip_words = ['광고 라이브러리', 'Ad Library', 'API', '브랜디드 콘텐츠', 'See summary', '요약 보기',
                              'About this ad', '이 광고 정보', 'See ad details', '광고 세부정보', '모든 광고']
                lines = [l for l in lines if not any(sw in l for sw in skip_words)]

                if lines:
                    ad['advertiser'] = lines[0]

                # 게재 기간
                for l in lines:
                    if '시작' in l or 'Started' in l or 'running' in l:
                        ad['period'] = l
                        break

                # 본문 = 가장 긴 텍스트 (광고주, 기간 제외)
                content_lines = [l for l in lines if l != ad['advertiser'] and l != ad['period'] and len(l) > 5]
                if content_lines:
                    content_lines.sort(key=len, reverse=True)
                    ad['body'] = content_lines[0]
                    # 헤드라인 = 두번째로 긴 텍스트 또는 짧은 텍스트
                    headlines = [l for l in content_lines if l != ad['body'] and 5 < len(l) < 80]
                    if headlines:
                        ad['headline'] = headlines[0]

                # CTA
                cta_btns = container.find_elements(By.CSS_SELECTOR, "a[role='button'], div[role='button']")
                for btn in cta_btns:
                    bt = btn.text.strip()
                    if bt and 2 < len(bt) < 25 and bt not in ('더 보기', 'See more', '좋아요', 'Like'):
                        ad['cta'] = bt
                        break

                if ad['body'] or ad['headline']:
                    # 이미지 다운로드
                    if ad['image_url']:
                        fname = "ad_%d_%d.jpg" % (int(time.time()*1000), len(results))
                        fpath = os.path.join(AD_REFS_DIR, fname)
                        try:
                            r = req.get(ad['image_url'], timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                            if r.status_code == 200 and len(r.content) > 2000:
                                with open(fpath, 'wb') as f:
                                    f.write(r.content)
                                ad['image_file'] = fname
                        except Exception:
                            pass
                    results.append(ad)
            except Exception as e2:
                print("[meta-ads] card parse error: %s" % e2)
                continue

        # ── 폴백: date_markers가 없으면 일반적인 방식 시도 ──
        if not results:
            print("[meta-ads] Fallback: trying generic approach")
            # 페이지 소스에서 이미지 URL 직접 추출
            page_src = driver.page_source
            img_urls = re.findall(r'https://scontent[^"\']+', page_src)
            img_urls = list(dict.fromkeys(img_urls))[:count]  # 중복 제거
            for img_url in img_urls:
                if 'emoji' in img_url or 'avatar' in img_url or len(img_url) > 500:
                    continue
                ad = {'headline': keyword, 'body': '', 'cta': '', 'advertiser': '', 'period': '', 'image_url': img_url, 'image_file': ''}
                fname = "ad_%d_%d.jpg" % (int(time.time()*1000), len(results))
                fpath = os.path.join(AD_REFS_DIR, fname)
                try:
                    r = req.get(img_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                    if r.status_code == 200 and len(r.content) > 5000:
                        with open(fpath, 'wb') as f:
                            f.write(r.content)
                        ad['image_file'] = fname
                        results.append(ad)
                except Exception:
                    pass
                if len(results) >= count:
                    break

    except Exception as e:
        print("[meta-ads] crawl error: %s" % e)
    finally:
        driver.quit()
    return results


def _analyze_ad_refs(refs):
    """레퍼런스 패턴 분석 (AI)"""
    ref_text = ""
    for i, r in enumerate(refs):
        ref_text += "[%d] 헤드라인: %s | 본문: %s | CTA: %s\n" % (i+1, r.get('headline',''), r.get('body','')[:100], r.get('cta',''))

    system = "당신은 광고 소재 분석 전문가입니다."
    user = """아래 수집된 광고 레퍼런스 %d개를 분석해주세요.

%s

분석 항목:
1. 가장 많이 쓰이는 소구점 Top 3
2. 후킹 방식 분류 (공포/호기심/공감/결과제시/긴급성)
3. CTA 패턴 분포
4. 평균 헤드라인 길이
5. 자주 쓰이는 표현/키워드
6. 추천 광고 전략 요약

JSON으로 응답해.""" % (len(refs), ref_text)

    return call_claude(system, user)


def _generate_ad_creatives(product, appeal, refs_analysis, ref_examples, platform, ad_type, count, forbidden):
    """광고 소재 생성 (AI)"""
    system = "당신은 메타/틱톡 DA 광고 소재를 기획하는 퍼포먼스 마케터입니다."
    user = """아래 정보를 기반으로 클릭률 높은 광고 소재를 %d개 기획해주세요.

## 광고 플랫폼: %s
## 광고 유형: %s

## 제품 정보
- 제품명: %s
- 주요 성분: %s
- 핵심 특징(USP): %s
- 타겟층: %s
- 나만의 키워드: %s

## 소구점: %s

## 레퍼런스 분석 결과
%s

## 별점 높은 레퍼런스 예시
%s

%s

## 출력 형식 (JSON 배열)
각 소재를 아래 형식으로:
[
  {
    "headline": "헤드라인 (15자 이내)",
    "body": "본문 텍스트 (100자 이내)",
    "cta": "CTA 버튼 텍스트",
    "overlay_text": "이미지 위 텍스트 오버레이 (2줄)",
    "ref_index": 참고한 레퍼런스 번호
  }
]""" % (
        count, platform, ad_type,
        product.get('name',''), product.get('ingredients',''), product.get('usp',''),
        product.get('target',''), product.get('brand_keyword',''),
        appeal, refs_analysis, ref_examples,
        ("## 광고 금지 문구\n다음 표현 사용 금지: " + forbidden) if forbidden else ""
    )

    return call_claude(system, user)


def _create_ad_image(bg_path, overlay_text, output_path):
    """배경 이미지에 광고 텍스트 오버레이"""
    try:
        img = Image.open(bg_path).convert("RGBA")
        img = img.resize((1080, 1080), Image.LANCZOS)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 56)
        except Exception:
            font = ImageFont.load_default()

        lines = overlay_text.split('\n')
        y_pos = img.height - 200
        draw.rectangle([0, y_pos - 30, img.width, img.height], fill=(0, 0, 0, 160))

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (img.width - tw) // 2
            draw.text((x, y_pos), line, fill="white", font=font)
            y_pos += 80

        result = Image.alpha_composite(img, overlay).convert("RGB")
        result.save(output_path, quality=95)
        return True
    except Exception as e:
        print("[ad-image] error: %s" % e)
        return False


# ═══════════════════════════ ENDPOINTS ═══════════════════════════

@router.post("/crawl-refs")
async def ad_crawl_refs(request: Request):
    """메타 광고 라이브러리에서 레퍼런스 수집 (SSE)"""
    body = await request.json()
    keyword = body.get('keyword', '')
    country = body.get('country', 'KR')
    count = body.get('count', 30)
    advertiser = body.get('advertiser', '')

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({'type': 'progress', 'msg': '메타 광고 라이브러리 크롤링 중...'})
        await selenium_semaphore.acquire()
        try:
            refs = await loop.run_in_executor(executor, _crawl_meta_ads, keyword, country, count, advertiser)
        finally:
            selenium_semaphore.release()
        yield _sse({'type': 'complete', 'refs': refs, 'total': len(refs)})
      except Exception as e:
        print(f"[ad_crawl_refs] 에러: {e}")
        yield _sse({'type': 'error', 'message': f'광고 레퍼런스 수집 중 오류: {e}'})

    return SSEResponse(generate())


@router.get("/ref-image/{filename}")
async def ad_ref_image(filename: str):
    safe_name = os.path.basename(filename)
    fpath = os.path.join(AD_REFS_DIR, safe_name)
    if os.path.exists(fpath):
        return FileResponse(fpath, media_type="image/jpeg")
    return Response(status_code=404)


@router.post("/analyze")
async def ad_analyze(request: Request):
    """레퍼런스 패턴 분석"""
    body = await request.json()
    refs = body.get('refs', [])
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _analyze_ad_refs, refs)
    return {'analysis': result}


@router.post("/generate")
async def ad_generate(request: Request):
    """광고 소재 생성"""
    body = await request.json()
    product = body.get('product', {})
    appeal = body.get('appeal', '')
    analysis = body.get('analysis', '')
    ref_examples = body.get('ref_examples', '')
    platform = body.get('platform', '메타')
    ad_type = body.get('ad_type', '이미지')
    count = body.get('count', 5)
    forbidden = body.get('forbidden', '')
    ref_images = body.get('ref_images', {})  # {index: filename}

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(executor, _generate_ad_creatives,
        product, appeal, analysis, ref_examples, platform, ad_type, count, forbidden)

    # JSON 파싱
    creatives = []
    try:
        m = re.search(r'\[[\s\S]*\]', raw)
        if m:
            creatives = json.loads(m.group())
    except Exception:
        creatives = [{'headline': raw[:50], 'body': raw, 'cta': '자세히 보기', 'overlay_text': '', 'ref_index': 0}]

    # 각 소재에 이미지 합성
    for i, cr in enumerate(creatives):
        cr['image_file'] = ''
        overlay = cr.get('overlay_text', '')
        ref_idx = cr.get('ref_index', 0)
        bg_file = ref_images.get(str(ref_idx), '') or ref_images.get(str(ref_idx - 1), '')
        if bg_file and overlay:
            bg_path = os.path.join(AD_REFS_DIR, bg_file)
            if os.path.exists(bg_path):
                out_fname = "creative_%s_%d.jpg" % (int(time.time()*1000), i)
                out_path = os.path.join(AD_OUTPUTS_DIR, out_fname)
                ok = await loop.run_in_executor(executor, _create_ad_image, bg_path, overlay, out_path)
                if ok:
                    cr['image_file'] = out_fname

    return {'creatives': creatives}


@router.get("/output-image/{filename}")
async def ad_output_image(filename: str):
    safe_name = os.path.basename(filename)
    fpath = os.path.join(AD_OUTPUTS_DIR, safe_name)
    if os.path.exists(fpath):
        return FileResponse(fpath, media_type="image/jpeg")
    return Response(status_code=404)


@router.post("/save-notion")
async def ad_save_notion(request: Request):
    body = await request.json()
    headers = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    props = {
        '제목': {'title': [{'text': {'content': body.get('headline', '')}}]},
        '채널': {'select': {'name': '메타광고'}},
        '생산 상태': {'select': {'name': '초안'}},
        '발행_상태': {'select': {'name': '미발행'}},
    }
    summary = body.get('body', '') + ' | CTA: ' + body.get('cta', '')
    props['본문'] = {'rich_text': [{'text': {'content': summary[:2000]}}]}
    payload = {'parent': {'database_id': CONTENT_DB_ID}, 'properties': props}
    try:
        from src.services.notion_client import create_page
        result = create_page(CONTENT_DB_ID, props)
        return {'success': result['success'], 'error': result.get('error', '')}
    except Exception as e:
        return {'success': False, 'error': str(e)}


@router.post("/upload-product-image")
async def ad_upload_product_image(file: UploadFile = File(...)):
    """제품 이미지 업로드"""
    allowed_ext = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in allowed_ext:
        return JSONResponse({'error': f'허용되지 않는 파일 형식: {ext}'}, status_code=400)
    fname = "product_%s_%s" % (int(time.time()*1000), file.filename)
    fpath = os.path.join(AD_REFS_DIR, fname)
    with open(fpath, 'wb') as f:
        content = await file.read()
        f.write(content)
    return {'filename': fname}
