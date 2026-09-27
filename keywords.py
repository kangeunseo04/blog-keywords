"""
블로그 키워드 추천 도구
- 내일(기본) 날짜 기준으로 사람들이 많이 찾을 만한 키워드를 카테고리별로 뽑는다.
- 신호 3개: 네이버 데이터랩 검색 추이(최근 흐름 + 작년 이맘때), 달력(연휴/요일/계절/기념일), 블로그 문서 수(경쟁도)
- 결과: reports/YYYY-MM-DD.md 로 저장 (GitHub Actions가 이슈로도 올려줌)

실행: python keywords.py            (내일 날짜 기준)
      python keywords.py 2026-10-01 (특정 날짜 기준)
"""
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import holidays
import requests

KST = ZoneInfo("Asia/Seoul")
KEY_ID = os.environ.get("NAVER_APIHUB_KEY_ID", "")
KEY = os.environ.get("NAVER_APIHUB_KEY", "")
BASE = "https://naverapihub.apigw.ntruss.com"
HEADERS = {
    "X-NCP-APIGW-API-KEY-ID": KEY_ID,
    "X-NCP-APIGW-API-KEY": KEY,
    "Content-Type": "application/json",
}
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


# ---------- 달력 신호 ----------
def calendar_tags(target: date) -> list[tuple[str, str]]:
    """대상 날짜에 해당하는 (태그, 이유) 목록"""
    kr = holidays.KR(years=[target.year - 1, target.year, target.year + 1])
    tags = []

    def off(d):  # 쉬는 날인가
        return d.weekday() >= 5 or d in kr

    # 연휴 끝: 어제까지 3일 이상 연속으로 쉬었고 오늘은 출근
    if not off(target):
        n, d = 0, target - timedelta(days=1)
        names = set()
        while off(d):
            if d in kr:
                names.add(kr[d].split(" ")[0])
            n += 1
            d -= timedelta(days=1)
        if n >= 3:
            tags.append(("연휴끝", f"{n}일 연휴 다음 첫 출근일"))
            if any("추석" in x for x in names):
                tags.append(("추석", "추석 연휴 직후"))
            if any("설" in x for x in names):
                tags.append(("설날", "설 연휴 직후"))

    # 연휴 직전/중: 3일 안에 추석·설이 있으면
    for i in range(0, 4):
        d = target + timedelta(days=i)
        if d in kr:
            name = kr[d]
            if "추석" in name and ("추석", "추석 연휴 직후") not in tags:
                tags.append(("추석", f"{i}일 뒤 {name}"))
                break
            if "설" in name and ("설날", "설 연휴 직후") not in tags:
                tags.append(("설날", f"{i}일 뒤 {name}"))
                break

    wd = target.weekday()
    if wd == 0:
        tags.append(("월요일", "월요일 = 다이어트/식단 시작 검색 많음"))
    if wd == 4:
        tags.append(("금요일", "주말 앞두고 맛집/카페/OTT 검색 많음"))
    if wd >= 5:
        tags.append(("주말", "주말 = 맛집/카페/데이트/OTT 검색 많음"))
    if wd == 6:
        tags.append(("일요일", "일요일 밤 = 다음 주 계획·다이어트 결심 검색"))
    if target.day <= 3:
        tags.append(("월초", "월초 = 신메뉴/계획 검색"))

    m = target.month
    season = {3: "봄", 4: "봄", 5: "봄", 6: "여름", 7: "여름", 8: "여름",
              9: "가을", 10: "가을", 11: "가을", 12: "겨울", 1: "겨울", 2: "겨울"}[m]
    tags.append((season, f"{m}월"))

    md = (m, target.day)
    events = {
        "새해": [(1, d) for d in range(1, 8)],
        "크리스마스": [(12, d) for d in range(18, 26)],
        "할로윈": [(10, d) for d in range(25, 32)],
        "빼빼로데이": [(11, d) for d in range(8, 12)],
        "발렌타인": [(2, d) for d in range(10, 15)],
        "블랙프라이데이": [(11, d) for d in range(20, 31)],
        "수능": [(11, d) for d in range(10, 20)],
    }
    for tag, days in events.items():
        if md in days:
            tags.append((tag, f"{m}/{target.day} 기념일 시즌"))
    return tags


