from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
from urllib.parse import quote
import re
from selenium.webdriver.common.by import By

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--window-size=1920,1080')
opts.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
svc = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=svc, options=opts)

query_zh = "饮食"
count = 30
results = []
try:
    url = f"https://image.baidu.com/search/index?tn=baiduimage&word={quote(query_zh)}"
    print(f"URL: {url}")
    driver.get(url)
    time.sleep(3)

    # 스크롤해서 더 많은 이미지 로드
    scroll_count = max(1, count // 20)
    for _ in range(scroll_count):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)

    html = driver.page_source
    with open("baidu_source.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    urls = re.findall(r'"objURL":"(http://[^"]+|https://[^"]+)"', html)
    print(f"objURL count: {len(urls)}")
    if not urls:
        imgs = driver.find_elements(By.CSS_SELECTOR, "img.main_img")
        urls = [img.get_attribute("data-imgurl") for img in imgs if img.get_attribute("data-imgurl")]
        print(f"data-imgurl count: {len(urls)}")

    for u in urls[:count]:
        if u.startswith("http"):
            results.append(u)
except Exception as e:
    print(f"[baidu] error: {e}")
driver.quit()
print(f"Found: {len(results)}")
print(results[:5])
