# blog-keywords

매일 **저녁 6시(KST)** 에 내일 사람들이 많이 찾을 만한 블로그 키워드를 뽑아서 **Issues** 탭에 올려줍니다.

## 어떻게 고르나
1. **네이버 데이터랩 검색 추이** — 최근 3일이 지난 4주보다 얼마나 올랐나 + 작년 이맘때 튀었나
2. **달력** — 연휴 끝, 요일, 월초, 계절, 추석·설·크리스마스 같은 기념일
3. **경쟁도** — 네이버 블로그에 이미 있는 글 수 (적을수록 유리)
4. **요일 패턴** — 최근 8주에서 그 요일에 유독 많이 찾는 키워드인지
5. **요즘 뜨는 것** — 최근 7일 블로그·뉴스 새 글 제목에서 갑자기 자주 보이는 브랜드·메뉴·제품 (인스타·숏츠 유행 역추적)

## 대시보드로 보기
저장소를 **Public**으로 바꾸고 Settings → Pages → Branch **main / (root)** 로 켜면
`https://kangeunseo04.github.io/blog-keywords/` 에서 그래프·카드로 볼 수 있습니다. (폰 홈 화면에 추가해 두면 앱처럼 열려요)

## 파일
- `seeds.json` — 카테고리별 후보 키워드. **여기만 고치면 됩니다.** (폰에서 연필 아이콘으로 수정 가능)
- `keywords.py` — 점수 계산
- `buzz.py` — 요즘 뜨는 것 찾기 (검색어는 seeds.json의 buzz_queries)
- `searchad.py` — 네이버 검색광고 API (월 검색량·연관 키워드·포화도)
- `index.html` — 대시보드 (GitHub Pages)
- `.github/workflows/daily.yml` — 매일 자동 실행
- `reports/` — 날짜별 결과 누적

## 지금 당장 돌려보기
Actions 탭 → **내일 키워드 뽑기** → **Run workflow** → 초록 버튼. 1~2분 뒤 Issues 탭에 결과가 생깁니다.

## 설정 (한 번만)
Settings → Secrets and variables → Actions → **New repository secret**
- `NAVER_APIHUB_KEY_ID`
- `NAVER_APIHUB_KEY`
- `YOUTUBE_API_KEY` (선택 — 있으면 유튜브 신호도 같이 봄)
- `NAVER_AD_API_KEY`, `NAVER_AD_SECRET`, `NAVER_AD_CUSTOMER_ID` (선택 — 있으면 실제 월 검색량·연관 키워드·포화도가 나옴. searchad.naver.com → 도구 → API 사용 관리)