# ---------- 네이버 API ----------
def datalab(groups: list[dict], start: date, end: date) -> dict:
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "date",
        "keywordGroups": groups,
    }
    r = requests.post(f"{BASE}/search-trend/v1/search", headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def blog_count(keyword: str) -> int | None:
    """네이버 블로그에 이미 있는 문서 수 (경쟁도). 실패하면 None."""
    try:
        r = requests.get(f"{BASE}/search/v1/blog", headers=HEADERS,
                         params={"query": keyword, "display": 1}, timeout=15)
        r.raise_for_status()
        return int(r.json().get("total", 0))
    except Exception:
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def is_off(d: date, kr) -> bool:
    return d.weekday() >= 5 or d in kr


def last_year_ref(target: date) -> tuple[date, str]:
    """작년 비교 기준일. 추석·설 근처(±10일)면 '작년 명절 기준 같은 위치', 아니면 같은 날짜.
    예) 올해 추석 3일 뒤 → 작년 추석 3일 뒤"""
    kr = holidays.KR(years=[target.year - 1, target.year])
    for i in range(-10, 11):
        d = target + timedelta(days=i)
        name = kr.get(d, "")
        if name in ("추석", "설날"):
            offset = target - d
            ly_main = [x for x, n in kr.items() if n == name and x.year == target.year - 1]
            if ly_main:
                return ly_main[0] + offset, f"작년 {name} 기준 {offset.days:+d}일"
    ly = target.replace(year=target.year - 1)
    return ly, "작년 같은 날짜"


def post_holiday(target: date, ref: date) -> bool:
    """대상일은 평일인데 데이터 마지막 3일이 대부분 쉬는 날이면 True (연휴 직후)"""
    kr = holidays.KR(years=[target.year])
    if is_off(target, kr):
        return False
    off_days = sum(is_off(ref - timedelta(days=i), kr) for i in range(3))
    return off_days >= 2


def series_signals(data: list[dict], target: date, ly_ref: date) -> dict:
    """ratio 시계열에서 최근 흐름·작년 이맘때·요일 패턴·최근 수준 계산"""
    by = {d["period"]: float(d["ratio"]) for d in data}
    kr = holidays.KR(years=[target.year - 1, target.year])

    def window(center: date, days_back: int, days_fwd: int = 0):
        out = []
        for i in range(-days_back, days_fwd + 1):
            v = by.get((center + timedelta(days=i)).isoformat())
            if v is not None:
                out.append(v)
        return out

    today = datetime.now(KST).date()
    last_avail = max(by) if by else None
    # 데이터랩은 하루 이틀 늦게 채워지므로 실제 있는 마지막 날짜 기준
    ref = min(today, date.fromisoformat(last_avail)) if last_avail else today

    # 최근 흐름: 대상일과 같은 종류의 날(평일↔평일, 쉬는날↔쉬는날) 최근 3일만 사용
    # → 연휴 직후 평일을 볼 때 연휴 동안의 외식·영화 검색이 섞이지 않음
    want_off = is_off(target, kr)
    same_kind = []
    d = ref
    while len(same_kind) < 3 and (ref - d).days < 21:
        v = by.get(d.isoformat())
        if v is not None and is_off(d, kr) == want_off:
            same_kind.append(v)
        d -= timedelta(days=1)
    recent3 = mean(same_kind) if same_kind else mean(window(ref, 2))
    prior28 = mean(window(ref - timedelta(days=3), 27))
    level7 = mean(window(ref, 6))

    ly_peak = mean(window(ly_ref, 2, 2))
    ly_base = mean(window(ly_ref - timedelta(days=3), 27))

    # 요일 패턴: 최근 8주 중 공휴일 뺀 날들에서 (대상 요일 평균) ÷ (전체 평균)
    same_wd, all_days = [], []
    for i in range(56):
        d = ref - timedelta(days=i)
        v = by.get(d.isoformat())
        if v is None or d in kr:
            continue
        all_days.append(v)
        if d.weekday() == target.weekday():
            same_wd.append(v)
    wf = (mean(same_wd) / mean(all_days)) if all_days and mean(all_days) > 0 and same_wd else 1.0

    return {
        "level": level7,
        "momentum": (recent3 / prior28) if prior28 > 0 else (1.0 if recent3 == 0 else 3.0),
        "seasonal": (ly_peak / ly_base) if ly_base > 0 else 1.0,
        "weekday": wf,
        "no_data": level7 == 0 and prior28 == 0,
    }


def fetch_all(keywords: list[str], anchor: str, target: date, ly_ref: date) -> dict[str, dict]:
    """앵커 1개 + 키워드 4개씩 묶어 호출. 앵커 대비 상대 검색량으로 배치 간 비교 가능하게 함."""
    start = min(ly_ref, target.replace(year=target.year - 1)) - timedelta(days=40)
    end = datetime.now(KST).date()
    out = {}
    for i in range(0, len(keywords), 4):
        chunk = keywords[i:i + 4]
        groups = [{"groupName": anchor, "keywords": [anchor]}] + \
                 [{"groupName": k, "keywords": [k]} for k in chunk]
        try:
            res = datalab(groups, start, end)
        except Exception as e:
            print(f"[datalab 실패] {chunk}: {e}", file=sys.stderr)
            continue
        results = {r["title"]: r["data"] for r in res.get("results", [])}
        a = series_signals(results.get(anchor, []), target, ly_ref)
        a_level = a["level"] or 1e-9
        for k in chunk:
            s = series_signals(results.get(k, []), target, ly_ref)
            s["rel_volume"] = s["level"] / a_level  # 앵커(예: '다이어트')=1.0 기준
            out[k] = s
        time.sleep(0.3)
    return out


# ---------- 점수 ----------
def pct_rank(values: dict[str, float]) -> dict[str, float]:
    items = sorted(values.items(), key=lambda x: x[1])
    n = len(items)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(items)}


