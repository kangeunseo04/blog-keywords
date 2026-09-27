"""
요즘 뜨는 것 찾기
- 네이버 블로그·뉴스 검색(최신순)으로 최근 7일 새 글 제목을 모아
  갑자기 자주 등장하는 브랜드·메뉴·제품 이름을 뽑고, 데이터랩으로 검색이 실제로 붙는지 확인한다.
- 인스타·숏츠에서 유행하는 건 며칠 안에 블로그 제목에 그대로 찍히므로 그걸 역추적하는 방식.
"""
import html
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

BASE = "https://naverapihub.apigw.ntruss.com"

# 제목에 늘 나오는 뻔한 말 — 후보에서 제외
STOP = set("""
후기 리뷰 추천 솔직 솔직후기 내돈내산 방문 방문후기 재방문 존맛 존맛탱 맛집 카페 신메뉴 메뉴 가격 칼로리 정리 총정리 비교
오늘 어제 내일 주말 평일 요즘 최근 인생 최고 최애 대박 강추 비추 꿀팁 팁 정보 공유 일상 데일리 브이로그 먹방 기록
다이어트 식단 운동 성공 실패 시작 도전 후 전 중 개월 주차 일차 kg 키로 감량 유지 체중 몸무게
출시 한정 한정판 신상 신제품 출시일 판매 구매 구매처 가격대 할인 세일 이벤트 증정 무료 쿠폰
넷플릭스 디즈니플러스 티빙 쿠팡플레이 웨이브 드라마 영화 예능 시즌 회차 결말 스포 줄거리 리뷰 감상 관람 개봉
서울 경기 인천 부산 대구 대전 광주 울산 강남 홍대 성수 연남 잠실 판교 분당 수원 용인 일산 근처 동네 우리
사진 영상 인스타 인스타그램 유튜브 숏츠 틱톡 블로그 포스팅 이웃 댓글 공감 구독 좋아요
그리고 그래서 하지만 진짜 정말 완전 너무 엄청 살짝 조금 약간 그냥 역시 드디어 결국 다시 또 계속 아직 이제
하는 하기 하고 했다 했어요 해요 합니다 있는 없는 있어요 없어요 되는 되기 먹는 먹기 먹고 먹은 마시는 가는 가기 갔다 가서 가면
이번 지난 다음 이달 매일 매주 매달 하루 이틀 한달 일주일 첫 두번째 세번째 신규 오픈 재오픈 리뉴얼
""".split())

TOKEN_SPLIT = re.compile(r"[\s\[\]()（）/,!?~·|:;\"'“”‘’…\-–—+=*#&%<>{}]+")
HANGUL_OR_ALPHA = re.compile(r"[가-힣A-Za-z]")
VERB_END = re.compile(r"(어요|아요|해요|했어요|습니다|합니다|했다|하다|이다|네요|더라|더라구요|는데|던데|나요|까요|세요|봤어요|봐요|줘요|져요|되요|돼요|었다|았다|한다|된다|하기|되기)$")


def clean_title(t: str) -> str:
    t = re.sub(r"</?b>", "", t)
    t = html.unescape(t)
    return t.strip()


def _headers(key_id, key):
    return {"X-NCP-APIGW-API-KEY-ID": key_id, "X-NCP-APIGW-API-KEY": key}


def search_blog(q: str, key_id: str, key: str, pages: int = 3) -> list[dict]:
    """최신순 블로그 글. 페이지당 100개."""
    out = []
    for p in range(pages):
        try:
            r = requests.get(f"{BASE}/search/v1/blog", headers=_headers(key_id, key),
                             params={"query": q, "display": 100, "start": 1 + p * 100, "sort": "date"}, timeout=15)
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception as e:
            print(f"[blog 검색 실패] {q} p{p}: {e}", file=sys.stderr)
            break
        for it in items:
            try:
                d = datetime.strptime(it.get("postdate", ""), "%Y%m%d").date()
            except ValueError:
                continue
            out.append({"title": clean_title(it.get("title", "")), "date": d, "src": "blog", "q": q,
                        "link": it.get("link", "")})
        if len(items) < 100:
            break
        time.sleep(0.15)
    return out


