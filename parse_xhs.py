from bs4 import BeautifulSoup

with open("xhs_source.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

imgs = soup.find_all("img")
valid = []
for img in imgs:
    src = img.get("src") or ""
    if "sns-webpic" in src or "ci.xiaohongshu.com" in src or "sns-avatar" not in src and src.startswith("http"):
        valid.append(src)

print(f"Total valid images found: {len(valid)}")
for i, v in enumerate(valid[:15]):
    print(f"{i}: {v}")