def score_all(sig: dict[str, dict], comp: dict[str, int | None], ctx_kw: set[str],
              after_holiday: bool) -> dict[str, float]:
    vol_rank = pct_rank({k: math.log1p(v["rel_volume"] * 100) for k, v in sig.items()})
    comp_vals = {k: math.log1p(c) for k, c in comp.items() if c is not None}
    comp_rank = pct_rank(comp_vals) if comp_vals else {}
    # 연휴 직후엔 '최근 흐름'이 연휴 행동(외식·영화)을 반영하므로 비중을 낮추고 작년·요일 비중을 올림
    w_mom, w_season = (10, 30) if after_holiday else (20, 20)
    scores = {}
    for k, v in sig.items():
        if v["no_data"]:
            scores[k] = -1
            continue
        s = 35 * vol_rank[k]
        s += w_mom * max(-1.0, min(1.0, v["momentum"] - 1))            # 최근 3일 vs 이전 4주
        s += w_season * max(-1.0, min(1.0, (v["seasonal"] - 1) / 2))   # 작년 같은 위치에서 튀었나
        s += 15 * max(-1.0, min(1.0, (v["weekday"] - 1) * 3))          # 이 요일에 강한 키워드인가 (±33%면 만점)
        s += 10 * (1 - comp_rank.get(k, 0.5))                          # 문서 적을수록 유리
        if k in ctx_kw:
            s += 10
        scores[k] = round(s, 1)
    return scores


# ---------- 리포트 ----------
def arrow(x: float) -> str:
    if x >= 1.5: return f"↑↑ {x:.1f}배"
    if x >= 1.15: return f"↑ {x:.1f}배"
    if x <= 0.7: return f"↓ {x:.1f}배"
    return "→ 보합"


def pct(x: float) -> str:
    d = round((x - 1) * 100)
    return f"{d:+d}%" if abs(d) >= 3 else "보통"


