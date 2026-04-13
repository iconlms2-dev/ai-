"""사진 수집 · 모자이크 · 라이브러리 관리"""
import os
import re
import json
import time
import shutil
import asyncio
import subprocess
from urllib.parse import quote

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from src.services.sse_helper import sse_dict, SSEResponse
from selenium.webdriver.common.by import By

from src.services.config import BASE_DIR, executor, GEMINI_API_KEY, selenium_semaphore
from src.services.selenium_pool import create_driver

router = APIRouter()

# ── 디렉토리 설정 ──

PHOTO_DIR = os.path.join(BASE_DIR, "photos")
PHOTO_LIB_FILE = os.path.join(BASE_DIR, "photo_library.json")
TEMP_PHOTO_DIR = os.path.join(BASE_DIR, "temp_photos")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(TEMP_PHOTO_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

XHS_PATH = os.environ.get('XHS_PATH', shutil.which('xhs') or '/Users/iconlms/Library/Python/3.11/bin/xhs')


# ── 헬퍼 함수 ──

def _translate_ko_to_zh(text):
    """한국어 → 중국어 번역 (Gemini Flash)"""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
        payload = {
            "contents": [{"parts": [{"text": "다음 한국어를 중국어(간체)로 번역해줘. 번역 결과만 출력하고 다른 설명은 하지 마.\n\n" + text}]}]
        }
        r = req.post(url, json=payload, timeout=10)
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return text


def _crawl_baidu_images(driver, query_zh, count):
    """바이두 이미지 검색 + 고해상도 이미지 URL 수집"""
    results = []
    try:
        url = f"https://image.baidu.com/search/index?tn=baiduimage&word={quote(query_zh)}"
        driver.get(url)
        time.sleep(3)

        # 스크롤해서 더 많은 이미지 로드
        scroll_count = max(1, count // 20)
        for _ in range(scroll_count):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)

        # 이미지 추출 (objURL이 보통 고해상도 원본)
        html = driver.page_source
        # objURL": "http://..." 형태 정규식
        urls = re.findall(r'"objURL":"(http://[^"]+|https://[^"]+)"', html)
        if not urls:
            # 보조 수단: 일반 img 태그의 src / data-src
            imgs = driver.find_elements(By.CSS_SELECTOR, "img")
            for img in imgs:
                u = img.get_attribute("data-imgurl") or img.get_attribute("data-src") or img.get_attribute("src")
                if u and u.startswith("http") and "avatar" not in u and "logo" not in u:
                    if u not in urls:
                        urls.append(u)

        for u in urls[:count]:
            if u.startswith("http"):
                results.append(u)
    except Exception as e:
        print(f"[baidu] error: {e}")
    return results


def _crawl_xhs_images(query_zh, count):
    """샤오홍슈 이미지 수집 (xiaohongshu-cli 사용)"""
    results = []
    try:
        result = subprocess.run(
            [XHS_PATH, "search", query_zh, "--sort", "popular", "--json"],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        items = data.get("data", {}).get("items", [])

        for item in items:
            if len(results) >= count:
                break
            nc = item.get("note_card", {})
            # 이미지 타입 게시물만 (영상 제외)
            if nc.get("type") == "video":
                continue
            for img in nc.get("image_list", []):
                if len(results) >= count:
                    break
                # WB_DFT = 고해상도
                url = ""
                for info in img.get("info_list", []):
                    if info.get("image_scene") == "WB_DFT":
                        url = info.get("url", "")
                        break
                if not url:
                    url = img.get("info_list", [{}])[0].get("url", "") if img.get("info_list") else ""
                if url and url.startswith("http"):
                    results.append(url)
    except Exception as e:
        print(f"[xhs-cli] search error: {e}")
    return results


def _download_image(url, filename, category):
    """이미지 다운로드 + 카테고리별 폴더 저장"""
    try:
        cat_dir = os.path.join(PHOTO_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://image.baidu.com/"
        }
        r = req.get(url, headers=headers, timeout=15, stream=True)
        if r.status_code == 200:
            filepath = os.path.join(cat_dir, filename)
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"[download] error {url}: {e}")
    return False


def _mosaic_faces(image_path):
    """OpenCV로 얼굴 감지 후 모자이크 처리"""
    import cv2
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        for (x, y, w, h) in faces:
            roi = img[y:y+h, x:x+w]
            small = cv2.resize(roi, (max(1, w//10), max(1, h//10)))
            mosaic = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
            img[y:y+h, x:x+w] = mosaic
        cv2.imwrite(image_path, img)
        return len(faces) > 0
    except Exception as e:
        print(f"[mosaic] error: {e}")
        return False


def _collect_xhs_for_cafe(target, count):
    """타겟층 기반으로 샤오홍슈 이미지 수집 + 모자이크"""
    # 타겟층 → 중국어 검색 키워드 변환
    zh_query = _translate_ko_to_zh(target + " 일상")
    print(f"[xhs-cafe] target='{target}' → query='{zh_query}'")

    urls = _crawl_xhs_images(zh_query, count + 3)
    if not urls:
        print("[xhs-cafe] no images found, trying simpler query")
        zh_query = _translate_ko_to_zh(target)
        urls = _crawl_xhs_images(zh_query, count + 3)

    downloaded = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"}
    for i, url in enumerate(urls):
        if len(downloaded) >= count:
            break
        try:
            r = req.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and len(r.content) > 2000:
                fname = f"xhs_cafe_{int(time.time()*1000)}_{i}.jpg"
                fpath = os.path.join(TEMP_PHOTO_DIR, fname)
                with open(fpath, 'wb') as f:
                    f.write(r.content)
                _mosaic_faces(fpath)
                downloaded.append(fpath)
        except Exception:
            pass
        time.sleep(2)  # 차단 방지
    return downloaded


# ── 엔드포인트 ──

@router.get("/translate")
async def photo_translate(text: str):
    loop = asyncio.get_running_loop()
    zh = await loop.run_in_executor(executor, _translate_ko_to_zh, text)
    return {"zh": zh}


@router.post("/crawl")
async def photo_crawl(request: Request):
    body = await request.json()
    query_zh = body.get("query_zh", "")
    count = body.get("count", 30)
    sources = body.get("sources", ["baidu"])
    category = body.get("category", "제품사진")

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield sse_dict({'type':'progress','msg':'브라우저 시작 중...','cur':0,'total':0})
        await selenium_semaphore.acquire()
        driver = None
        try:
            driver = await loop.run_in_executor(executor, create_driver)

            all_urls = []
            if "baidu" in sources:
                yield sse_dict({'type':'progress','msg':f'바이두 이미지 검색: {query_zh}','cur':0,'total':count})
                baidu_urls = await loop.run_in_executor(executor, _crawl_baidu_images, driver, query_zh, count)
                all_urls.extend([("baidu", u) for u in baidu_urls])

            if "xhs" in sources:
                yield sse_dict({'type':'progress','msg':f'샤오홍슈 검색: {query_zh}','cur':0,'total':count})
                xhs_urls = await loop.run_in_executor(executor, _crawl_xhs_images, query_zh, count)
                if not xhs_urls:
                    yield sse_dict({'type':'progress','msg':'⚠️ 샤오홍슈 수집 실패 (로그인/캡챠 차단 확인)','cur':0,'total':count})
                all_urls.extend([("xhs", u) for u in xhs_urls])
        finally:
            if driver:
                await loop.run_in_executor(executor, driver.quit)
            selenium_semaphore.release()

        # 이미지 다운로드
        total = min(len(all_urls), count)
        downloaded = 0
        for i, (src, url) in enumerate(all_urls[:count]):
            ts = int(time.time() * 1000)
            ext = "jpg"
            if ".png" in url.lower():
                ext = "png"
            elif ".webp" in url.lower():
                ext = "webp"
            filename = f"{src}_{ts}_{i}.{ext}"

            yield sse_dict({'type':'progress','msg':f'다운로드 중 ({i+1}/{total})','cur':i+1,'total':total})

            ok = await loop.run_in_executor(executor, _download_image, url, filename, category)
            if ok:
                downloaded += 1
                # 프론트엔드 호환성을 위해 filename은 상대경로처럼 전달
                rel_filename = f"{category}/{filename}"
                yield sse_dict({'type':'image','filename':rel_filename,'category':category})
            await asyncio.sleep(0.3)

        yield sse_dict({'type':'complete','total':downloaded})
      except Exception as e:
        print(f"[photo_crawl] 에러: {e}")
        yield sse_dict({'type':'error','message':f'이미지 수집 중 오류: {e}'})

    return SSEResponse(generate())


@router.get("/thumb/{filename:path}")
async def photo_thumb(filename: str):
    filepath = os.path.realpath(os.path.join(PHOTO_DIR, filename))
    if not filepath.startswith(os.path.realpath(PHOTO_DIR)):
        return Response(status_code=403)
    if not os.path.exists(filepath):
        return {"error": "not found"}
    return FileResponse(filepath, media_type="image/jpeg")


@router.get("/image/{filename:path}")
async def photo_image(filename: str):
    filepath = os.path.realpath(os.path.join(PHOTO_DIR, filename))
    if not filepath.startswith(os.path.realpath(PHOTO_DIR)):
        return Response(status_code=403)
    if not os.path.exists(filepath):
        return {"error": "not found"}
    return FileResponse(filepath)


@router.post("/mosaic")
async def photo_mosaic(request: Request):
    """간단한 모자이크 처리 (PIL 없이 — 파일명에 _mosaic 태그 추가)"""
    body = await request.json()
    filenames = body.get("filenames", [])
    processed = []
    for fn in filenames:
        filepath = os.path.join(PHOTO_DIR, fn)
        if os.path.exists(filepath):
            # PIL이 없으므로 파일 복사 + 이름에 _mosaic 추가
            name, ext = os.path.splitext(fn)
            new_fn = f"{name}_mosaic{ext}"
            new_path = os.path.join(PHOTO_DIR, new_fn)
            shutil.copy2(filepath, new_path)
            processed.append(new_fn)
    return {"processed": processed, "count": len(processed)}


@router.post("/delete")
async def photo_delete(request: Request):
    body = await request.json()
    filenames = body.get("filenames", [])
    deleted = 0
    for fn in filenames:
        filepath = os.path.join(PHOTO_DIR, fn)
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted += 1
    return {"deleted": deleted}


@router.post("/save-library")
async def photo_save_library(request: Request):
    from datetime import datetime
    body = await request.json()
    items = body.get("items", [])
    keyword = body.get("keyword", "")

    # 기존 라이브러리 로드
    lib = []
    if os.path.exists(PHOTO_LIB_FILE):
        with open(PHOTO_LIB_FILE, 'r', encoding='utf-8') as f:
            lib = json.load(f)

    # 새 항목 추가
    for item in items:
        lib.append({
            "filename": item["filename"],
            "category": item.get("category", "기타"),
            "keyword": keyword,
            "saved_at": datetime.now().isoformat()
        })

    with open(PHOTO_LIB_FILE, 'w', encoding='utf-8') as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)

    return {"saved": len(items), "total": len(lib)}


@router.get("/library")
async def photo_library():
    if not os.path.exists(PHOTO_LIB_FILE):
        return {"items": []}
    with open(PHOTO_LIB_FILE, 'r', encoding='utf-8') as f:
        lib = json.load(f)
    # 실제 파일 존재 여부 확인
    lib = [item for item in lib if os.path.exists(os.path.join(PHOTO_DIR, item["filename"]))]
    return {"items": lib}