def search_news(q: str, key_id: str, key: str) -> list[dict]:
    out = []
    try:
        r = requests.get(f"{BASE}/search/v1/news", headers=_headers(key_id, key),
                         params={"query": q, "display": 100, "sort": "date"}, timeout=15)
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as e:
        print(f"[news 검색 실패] {q}: {e}", file=sys.stderr)
        return out
    for it in items:
        try:
            d = parsedate_to_datetime(it.get("pubDate", "")).date()
        except Exception:
            continue
        out.append({"title": clean_title(it.get("title", "")), "date": d, "src": "news", "q": q,
                    "link": it.get("originallink") or it.get("link", "")})
    return out


def search_youtube(q: str, api_key: str, today: date) -> list[dict]:
    """최근 7일 올라온 영상 중 조회수 순 50개. search.list 100유닛 + videos.list 1유닛 (하루 무료 10,000유닛)."""
    if not api_key:
        return []
    out = []
    try:
        since = (today - timedelta(days=7)).isoformat() + "T00:00:00Z"
        r = requests.get("https://www.googleapis.com/youtube/v3/search", params={
            "key": api_key, "part": "snippet", "q": q, "type": "video", "order": "viewCount",
            "publishedAfter": since, "regionCode": "KR", "relevanceLanguage": "ko", "maxResults": 50}, timeout=20)
        r.raise_for_status()
        items = r.json().get("items", [])
        ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
        views = {}
        if ids:
            r2 = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
                "key": api_key, "part": "statistics", "id": ",".join(ids)}, timeout=20)
            r2.raise_for_status()
            views = {v["id"]: int(v.get("statistics", {}).get("viewCount", 0)) for v in r2.json().get("items", [])}
        for it in items:
            vid = it.get("id", {}).get("videoId")
            sn = it.get("snippet", {})
            try:
                d = datetime.strptime(sn.get("publishedAt", "")[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            out.append({"title": clean_title(sn.get("title", "")), "date": d, "src": "youtube", "q": q,
                        "link": f"https://youtu.be/{vid}", "views": views.get(vid, 0)})
    except Exception as e:
        print(f"[youtube 검색 실패] {q}: {e}", file=sys.stderr)
    return out


class Tokenizer:
    """kiwipiepy가 있으면 명사 판별에 쓰고, 없으면 단순 규칙."""
    def __init__(self):
        try:
            from kiwipiepy import Kiwi
            self.kiwi = Kiwi()
        except Exception:
            self.kiwi = None
        self.cache = {}

    def nouny(self, tok: str) -> bool:
        if tok in self.cache:
            return self.cache[tok]
        ok = True
        if self.kiwi:
            tags = [t.tag for t in self.kiwi.tokenize(tok)]
            has_noun = any(t.startswith("NN") or t in ("NP", "SL", "NR") for t in tags)
            # 문장 끝 어미로 끝나는 덩어리("먹었어요", "맛있다")만 제외 — 브랜드 조어("요거보라")는 살림
            ends_sentence = bool(tags) and tags[-1] == "EF"
            ok = has_noun and not ends_sentence and not VERB_END.search(tok)
        self.cache[tok] = ok
        return ok


def tokens_of(title: str, tk: Tokenizer, query_words: set[str]) -> list[str]:
    toks = []
    for raw in TOKEN_SPLIT.split(title):
        t = raw.strip(".")
        if len(t) < 2 or len(t) > 15:
            continue
        if not HANGUL_OR_ALPHA.search(t):
            continue
        if re.fullmatch(r"[\d년월일시분초회차호]+", t):
            continue
        if t in STOP or t.lower() in STOP:
            continue
        if not tk.nouny(t):
            continue
        toks.append(t)
    return toks


def candidates(posts: list[dict], tk: Tokenizer, seed_words: set[str], today: date):
    """후보 구절별 (최근7일 글 수, 그 전 14일 글 수, 예시 제목, 출처)"""
    recent = defaultdict(set)   # phrase -> set(post idx)
    prev = defaultdict(set)
    example = {}
    src_of = defaultdict(set)
    yt_views = defaultdict(int)
    for i, p in enumerate(posts):
        age = (today - p["date"]).days
        if age < 0 or age > 21:
            continue
        qw = set(TOKEN_SPLIT.split(p["q"]))
        toks = tokens_of(p["title"], tk, qw)
        phrases = set()
        for n in (1, 2, 3):
            for j in range(len(toks) - n + 1):
                ph = " ".join(toks[j:j + n])
                # 검색어 자체만으로 된 구절은 제외 (검색했으니 당연히 나옴)
                if all(w in qw for w in toks[j:j + n]):
                    continue
                if ph in seed_words:
                    continue
                phrases.add(ph)
        bucket = recent if age <= 7 else prev
        for ph in phrases:
            bucket[ph].add(i)
            if ph not in example and age <= 7:
                example[ph] = p
            src_of[ph].add(p["src"])
            if age <= 7 and p["src"] == "youtube":
                yt_views[ph] += p.get("views", 0)
    rows = []
    for ph, s in recent.items():
        c7 = len(s)
        if c7 < 3:
            continue
        rows.append({"phrase": ph, "c7": c7, "cprev": len(prev.get(ph, ())),
                     "example": example.get(ph), "src": src_of[ph], "yt_views": yt_views.get(ph, 0)})
    # 짧은 구절이 긴 구절에 포함되고 글 수가 비슷하면 긴 쪽만 남김 ("토마토마라탕" < "탕화쿵푸 토마토마라탕")
    rows.sort(key=lambda r: (-r["c7"], -len(r["phrase"])))
    kept = []
    for r in rows:
        dominated = False
        for k in list(kept):
            if r["phrase"] == k["phrase"]:
                continue
            if r["phrase"] in k["phrase"] and k["c7"] >= r["c7"] * 0.6:   # 더 긴 구절이 이미 있고 글 수 비슷
                dominated = True
                break
            if k["phrase"] in r["phrase"] and r["c7"] >= k["c7"] * 0.6:   # 내가 더 긴 구절이고 글 수 비슷
                kept.remove(k)
        if not dominated:
            kept.append(r)
    # 겹치는 구절 정리: 두 단어 이상 공유하고 글 수가 비슷하면 하나만 ("더벤티 요거보라 찹쌀떡" vs "요거보라 찹쌀떡 스무디")
    merged = []
    for r in kept:
        rt = set(r["phrase"].split())
        if any(len(rt & set(k["phrase"].split())) >= 2 and k["c7"] >= r["c7"] * 0.6 for k in merged):
            continue
        merged.append(r)
    kept = merged
    # 새로 등장(그 전 2주엔 거의 없던 것)일수록 위로
    for r in kept:
        r["newness"] = r["c7"] / (r["cprev"] + 1)
        yt_bonus = 1 + min(2.0, r["yt_views"] / 200_000)
        r["buzz"] = r["c7"] * (1 + min(3.0, r["newness"])) * (1.5 if "news" in r["src"] else 1.0) * yt_bonus
    kept.sort(key=lambda r: -r["buzz"])
    return kept


def datalab_momentum(phrases: list[str], key_id: str, key: str, today: date) -> dict[str, float]:
    """최근 3일 ÷ 이전 4주 (5개씩 묶어 호출)"""
    out = {}
    start, end = today - timedelta(days=40), today
    for i in range(0, len(phrases), 5):
        chunk = phrases[i:i + 5]
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
                "keywordGroups": [{"groupName": p, "keywords": [p]} for p in chunk]}
        try:
            r = requests.post(f"{BASE}/search-trend/v1/search", headers={**_headers(key_id, key),
                              "Content-Type": "application/json"}, json=body, timeout=30)
            r.raise_for_status()
            for res in r.json().get("results", []):
                vals = [float(d["ratio"]) for d in res["data"]]
                if len(vals) < 10:
                    out[res["title"]] = 0.0
                    continue
                recent = sum(vals[-3:]) / 3
                base = sum(vals[:-3]) / max(1, len(vals) - 3)
                out[res["title"]] = (recent / base) if base > 0 else (5.0 if recent > 0 else 0.0)
        except Exception as e:
            print(f"[datalab 실패] {chunk}: {e}", file=sys.stderr)
        time.sleep(0.3)
    return out


def buzz_section(seeds: dict, key_id: str, key: str, today: date, top_n: int = 15, yt_key: str = "") -> str:
    bq = seeds.get("buzz_queries", {})
    nq = seeds.get("buzz_news_queries", [])
    if not bq and not nq:
        return ""
    tk = Tokenizer()
    seed_words = {k for kws in seeds.get("categories", {}).values() for k in kws}
    posts = []
    for cat, qs in bq.items():
        for q in qs:
            posts += search_blog(q, key_id, key, pages=2)
    for q in nq:
        posts += search_news(q, key_id, key)
    yq = seeds.get("buzz_youtube_queries", [])
    if yt_key and yq:
        for q in yq:
            posts += search_youtube(q, yt_key, today)
            time.sleep(0.2)
    print(f"[buzz] 수집한 글 {len(posts)}개")
    if not posts:
        return ""
    rows = candidates(posts, tk, seed_words, today)[:40]
    mom = datalab_momentum([r["phrase"] for r in rows], key_id, key, today)
    for r in rows:
        m = mom.get(r["phrase"], 0.0)
        r["mom"] = m
        # 검색이 실제로 붙는 것(데이터랩에 값이 있음)에 가산
        r["final"] = r["buzz"] * (1 + min(3.0, max(0.0, m - 1))) * (1.0 if m > 0 else 0.4)
    rows.sort(key=lambda r: -r["final"])
    rows = rows[:top_n]
    if not rows:
        return ""

    def mom_txt(m):
        if m == 0: return "검색 거의 없음"
        if m >= 1.5: return f"↑↑ {m:.1f}배"
        if m >= 1.15: return f"↑ {m:.1f}배"
        return "→ 보합"

    def views_txt(n):
        if n <= 0: return "-"
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000: return f"{n//1000}K"
        return str(n)

    L = ["## 🔥 요즘 뜨는 것 (블로그·뉴스·유튜브 제목에서 새로 많이 보이는 이름)",
         "최근 7일 새 글·영상 제목에 자주 나온 브랜드·메뉴·제품. '그 전 2주'가 0에 가까울수록 이번 주에 갑자기 뜬 것. 검색흐름은 데이터랩 최근 3일 ÷ 이전 4주.",
         "",
         "| 이름 | 최근 7일 글 | 그 전 2주 | 유튜브 조회수 | 검색흐름 | 예시 |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        ex = r["example"]
        ex_txt = f"[{ex['title'][:40]}]({ex['link']})" if ex and ex.get("link") else (ex["title"][:40] if ex else "")
        src = (" 📰" if "news" in r["src"] else "") + (" ▶️" if "youtube" in r["src"] else "")
        L.append(f"| **{r['phrase']}**{src} | {r['c7']} | {r['cprev']} | {views_txt(r['yt_views'])} | {mom_txt(r['mom'])} | {ex_txt} |")
    L.append("")
    L.append("📰 = 뉴스에도 나온 것, ▶️ = 최근 7일 유튜브 영상 제목에도 나온 것(조회수는 그 영상들 합). 여기 나온 이름은 아직 글이 적을 때 선점하는 용도라, 한 번 검색해 보고 실제 유행인지 확인 후 쓰세요.")
    return "\n".join(L)
