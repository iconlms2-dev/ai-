from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--disable-blink-features=AutomationControlled')
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option('useAutomationExtension', False)
opts.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

svc = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=svc, options=opts)

driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

url = "https://www.xiaohongshu.com/search_result/?keyword=饮食&type=54"
driver.get(url)
time.sleep(5)

html = driver.page_source
with open("xhs_source2.html", "w", encoding="utf-8") as f:
    f.write(html)

driver.quit()

from bs4 import BeautifulSoup
with open("xhs_source2.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

imgs = soup.find_all("img")
valid = [img.get("src") for img in imgs if img.get("src") and str(img.get("src")).startswith("http")]
print(f"Bypass valid images: {len(valid)}")