def fmt_int(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def build_report(target: date, tags, seeds, sig, comp, scores, ctx_kw, ly_note: str, after_holiday: bool) -> str:
    L = []
    wd = WEEKDAY_KO[target.weekday()]
    L.append(f"# {target.isoformat()} ({wd}) 키워드 추천\n")
    L.append("## 오늘의 달력 신호")
    for t, why in tags:
        L.append(f"- **{t}** — {why}")
    L.append(f"- 작년 비교 기준: {ly_note}")
    if after_holiday:
        L.append("- ⚠️ 연휴 직후: '최근흐름'은 연휴 전 평일 3일 기준으로 계산(연휴 중 외식·영화 검색 제외), 작년·요일 패턴 비중을 높임")
    L.append("")
    L.append(f"검색량=`다이어트`를 1.0으로 본 배수. 최근흐름=대상일과 같은 종류의 날(평일/쉬는날) 최근 3일 ÷ 이전 4주. 작년={ly_note} ÷ 그 전 4주. {wd}요일=최근 8주 중 {wd}요일 평균 ÷ 전체 평균. 문서수=네이버 블로그 기존 글 수(적을수록 경쟁 낮음).\n")

    # 전체 TOP 10
    ranked = sorted([k for k in scores if scores[k] >= 0], key=lambda k: -scores[k])
    cat_of = {}
    for c, kws in seeds["categories"].items():
        for k in kws:
            cat_of.setdefault(k, c)
    for k in ctx_kw:
        cat_of.setdefault(k, "달력 키워드")

    L.append("## 👉 내일 쓸 만한 키워드 TOP 10")
    L.append(f"| 순위 | 키워드 | 분류 | 검색량 | 최근흐름 | 작년 | {wd}요일 | 문서수 | 점수 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, k in enumerate(ranked[:10], 1):
        v = sig[k]
        mark = " 🗓" if k in ctx_kw else ""
        L.append(f"| {i} | **{k}**{mark} | {cat_of.get(k,'')} | {v['rel_volume']:.2f} | {arrow(v['momentum'])} | {arrow(v['seasonal'])} | {pct(v['weekday'])} | {fmt_int(comp.get(k))} | {scores[k]} |")
    L.append("")

    # 오늘의 2편 제안: 서로 다른 분류에서 1, 2위
    picks, seen = [], set()
    for k in ranked:
        c = cat_of.get(k, "")
        if c not in seen:
            picks.append(k); seen.add(c)
        if len(picks) == 2:
            break
    if picks:
        L.append("## ✍️ 오늘 2편 제안")
        for k in picks:
            L.append(f"- **{k}** ({cat_of.get(k,'')})")
        L.append("")

    # 카테고리별
    L.append("## 카테고리별 TOP 5")
    groups = dict(seeds["categories"])
    groups["달력 키워드"] = sorted(ctx_kw)
    for c, kws in groups.items():
        rows = sorted([k for k in kws if k in scores and scores[k] >= 0], key=lambda k: -scores[k])[:5]
        if not rows:
            continue
        L.append(f"### {c}")
        L.append(f"| 키워드 | 검색량 | 최근흐름 | 작년 | {wd}요일 | 문서수 | 점수 |")
        L.append("|---|---|---|---|---|---|---|")
        for k in rows:
            v = sig[k]
            L.append(f"| {k} | {v['rel_volume']:.2f} | {arrow(v['momentum'])} | {arrow(v['seasonal'])} | {pct(v['weekday'])} | {fmt_int(comp.get(k))} | {scores[k]} |")
        L.append("")

    nodata = [k for k in scores if scores[k] < 0]
    if nodata:
        L.append("<details><summary>검색량이 거의 없어 제외한 키워드</summary>\n")
        L.append(", ".join(nodata))
        L.append("\n</details>")
    return "\n".join(L)


def main():
    if not KEY_ID or not KEY:
        sys.exit("NAVER_APIHUB_KEY_ID / NAVER_APIHUB_KEY 환경변수가 없습니다.")
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = datetime.now(KST).date() + timedelta(days=1)  # 기본: 내일

    with open(os.path.join(os.path.dirname(__file__) or ".", "seeds.json"), encoding="utf-8") as f:
        seeds = json.load(f)

    tags = calendar_tags(target)
    ctx_kw = set()
    for t, _ in tags:
        ctx_kw.update(seeds["context_keywords"].get(t, []))

    keywords, seen = [], set()
    for kws in seeds["categories"].values():
        for k in kws:
            if k not in seen:
                keywords.append(k); seen.add(k)
    for k in sorted(ctx_kw):
        if k not in seen:
            keywords.append(k); seen.add(k)

    ly_ref, ly_note = last_year_ref(target)
    print(f"대상일 {target} / 달력 태그 {[t for t,_ in tags]} / 작년기준 {ly_ref}({ly_note}) / 키워드 {len(keywords)}개")
    sig = fetch_all(keywords, seeds["anchor"], target, ly_ref)
    if not sig:
        sys.exit("데이터랩 응답이 없습니다. API 키와 Application의 검색어트렌드 권한을 확인하세요.")
    comp = {k: blog_count(k) for k in sig}
    after_holiday = post_holiday(target, datetime.now(KST).date())
    scores = score_all(sig, comp, ctx_kw, after_holiday)
    report = build_report(target, tags, seeds, sig, comp, scores, ctx_kw, ly_note, after_holiday)

    # 요즘 뜨는 것 (실패해도 본 리포트는 나가야 하므로 감싸둠)
    try:
        from buzz import buzz_section
        section = buzz_section(seeds, KEY_ID, KEY, datetime.now(KST).date())
        if section:
            report = report.replace("## 카테고리별 TOP 5", section + "\n\n## 카테고리별 TOP 5", 1)
    except Exception as e:
        print(f"[buzz 실패] {e}", file=sys.stderr)

    os.makedirs("reports", exist_ok=True)
    path = f"reports/{target.isoformat()}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
