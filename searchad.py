"""
네이버 검색광고 API — 키워드 도구
- 월간 검색수(PC+모바일, 절대값)와 연관 키워드를 준다. 판다랭크 '월 검색량'이 이 숫자.
- 키 없으면 조용히 빈 결과 → 나머지는 데이터랩 상대값으로 동작.

GitHub Secrets: NAVER_AD_API_KEY, NAVER_AD_SECRET, NAVER_AD_CUSTOMER_ID
"""
import base64
import hashlib
import hmac
import os
import sys
import time

import requests

BASE = "https://api.searchad.naver.com"
API_KEY = os.environ.get("NAVER_AD_API_KEY", "")
SECRET = os.environ.get("NAVER_AD_SECRET", "")
CUSTOMER = os.environ.get("NAVER_AD_CUSTOMER_ID", "")


def enabled() -> bool:
    return bool(API_KEY and SECRET and CUSTOMER)


def _headers(method: str, uri: str) -> dict:
    ts = str(round(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": API_KEY, "X-Customer": CUSTOMER, "X-Signature": sig}


def _num(v) -> int:
    """'< 10' 같은 값은 5로"""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.startswith("<"):
        return 5
    try:
        return int(float(s))
    except ValueError:
        return 0


def _norm(k: str) -> str:
    return k.replace(" ", "").lower()


def keyword_tool(hints: list[str]) -> list[dict]:
    """hintKeywords 최대 5개. 각 항목: relKeyword(공백 제거됨), monthlyPcQcCnt, monthlyMobileQcCnt, compIdx"""
    uri = "/keywordstool"
    try:
        r = requests.get(BASE + uri, headers=_headers("GET", uri),
                         params={"hintKeywords": ",".join(hints), "showDetail": 1}, timeout=20)
        r.raise_for_status()
        return r.json().get("keywordList", [])
    except Exception as e:
        print(f"[검색광고 실패] {hints}: {e}", file=sys.stderr)
        return []


def monthly_volumes(keywords: list[str]) -> dict[str, dict]:
    """키워드별 {pc, mo, total, comp}. 5개씩 묶어 호출."""
    if not enabled():
        return {}
    out = {}
    for i in range(0, len(keywords), 5):
        chunk = keywords[i:i + 5]
        want = {_norm(k): k for k in chunk}
        for it in keyword_tool(chunk):
            k = want.get(_norm(it.get("relKeyword", "")))
            if k and k not in out:
                pc, mo = _num(it.get("monthlyPcQcCnt")), _num(it.get("monthlyMobileQcCnt"))
                out[k] = {"pc": pc, "mo": mo, "total": pc + mo, "comp": it.get("compIdx", "")}
        time.sleep(0.2)
    return out


def related(keyword: str, exclude: set[str], top: int = 10) -> list[dict]:
    """한 키워드의 연관 키워드 (월 검색량 순). 판다랭크 '연관 키워드' 탭에 해당."""
    if not enabled():
        return []
    rows = []
    ex = {_norm(x) for x in exclude} | {_norm(keyword)}
    for it in keyword_tool([keyword]):
        rk = it.get("relKeyword", "")
        if _norm(rk) in ex:
            continue
        pc, mo = _num(it.get("monthlyPcQcCnt")), _num(it.get("monthlyMobileQcCnt"))
        rows.append({"keyword": rk, "total": pc + mo, "pc": pc, "mo": mo, "comp": it.get("compIdx", "")})
    rows.sort(key=lambda r: -r["total"])
    return rows[:top]


def saturation(monthly_posts: int | None, monthly_search: int | None) -> tuple[float | None, str]:
    """블로그 포화도 = 월 발행량 ÷ 월 검색량, 노출 기회 등급"""
    if not monthly_posts and monthly_posts != 0:
        return None, ""
    if not monthly_search:
        return None, ""
    s = monthly_posts / monthly_search
    if s < 0.05: g = "매우 높음"
    elif s < 0.15: g = "높음"
    elif s < 0.4: g = "보통"
    elif s < 1.0: g = "낮음"
    else: g = "매우 낮음"
    return s, g
