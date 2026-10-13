"""
서이추 후보 블로그 뽑기
- seeds.json의 카테고리 키워드로 네이버 블로그 최신 글을 검색해서, 최근 7일 안에 글을 쓴 블로그를 모은다.
- 이미 추천한 블로그(neighbors/seen.json)와 내 블로그는 뺀다.
- 결과: neighbors/YYYY-MM-DD.md, neighbors/latest.json (neighbors.html이 읽음), .last_neighbors (Actions가 이슈로 올림)

실행: python neighbors.py
      python neighbors.py --demo   (API 없이 가짜 데이터로 형식만 확인)
"""
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).parent
OUT = ROOT / "neighbors"
BASE = "https://naverapihub.apigw.ntruss.com"
KEY_ID = os.environ.get("NAVER_APIHUB_KEY_ID", "")
KEY = os.environ.get("NAVER_APIHUB_KEY", "")

PER_CATEGORY = 3        # 카테고리마다 하루 검색할 키워드 수 (날마다 돌아가며 바뀜)
RECENT_DAYS = 7         # 이 기간 안에 글이 있어야 '활동 중'
MAX_LIST = 15           # 하루 목록 최대 개수
OWN_NAME_HINT = "깡유니버스"          # 블로그 이름에 이게 들어 있으면 내 블로그
OWN_BLOG_IDS: set[str] = set()       # 내 블로그 아이디를 알면 여기에 (예: {"abcd1234"})


def clean(t: str) -> str:
    return html.unescape(re.sub(r"</?b>", "", t or "")).strip()


def blog_id(link: str) -> str | None:
    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([^/?#]+)", link or "")
    return m.group(1) if m else None


def search_recent(q: str) -> list[dict]:
    r = requests.get(
        f"{BASE}/search/v1/blog",
        headers={"X-NCP-APIGW-API-KEY-ID": KEY_ID, "X-NCP-APIGW-API-KEY": KEY},
        params={"query": q, "display": 100, "start": 1, "sort": "date"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def demo_items(q: str) -> list[dict]:
    today = datetime.now(KST).strftime("%Y%m%d")
    return [
        {"title": f"<b>{q}</b> 후기 {i}", "link": f"https://blog.naver.com/demo{i % 4}/{1000 + i}",
         "bloggername": f"데모블로그{i % 4}", "bloggerlink": f"https://blog.naver.com/demo{i % 4}",
         "postdate": today}
        for i in range(6)
    ] + [{"title": "내 글", "link": "https://blog.naver.com/me/1", "bloggername": "깡유니버스의 깡",
          "bloggerlink": "https://blog.naver.com/me", "postdate": today}]


def pick_keywords(seeds: dict, today: date) -> list[tuple[str, str]]:
    """(카테고리, 키워드) — 카테고리마다 날짜 기준으로 돌려가며 PER_CATEGORY개"""
    out = []
    for cat, words in seeds["categories"].items():
        if not words:
            continue
        start = (today.toordinal() * PER_CATEGORY) % len(words)
        for i in range(PER_CATEGORY):
            out.append((cat, words[(start + i) % len(words)]))
    return out


def main():
    demo = "--demo" in sys.argv
    if not demo and not (KEY_ID and KEY):
        sys.exit("NAVER_APIHUB_KEY_ID / NAVER_APIHUB_KEY 가 없어요. (Secrets 확인)")

    today = datetime.now(KST).date()
    cutoff = today - timedelta(days=RECENT_DAYS)
    seeds = json.loads((ROOT / "seeds.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)

    seen_path = OUT / "seen.json"
    seen: dict[str, str] = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}

    blogs: dict[str, dict] = {}
    failed = 0
    queries = pick_keywords(seeds, today)
    for cat, kw in queries:
        try:
            items = demo_items(kw) if demo else search_recent(kw)
        except Exception as e:
            failed += 1
            print(f"[검색 실패] {kw}: {e}", file=sys.stderr)
            continue
        for it in items:
            bid = blog_id(it.get("bloggerlink", "")) or blog_id(it.get("link", ""))
            if not bid:  # 티스토리 등 네이버 블로그가 아닌 곳은 서이추 대상이 아님
                continue
            name = clean(it.get("bloggername", ""))
            if bid in OWN_BLOG_IDS or OWN_NAME_HINT in name:
                continue
            try:
                d = datetime.strptime(it.get("postdate", ""), "%Y%m%d").date()
            except ValueError:
                continue
            if d < cutoff:
                continue
            b = blogs.setdefault(bid, {"id": bid, "name": name or bid, "url": f"https://blog.naver.com/{bid}",
                                       "cats": set(), "posts": {}})
            b["cats"].add(cat)
            b["posts"][it.get("link", "")] = {"title": clean(it.get("title", "")), "date": d.isoformat(),
                                              "url": it.get("link", "")}
        time.sleep(0.15)

    if failed == len(queries):
        sys.exit("검색이 전부 실패했어요. 키·API 권한을 확인해 주세요.")

    fresh = [b for bid, b in blogs.items() if bid not in seen]
    for b in fresh:
        b["score"] = len(b["posts"]) * 2 + len(b["cats"])
    fresh.sort(key=lambda b: (-b["score"], b["name"]))
    picked = fresh[:MAX_LIST]

    rows = []
    for b in picked:
        posts = sorted(b["posts"].values(), key=lambda p: p["date"], reverse=True)
        rows.append({
            "id": b["id"], "name": b["name"], "url": b["url"],
            "cats": sorted(b["cats"]), "recent_posts": len(posts),
            "latest": posts[:2],
        })
        seen[b["id"]] = today.isoformat()

    # 오래된 기록(120일 넘은 것)은 정리해서 다시 나올 수 있게 한다
    keep_after = (today - timedelta(days=120)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= keep_after}

    payload = {
        "date": today.isoformat(),
        "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "criteria": f"최근 {RECENT_DAYS}일 안에 글이 검색된 네이버 블로그 · 이미 추천한 블로그 제외",
        "queried": [f"{c}: {k}" for c, k in queries],
        "failedQueries": failed,
        "pool": len(blogs),
        "items": rows,
    }

    lines = [f"# 서이추 후보 {today.isoformat()} ({len(rows)}곳)", ""]
    if not rows:
        lines.append("오늘은 새로 추천할 블로그가 없었어요. (이미 추천한 블로그는 제외돼요)")
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. **{r['name']}** — {', '.join(r['cats'])} · 최근 {RECENT_DAYS}일 글 {r['recent_posts']}개")
        lines.append(f"   - 블로그: {r['url']}")
        for p in r["latest"]:
            lines.append(f"   - 최근 글({p['date'][5:]}): [{p['title']}]({p['url']})")
    lines += ["", f"_검색한 키워드 {len(queries)}개 중 실패 {failed}개 · 후보 풀 {len(blogs)}곳_"]
    md = "\n".join(lines) + "\n"

    if demo:
        print(md)
        return

    (OUT / f"{today.isoformat()}.md").write_text(md, encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    seen_path.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / ".last_neighbors").write_text(str((OUT / f"{today.isoformat()}.md").relative_to(ROOT)), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
