"""
서이추 후보 블로그 뽑기 (v2)
- '후기 말투'로 검색해서, 검색 상위에 노출되는 개인 후기형 네이버 블로그를 모은다.
- 정보·SEO형 제목이 대부분인 블로그, 이미 추천한 블로그, 내 블로그는 뺀다.
- 방문자 수·댓글 열림 여부는 API에 없어서 알 수 없다 → 후보를 직접 열어 확인해야 한다.
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

PER_CATEGORY = 3          # 카테고리마다 하루 검색할 키워드 수 (날마다 돌아가며 바뀜)
TOP_N = 50                # 검색어마다 관련도순 상위 몇 개를 볼지
TOP_RANK = 10             # 이 순위 안이면 '상위 노출'
ACTIVE_DAYS = 30          # 이 기간 안에 쓴 글이 있어야 '활동 중'
MAX_LIST = 12             # 하루 목록 최대 개수
OWN_NAME_HINT = "깡유니버스"          # 블로그 이름에 이게 들어 있으면 내 블로그
OWN_BLOG_IDS: set[str] = set()       # 내 블로그 아이디를 알면 여기에 (예: {"abcd1234"})

# 후보를 '개인 후기'쪽으로 끌어오는 검색어 꼬리표. 여기를 고치면 결과 성격이 바뀐다.
SKIP_CATS = {"다이어트 정보"}         # 정보형 글이 몰리는 카테고리는 후보 찾기에서 뺀다
QUERY_SUFFIX = {
    "다이어트 식단": "내돈내산 후기",
    "카페": "다녀왔어요",
    "맛집": "다녀왔어요",
    "제품 리뷰": "내돈내산 후기",
    "컨텐츠 리뷰": "후기",
}

# 정보·SEO형 제목 (자동 발행·정보 모음 블로그에 흔한 틀). 추정일 뿐이라 '대부분'일 때만 뺀다.
SEO = re.compile(r"완벽\s?정리|총정리|가이드|\d+\s?가지|진짜 이유|줄거리\s*/|결말|BEST|TOP\s?\d+|알아보|란\?|원리|기전|효능|부작용|비교\s?분석|한눈에|…")
# 직접 겪은 사람의 말투
VOICE = re.compile(r"다녀왔|다녀온|먹어봤|먹어 봤|써봤|써 봤|사봤|입어봤|해봤|내돈내산|솔직|ㅎㅎ|ㅋㅋ|했어요|였어요|이에요|더라구요|더라고요|같아요|좋았어요|맛있었")


def clean(t: str) -> str:
    return html.unescape(re.sub(r"</?b>", "", t or "")).strip()


def blog_id(link: str) -> str | None:
    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([^/?#]+)", link or "")
    return m.group(1) if m else None


def search_top(q: str) -> list[dict]:
    """관련도순 상위 TOP_N개"""
    r = requests.get(
        f"{BASE}/search/v1/blog",
        headers={"X-NCP-APIGW-API-KEY-ID": KEY_ID, "X-NCP-APIGW-API-KEY": KEY},
        params={"query": q, "display": TOP_N, "start": 1, "sort": "sim"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("items", [])


def demo_items(q: str) -> list[dict]:
    today = datetime.now(KST).strftime("%Y%m%d")

    def it(bid, name, title, desc, rank_pad=0):
        return {"title": title, "description": desc, "link": f"https://blog.naver.com/{bid}/{abs(hash(title)) % 10**6}",
                "bloggername": name, "bloggerlink": f"https://blog.naver.com/{bid}", "postdate": today}

    return [
        it("realA", "평범한 일상A", f"{q} 갔다 왔어요", "친구랑 다녀왔어요 ㅎㅎ 생각보다 맛있었어요"),
        it("seoB", "정보모음B", f"{q} 완벽 정리 5가지", "알아보겠습니다 원리와 효능"),
        it("realC", "후기러C", f"{q} 내돈내산", "솔직하게 써봤어요 같아요"),
        it("plainD", "그냥D", f"{q}", "오늘의 기록"),
        it("me", "깡유니버스의 깡", "내 글", "다녀왔어요"),
    ]


def pick_keywords(seeds: dict, today: date) -> list[tuple[str, str]]:
    """(카테고리, 검색어) — 카테고리마다 날짜 기준으로 돌려가며 PER_CATEGORY개"""
    out = []
    for cat, words in seeds["categories"].items():
        if not words or cat in SKIP_CATS:
            continue
        suffix = QUERY_SUFFIX.get(cat, "후기")
        start = (today.toordinal() * PER_CATEGORY) % len(words)
        for i in range(PER_CATEGORY):
            out.append((cat, f"{words[(start + i) % len(words)]} {suffix}"))
    return out


def main():
    demo = "--demo" in sys.argv
    if not demo and not (KEY_ID and KEY):
        sys.exit("NAVER_APIHUB_KEY_ID / NAVER_APIHUB_KEY 가 없어요. (Secrets 확인)")

    today = datetime.now(KST).date()
    cutoff = today - timedelta(days=ACTIVE_DAYS)
    seeds = json.loads((ROOT / "seeds.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)

    seen_path = OUT / "seen.json"
    seen: dict[str, str] = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}

    blogs: dict[str, dict] = {}
    failed = 0
    queries = pick_keywords(seeds, today)
    for cat, q in queries:
        try:
            items = demo_items(q) if demo else search_top(q)
        except Exception as e:
            failed += 1
            print(f"[검색 실패] {q}: {e}", file=sys.stderr)
            continue
        for rank, it in enumerate(items):
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
            title, desc = clean(it.get("title", "")), clean(it.get("description", ""))
            text = f"{title} {desc}"
            # 검색어로 쓴 꼬리표 단어는 글이 원래 갖고 있던 말투가 아니므로 빼고 판정한다
            for tok in QUERY_SUFFIX.get(cat, "후기").split():
                text = text.replace(tok, "")
            b = blogs.setdefault(bid, {"id": bid, "name": name or bid, "url": f"https://blog.naver.com/{bid}",
                                       "cats": set(), "posts": {}, "top_queries": set()})
            b["cats"].add(cat)
            if rank < TOP_RANK:
                b["top_queries"].add(q)
            b["posts"][it.get("link", "")] = {
                "title": title, "date": d.isoformat(), "url": it.get("link", ""),
                "voice": bool(VOICE.search(text)), "seo": bool(SEO.search(title)),
            }
        time.sleep(0.15)

    if failed == len(queries):
        sys.exit("검색이 전부 실패했어요. 키·API 권한을 확인해 주세요.")

    fresh, dropped_seo, dropped_nov = [], 0, 0
    for bid, b in blogs.items():
        if bid in seen:
            continue
        posts = list(b["posts"].values())
        voice = sum(p["voice"] for p in posts)
        seo = sum(p["seo"] for p in posts)
        if seo >= max(1, (len(posts) + 1) // 2):   # 정보·SEO형 제목이 절반 이상
            dropped_seo += 1
            continue
        if voice < 1:                              # 후기 말투 글이 하나도 없음
            dropped_nov += 1
            continue
        b["voice"] = voice
        b["score"] = voice * 2 + len(b["top_queries"]) * 2 + len(b["cats"])
        fresh.append(b)
    fresh.sort(key=lambda b: (-b["score"], b["name"]))
    picked = fresh[:MAX_LIST]

    rows = []
    for b in picked:
        posts = sorted(b["posts"].values(), key=lambda p: p["date"], reverse=True)
        why = f"검색 상위({TOP_RANK}위 안) {len(b['top_queries'])}회 · 후기 말투 글 {b['voice']}개 · 최근 글 {posts[0]['date'][5:]}"
        rows.append({
            "id": b["id"], "name": b["name"], "url": b["url"],
            "cats": sorted(b["cats"]), "recent_posts": len(posts), "why": why,
            "latest": [{k: p[k] for k in ("title", "date", "url")} for p in posts[:2]],
        })
        seen[b["id"]] = today.isoformat()

    # 오래된 기록(120일 넘은 것)은 정리해서 다시 나올 수 있게 한다
    keep_after = (today - timedelta(days=120)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= keep_after}

    payload = {
        "date": today.isoformat(),
        "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "criteria": f"최근 {ACTIVE_DAYS}일 안에 후기 말투 글이 검색 상위에 노출된 블로그 · 정보형 제목 위주·이미 추천한 곳 제외",
        "note": "방문자 수·댓글 열림 여부는 알 수 없어요. 열어서 직접 확인해 주세요.",
        "queried": [f"{c}: {q}" for c, q in queries],
        "failedQueries": failed,
        "pool": len(blogs),
        "items": rows,
    }

    lines = [f"# 서이추 후보 {today.isoformat()} ({len(rows)}곳)", ""]
    if not rows:
        lines.append("오늘은 새로 추천할 블로그가 없었어요. (이미 추천한 블로그는 제외돼요)")
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. **{r['name']}** — {', '.join(r['cats'])}")
        lines.append(f"   - {r['why']}")
        lines.append(f"   - 블로그: {r['url']}")
        for p in r["latest"]:
            lines.append(f"   - 최근 글({p['date'][5:]}): [{p['title']}]({p['url']})")
    lines += ["", "방문자 수와 댓글 열림 여부는 API로 알 수 없어서, 신청 전에 블로그를 열어 직접 확인해 주세요.",
              f"_검색어 {len(queries)}개 중 실패 {failed}개 · 후보 풀 {len(blogs)}곳 · 정보형 제외 {dropped_seo}곳 · 후기 말투 없음 {dropped_nov}곳_"]
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
