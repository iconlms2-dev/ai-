from bs4 import BeautifulSoup
import re

with open("baidu_source.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
imgs = soup.find_all("img")
print(f"Total img tags: {len(imgs)}")

valid = []
for img in imgs:
    src = img.get("src") or img.get("data-src") or img.get("data-imgurl") or ""
    if "http" in src and "avatar" not in src:
        valid.append(src)

print(f"Valid srcs (first 10):")
for v in valid[:10]:
    print(v)

# Let's search for "hoverURL" or "thumbURL"
print("\nChecking for thumbURL/hoverURL JSON blocks:")
texts = re.findall(r'"thumbURL":"([^"]+)"', html)
print(f"thumbURL count: {len(texts)}")
if texts:
    print(f"First thumbURL: {texts[0]}")

texts2 = re.findall(r'"hoverURL":"([^"]+)"', html)    
print(f"hoverURL count: {len(texts2)}")
if texts2:
    print(f"First hoverURL: {texts2[0]}")

