# blog-keywords

매일 **저녁 6시(KST)** 에 내일 사람들이 많이 찾을 만한 블로그 키워드를 뽑아서 **Issues** 탭에 올려줍니다.

## 어떻게 고르나
1. **네이버 데이터랩 검색 추이** — 최근 3일이 지난 4주보다 얼마나 올랐나 + 작년 이맘때 튀었나
2. **달력** — 연휴 끝, 요일, 월초, 계절, 추석·설·크리스마스 같은 기념일
3. **경쟁도** — 네이버 블로그에 이미 있는 글 수 (적을수록 유리)

## 파일
- `seeds.json` — 카테고리별 후보 키워드. **여기만 고치면 됩니다.** (폰에서 연필 아이콘으로 수정 가능)
- `keywords.py` — 점수 계산
- `.github/workflows/daily.yml` — 매일 자동 실행
- `reports/` — 날짜별 결과 누적

## 지금 당장 돌려보기
Actions 탭 → **내일 키워드 뽑기** → **Run workflow** → 초록 버튼. 1~2분 뒤 Issues 탭에 결과가 생깁니다.

## 설정 (한 번만)
Settings → Secrets and variables → Actions → **New repository secret**
- `NAVER_APIHUB_KEY_ID`
- `NAVER_APIHUB_KEY`
