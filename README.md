# vid-moment-search

로컬 영상과 자연어 쿼리(찾을 장면 묘사)를 받아 해당 장면의 타임코드를 찾고,
여러 모델을 같은 테스트셋으로 돌려 정확도·비용·속도·안정성을 비교하는 테스트 도구.

| 백엔드 | 방식 |
|---|---|
| `gemini` | 영상을 Gemini File API에 올리고, 구조화 출력(JSON 스키마)으로 구간 후보를 받는다. 끝나면 업로드 파일 삭제. |
| `twelvelabs` | 영상을 TwelveLabs Marengo 인덱스에 올리고 텍스트 검색으로 클립을 받는다. 인덱스와 인덱싱된 영상은 재사용한다. |

별도 DB나 전처리(샷 경계 검출, 프레임 추출)는 없다.

## 설치

```bash
conda activate vid-moment-search   # 없으면: conda create -n vid-moment-search python=3.12 -y
pip install -r requirements.txt
```

## API 키 설정

| 백엔드 | 키 이름 | 발급 |
|---|---|---|
| gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |
| twelvelabs | `TWELVE_LABS_API_KEY` | [TwelveLabs Playground](https://playground.twelvelabs.io/) → API Keys |

프로젝트 루트의 `.env`에 키를 적으면 실행 시 자동으로 읽는다. `.env`는 `.gitignore`에 있어 git에 올라가지 않는다.

```powershell
copy .env.example .env    # bash: cp .env.example .env
```

```
# .env
GEMINI_API_KEY=발급받은_키
TWELVE_LABS_API_KEY=발급받은_키
```

쓰는 백엔드의 키만 채우면 된다. 같은 이름의 환경변수가 이미 설정돼 있으면 `.env`보다 그쪽이 우선한다.

## 프로필

비교 단위는 [profiles.json](profiles.json)의 프로필이다. 백엔드·모델·옵션을 묶어 이름을 붙인다.

| 프로필 | 내용 |
|---|---|
| `gemini-3.1-pro` (기본) | Gemini 3.1 Pro, 기본(static) 처리 |
| `gemini-3.8-flash-static` | Gemini 3.8 Flash, static 처리 (1fps 프레임 전체를 넣음) |
| `gemini-3.8-flash-agentic` | Gemini 3.8 Flash, agentic 처리 (모델이 타임라인을 탐색하며 필요한 구간만 봄) |
| `twelvelabs-marengo3.0` | TwelveLabs Marengo 3.0 검색 |

Gemini 옵션:

- `processing`: `static`, `agentic`, 또는 생략(모델 기본값)
  - agentic은 `config.GEMINI_AGENTIC_MODELS`에 있는 모델(3.8/3.7/3.6 Flash, 3.5 Flash Lite)만 쓸 수 있다.
  - 다른 모델에 agentic을 지정하면 실행 전에 에러가 난다.
- `media_resolution`: `low`, `medium`, `high`
- `thinking_level`: `minimal`, `low`, `medium`, `high`

새 조합을 비교하려면 프로필을 하나 추가하면 된다.

## 단일 검색

```bash
python search.py <영상 경로> "<찾을 장면 묘사>" [--profile 프로필]
python search.py videos/camping.mp4 "텐트 앞에서 장작에 불을 붙이는 장면" --profile gemini-3.8-flash-agentic
```

## 평가

### 1. 테스트셋 작성

`testsets/template.json`을 복사해서 채운다. 영상은 최상위 `video`에 한 번만 적고(케이스별로 덮어쓰기 가능), 시간은 초(숫자) 또는 `"mm:ss"`/`"hh:mm:ss"`로 적는다.

```json
{
  "video": "../videos/camping.mp4",
  "youtube_url": "https://www.youtube.com/watch?v=...",
  "cases": [
    {"id": "c01", "query": "장작에 불을 붙이는 장면", "gt": [["12:30", "12:58"]]},
    {"id": "c02", "query": "커피를 내리는 장면", "gt": [["05:10", "05:40"], ["41:00", "41:20"]]},
    {"id": "c03", "query": "빨간 컵으로 물을 마시는 장면", "gt": [["20:00", "20:10"]], "decoys": [["33:00", "33:08"]], "note": "33분엔 파란 컵"},
    {"id": "c04", "query": "강아지가 텐트로 뛰어드는 장면", "gt": []}
  ]
}
```

| 케이스 유형 | 입력 방법 | 보는 것 |
|---|---|---|
| normal | `gt`에 정답 구간 (여러 번 나오면 모두) | 정확도, 경계 오차 |
| decoy | `gt` + 헷갈리는 오답 구간 `decoys` | 진짜 구별 능력 |
| negative | `gt: []` (영상에 없는 장면) | "못 찾음"이라고 하는지, 지어내는지 |
| unlabeled | `gt: null` (정답 미입력) | 비용·속도·안정성만. 정확도 지표에서는 빠진다 |

쿼리가 비어 있으면 SKIP한다.

정답을 다 채우기 전에도 돌려볼 수 있다.

1. 정답을 비워 둔 채(`gt: null`) 실행한다.
2. 케이스별 표의 1순위 타임코드와 검토 시트를 보고 정답 구간을 채운다.
3. `report.py --testset`을 돌리면 API를 다시 부르지 않고 정확도까지 다시 계산된다.

`youtube_url`을 적으면 정성 검토 시트에 예측 시점으로 바로 가는 링크가 생긴다.

### 2. 실행

```bash
python evaluate.py testsets/camping.json --profile gemini-3.1-pro --profile gemini-3.8-flash-static --profile gemini-3.8-flash-agentic --repeats 3
```

- 프로필마다 영상을 한 번 올리고, (케이스 수 × `--repeats`)번 질의한다. 출력 안정성을 보려면 `--repeats`를 3 이상으로 둔다.
- 질의마다 원문 응답, 토큰 사용량, 지연 시간, 형식 위반, 오류가 `results/<시각>_<프로필>.json`에 바로 기록된다. 중간에 멈춰도 그때까지의 기록은 남는다.
- 실행이 끝나면 아래 리포트가 출력된다.

### 3. 리포트

```bash
python report.py                          # results/에서 프로필별 최신 실행을 비교
python report.py results/a.json results/b.json
python report.py --review review.csv      # 정성 검토 시트 저장
python report.py --testset testsets/camping.json   # 정답을 고친 뒤 API 재호출 없이 재계산
```

출력은 두 개의 표다.

- **지표 표:** 행이 지표, 열이 프로필이다.
- **케이스별 표:** 케이스마다 top-1 IoU 평균, 디코이에 속은 횟수, "못 찾음" 응답 횟수를 보여준다.

### 지표 정의

| 구분 | 지표 | 정의 |
|---|---|---|
| 정확도 | R@1 / R@K IoU≥θ | 1순위(또는 K개 후보 중 하나)가 정답 구간 중 하나와 IoU≥θ인 질의 비율. θ = 0.3/0.5/0.7. 정답 있는 케이스(normal+decoy)만 |
| | mIoU@1 | 1순위와 정답 구간의 IoU 평균 (결과 없으면 0) |
| 경계 오차 | 시작/끝 오차 | 1순위가 정답과 겹친 경우, 가장 많이 겹친 정답 구간과의 시작·끝 시점 차이(초). 평균/중앙값 |
| 디코이 | R@1 IoU≥0.5 | 디코이 케이스에서 1순위가 정답을 맞힌 비율 |
| | 디코이 오인율@1 | 1순위가 디코이와 IoU≥0.3이고 정답보다 디코이에 더 많이 겹친 비율 |
| 없음 처리 | '못 찾음' 응답률 | 정답 없는 케이스에서 빈 결과를 돌려준 비율. 나머지는 지어낸 답 |
| 비용 | 질의당/합계 ($) | 응답에 찍힌 실제 사용량 × [config.py](config.py) 단가 (아래 참고) |
| | 토큰 | 질의당 입력·캐시 적중·출력·thinking 토큰 평균 (Gemini) |
| 속도 | 질의 지연 | API 호출~응답 완료 시간. 평균, p50/p95/최대 |
| | 준비 시간 | 업로드(+TwelveLabs 인덱싱) 시간. 질의 지연과 분리 |
| 안정성 | API 오류율 | 오류·타임아웃 난 질의 비율 |
| | 형식 준수율 | 응답이 스키마를 지키고, 타임코드가 HH:MM:SS로 파싱되고, start≤end이고, 후보 수가 K 이하인 비율 |
| | 반복 일관성 | 같은 질의 반복 간 1순위 구간의 pairwise IoU 평균 / 정답 여부(IoU≥0.5, 없음 케이스는 빈 결과 여부)가 모든 반복에서 같은 케이스 비율 |

#### 비용 계산 방식

**Gemini:** API 응답의 `usage_metadata`에 실제 토큰 수가 찍히고, 이 값을 기록에 그대로 저장한다. 금액은 리포트를 만들 때 이 토큰 수에 단가를 곱해 계산한다.

- 같은 영상을 반복해서 질의하면 Gemini의 암시적 캐싱이 적용될 수 있다. 캐시에 적중한 토큰은 캐시 단가로 따로 계산한다.
- 3.1 Pro는 프롬프트가 200K 토큰을 넘으면 비싼 단가가 적용된다.

**TwelveLabs:** 응답에 과금 정보가 없다. 대신 실제 검색 횟수와 새로 인덱싱한 영상 길이에 단가를 곱한다.

단가는 공식 가격표를 보고 직접 확인해야 한다. 3.8/3.7/3.6 Flash는 2027년부터 2배가 된다.

### 정성 검토

`--review review.csv`로 시트를 만들어 엑셀에서 연다. 시트 구성은 다음과 같다.

- 케이스 × 프로필마다 첫 번째 성공 질의의 후보를 한 줄씩 적는다.
- 각 줄에는 예측 구간, IoU, 신뢰도, 모델이 말한 근거, YouTube 시점 링크가 들어간다.
- `판정`과 `메모` 칸은 비워 두니 직접 채운다.

## 1시간 영상 관련 참고

- **Gemini static 처리:** 영상 1초에 약 100토큰(low 해상도)이 들어 1시간이면 약 36만 토큰이다.
  - 3.1 Pro는 200K 초과 단가가 적용돼 질의 1회 입력 비용만 약 $1.4다.
  - `media_resolution: high`면 1시간에 약 108만 토큰이라 컨텍스트 한도(1M)를 넘는다.
- **Gemini agentic 처리:** 필요한 구간만 보므로 토큰이 크게 줄어들 수 있다(공식 문서 기준 최대 88%). 영상 탐색에 쓴 토큰은 thinking 토큰으로 잡힌다.
- **영상 화질:** 테스트 영상은 720p로 고정한다. 1시간 720p는 보통 1GB 안팎이라 Gemini File API 한도(파일당 2GB) 안에 들어온다. 넘으면 업로드 전에 에러로 알려준다.
  - Gemini 토큰 수는 원본 화질이 아니라 `media_resolution` 설정으로 정해지므로, 720p로 받아도 비용은 그대로다.
- **TwelveLabs:** 첫 실행 때 인덱싱에 수십 분이 걸릴 수 있다. 이 시간은 준비 시간으로 따로 잡히고, 이후 실행은 기존 인덱싱을 재사용한다.
- **타임아웃:** 질의 타임아웃은 기본 600초다. 타임아웃이 나면 API 오류로 기록된다.

## TwelveLabs 동작 방식

- 인덱스 `vid-moment-search-marengo3-0`을 처음 실행 때 만들고 계속 재사용한다.
- 같은 영상(파일명+크기)이면 다시 올리지 않는다. 기록의 `prepare.info.reused`로 확인할 수 있고, 인덱싱 비용은 새로 인덱싱한 경우에만 잡힌다.
- 검색은 해당 영상으로만 범위를 제한한다.
- 200MB 이하는 한 번에 업로드하고, 그보다 크면 나눠서 올린다. 파일은 4GB까지, 길이는 4초~4시간까지다(Marengo 3.0 제한).
- 신뢰도 점수 없이 rank 순서만 준다. 항상 결과를 돌려주므로 "못 찾음" 응답률은 구조적으로 0%다.
- 짧은 클립 단위로 결과가 나오므로, 정답 구간이 길면 IoU가 낮게 나올 수 있다.
- 인덱스와 영상 삭제는 [Playground](https://playground.twelvelabs.io/)에서 한다.

## 설정

[config.py](config.py)의 값은 환경변수나 `.env`로 덮어쓸 수 있다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `VMS_PROFILE` | `gemini-3.1-pro` | `--profile` 생략 시 프로필 |
| `VMS_TIMEOUT_SEC` | `600` | 질의 1회 타임아웃(초) |
| `VMS_PROCESSING_TIMEOUT_SEC` | `600` | 업로드 후 서버 측 처리 대기 한도(초) |
| `VMS_TL_INDEX_PREFIX` | `vid-moment-search` | TwelveLabs 인덱스 이름 앞부분 |
| `VMS_TL_INDEXING_TIMEOUT_SEC` | `3600` | TwelveLabs 인덱싱 대기 한도(초) |

## 다른 서비스 추가

1. [backends/](backends/)에 모듈을 만든다.
2. `make_client`, `prepare`, `query`, `cleanup` 네 함수를 구현한다. 인터페이스는 [backends/\_\_init\_\_.py](backends/__init__.py) 상단에 적어 두었다.
3. `NAMES`에 모듈 이름을 추가하고, `profiles.json`에 프로필을 만든다.
