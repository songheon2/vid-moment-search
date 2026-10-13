# vid-moment-search

자연어 질의로 긴 영상에서 장면의 시작·끝 시점을 찾는 장면 검색(moment retrieval) 실험 코드와 테스트셋이다.
상용 VLM(Gemini)과 영상 검색 전용 서비스(TwelveLabs)를 같은 테스트셋으로 돌려 정확도·비용·응답 시간을 비교한다.

논문 「영상 제작 의도 기반 질의 확장과 VLM을 활용한 편집용 클립 추천 시스템」(○○학술대회, 2026)의 3장 실험(장면 검색 모듈 평가)에 쓴 데이터셋과 코드를 공개한다.
질의 확장과 클립 추천 모듈은 이 저장소에 포함되어 있지 않다.

## 데이터셋

공개 YouTube 영상 17편(총 약 9.6시간, 평균 약 34분, 720p), 질의 17개, 정답 구간 22개로 구성했다.

- **영상 선정:** 편집 소재로 쓰이는 20분 이상의 브이로그 영상 중, 질의 대상 행동이 짧게 등장하는 영상을 골랐다.
- **질의:** 영상마다 대상 장면의 객체와 행동을 한 문장으로 묘사해 1개씩 작성했다.
- **정답 구간:** 영상을 재생하며 행동이 시작·종료되는 시점을 초 단위로 기록했다. 같은 장면이 여러 번 등장하면 모든 구간을 정답으로 두었다(총 22구간, 길이 2~144초, 중앙값 8초).
- **파일:** [testsets/vlog17.json](testsets/vlog17.json). `gt`는 정답 구간, `decoys`는 오인하기 쉬운 유사 장면이다.

| ID | 영상 | 길이 | 질의 | 정답 구간 |
|---|---|---|---|---|
| q01 | [I6sXHxGjCPU](https://www.youtube.com/watch?v=I6sXHxGjCPU) | 2:17:36 | 사람이 바나나 먹는 장면 | 13:41–13:49, 42:21–43:12 |
| q02 | [x6_cFyjYXwM](https://www.youtube.com/watch?v=x6_cFyjYXwM) | 21:21 | 사람이 런닝머신타는 장면 | 2:13–2:18 |
| q03 | [b9JIUZjfFJc](https://www.youtube.com/watch?v=b9JIUZjfFJc) | 29:54 | 사람이 섹소폰 부르는 장면 | 23:41–24:05 |
| q04 | [vT2c85lcxBg](https://www.youtube.com/watch?v=vT2c85lcxBg) | 26:25 | 사람이 걸어가면서 빵먹는 장면 | 10:57–11:46 |
| q05 | [jMtG6UOgzZA](https://www.youtube.com/watch?v=jMtG6UOgzZA) | 20:32 | 사람들이 마스크 쓰고 서 있는 장면 | 13:02–13:09, 19:30–19:38 |
| q06 | [HEsjQZjVAIQ](https://www.youtube.com/watch?v=HEsjQZjVAIQ) | 43:45 | 사람이 튀김우동라면 먹는장면 | 32:28–33:08 |
| q07 | [pdDiaihL1Y8](https://www.youtube.com/watch?v=pdDiaihL1Y8) | 34:52 | 주황색 모자를 쓰고 있는 장면 | 24:55–25:00, 25:09–25:55, 31:24–33:48 |
| q08 | [vCSEMlNLmO0](https://www.youtube.com/watch?v=vCSEMlNLmO0) | 29:58 | 사람과 사람이 악수하는 장면 | 27:39–28:25 (유사 장면 7:24–7:35) |
| q09 | [OPHazH7HlA4](https://www.youtube.com/watch?v=OPHazH7HlA4) | 20:39 | 사람이 얼굴화장하는 장면 | 1:22–2:24 |
| q10 | [NJ3Lw-8PWFE](https://www.youtube.com/watch?v=NJ3Lw-8PWFE) | 27:48 | 차량이 주유소로 들어가는 장면 | 23:09–23:14 |
| q11 | [3EDRq8CwXR0](https://www.youtube.com/watch?v=3EDRq8CwXR0) | 25:46 | 경찰서가 나오는 장면 | 15:37–15:41 |
| q12 | [-YRRJL7i5yI](https://www.youtube.com/watch?v=-YRRJL7i5yI) | 21:26 | 사람이 수경을 낀 상태인 장면 | 16:50–16:53 |
| q13 | [rKk928WtHKY](https://www.youtube.com/watch?v=rKk928WtHKY) | 29:51 | 눈 위에 있는 바나나를 집는 장면 | 18:26–18:30 |
| q14 | [wyRZj78vhJw](https://www.youtube.com/watch?v=wyRZj78vhJw) | 26:31 | 사람이 빵을 먹는 장면 | 21:07–21:34 |
| q15 | [B_TWwMgKu-Q](https://www.youtube.com/watch?v=B_TWwMgKu-Q) | 20:52 | 빨간색 커튼을 치는 장면 | 18:23–18:37 |
| q16 | [Vqjyh_m-5a8](https://www.youtube.com/watch?v=Vqjyh_m-5a8) | 33:53 | 파란옷을 입은 남자가 모자를 쓰는 장면 | 21:26–21:29 |
| q17 | [dHm3hfg68V8](https://www.youtube.com/watch?v=dHm3hfg68V8) | 22:29 | 사람이 어묵꼬치를 먹는 장면 | 0:03–0:05, 14:26–14:28 |

영상 파일은 저작권이 각 제작자에게 있으므로 이 저장소에 포함하지 않는다. YouTube ID와 정답 타임코드만 공개하며, 타임코드는 2026년 10월 기준 YouTube 게시본에 맞춰져 있다. 원본 영상이 수정·삭제되면 해당 질의는 재현할 수 없다.

## 실험 결과

17개 질의 기준 결과다(논문 표 1). 측정일은 2026년 10월 11일이다.

| 모델 | R1@0.3 | R1@0.5 | mIoU | 비용 ($/질의) | 평균 응답 시간 (s) |
|---|---|---|---|---|---|
| Gemini 3.8 Flash (에이전틱) | 82.4% | 76.5% | 0.673 | 0.069 | 61.8 |
| Gemini 3.8 Flash (기본) | 70.6% | 64.7% | 0.560 | 0.140 | 48.7 |
| Gemini 3.1 Pro | 41.2% | 35.3% | 0.333 | 0.495 | 45.7 |
| Gemini 3.1 Flash-Lite | 35.3% | 29.4% | 0.301 | 0.046 | 34.5 |
| TwelveLabs Marengo 3.0* | 0.0% | 0.0% | 0.064 | 0.004 | 0.3 |

\* 영상별 인덱싱 비용 때문에 6개 질의(q01, q02, q05, q08, q09, q15)만 평가했다. 비용은 검색 비용만이며, 영상당 인덱싱 비용(약 $0.94)과 인덱싱 시간은 별도다.

**실험 조건**
- Gemini는 `media_resolution: low`로 호출했다. 질의 확장 없이 질의 1개를 그대로 넣고, 최대 5개 후보 구간을 JSON 스키마로 받았다. 질의마다 1회 수행했다.
- **기본 처리:** 영상 전체를 초당 1프레임으로 넣는다.
- **에이전틱 처리:** 같은 모델(`gemini-3.8-flash`)에 영상 처리 옵션 `media_processing: AGENTIC`을 지정한다. 모델이 타임라인을 탐색하며 필요한 구간만 불러온다.
- **R1@θ:** 1순위 예측 구간이 정답 구간 중 하나와 IoU θ 이상인 질의의 비율이다.
- **mIoU:** 1순위 IoU의 평균이다.
- **비용:** API 응답에 기록된 실제 토큰 수에 공식 단가(2026년 10월)를 곱했다.
- **응답 시간:** API 호출부터 응답까지의 평균이며, 영상 업로드와 인덱싱 시간은 제외했다.
- 상용 API 모델은 버전이 바뀔 수 있어, 같은 설정으로 돌려도 결과가 달라질 수 있다.

**실행 기록:** 위 표를 만든 원본 기록을 [results/](results/)에 공개한다. 모델(프로필)마다 파일 하나이고, 질의마다 다음 값을 담고 있다.
- 모델 응답 원문, 후보 구간
- 토큰 사용량, 응답 시간, 형식 위반 여부

API를 다시 호출하지 않고 아래 명령으로 표를 다시 계산할 수 있다.

```bash
python report.py --testset testsets/vlog17.json --review review.csv   # review.csv: 질의·모델별 후보와 YouTube 시점 링크
```

## 재현 방법

```bash
# 1. 환경 (Python 3.12)
conda create -n vid-moment-search python=3.12 -y && conda activate vid-moment-search
pip install -r requirements.txt
pip install yt-dlp            # 영상 다운로드용. 병합에 ffmpeg가 필요하다

# 2. API 키: .env.example을 .env로 복사하고 GEMINI_API_KEY, TWELVE_LABS_API_KEY를 채운다

# 3. 영상 다운로드 (720p, videos/<YouTube ID>.mp4)
python -c "import json; open('videos.txt', 'w').write('\n'.join(c['youtube_url'] for c in json.load(open('testsets/vlog17.json', encoding='utf-8'))['cases']))"
yt-dlp -a videos.txt -S "res:720,vcodec:h264,acodec:m4a" --merge-output-format mp4 -o "videos/%(id)s.%(ext)s"

# 4. 실행과 결과
python evaluate.py testsets/vlog17.json --profile gemini-3.8-flash-agentic --profile gemini-3.8-flash-static --profile gemini-3.1-pro --profile gemini-3.1-flash-lite
python evaluate.py testsets/vlog17.json --profile twelvelabs-marengo3.0 --cases q01 q02 q05 q08 q09 q15
python report.py --testset testsets/vlog17.json --review review.csv
```

17개 질의를 Gemini 4개 프로필로 한 번씩 돌리면 약 $13이 들고, 업로드를 포함해 1.5~2시간 걸린다. TwelveLabs 6개 질의는 인덱싱 비용이 약 $10이다(그중 2시간 17분짜리 d01이 약 $5.7).

---

아래는 도구 사용법이다.

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
| `gemini-3.1-flash-lite` | Gemini 3.1 Flash-Lite, static 처리 |
| `twelvelabs-marengo3.0` | TwelveLabs Marengo 3.0 검색 |

프로필 이름은 모델 ID가 아니다. 예를 들어 `gemini-3.8-flash-agentic`은 모델 `gemini-3.8-flash`를 `processing: agentic`으로 호출한다.

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

쿼리가 비어 있으면 SKIP한다. 영상이 여러 개인 테스트셋은 케이스마다 `video`와 `youtube_url`을 적는다 (예: [testsets/vlog17.json](testsets/vlog17.json)).

정답을 다 채우기 전에도 돌려볼 수 있다.

1. 정답을 비워 둔 채(`gt: null`) 실행한다.
2. 케이스별 표의 1순위 타임코드와 검토 시트를 보고 정답 구간을 채운다.
3. `report.py`를 다시 돌리면 API를 다시 부르지 않고 정확도까지 다시 계산된다. 리포트는 실행 때 쓴 테스트셋 파일의 현재 정답을 읽는다.

`youtube_url`을 적으면 정성 검토 시트에 예측 시점으로 바로 가는 링크가 생긴다.

### 2. 실행

```bash
python evaluate.py testsets/vlog17.json --profile gemini-3.8-flash-static --profile gemini-3.8-flash-agentic --repeats 3
```

- 프로필마다 영상을 한 번 올리고, (케이스 수 × `--repeats`)번 질의한다. 출력 안정성을 보려면 `--repeats`를 3 이상으로 둔다.
- 실패했거나 새로 추가한 케이스만 다시 돌릴 때는 `--cases c02 c03`처럼 케이스를 고른다. 리포트가 케이스별로 최신 성공 기록을 합쳐 준다.
- 질의마다 원문 응답, 토큰 사용량, 지연 시간, 형식 위반, 오류가 `results/<시각>_<프로필>.json`에 바로 기록된다. 중간에 멈춰도 그때까지의 기록은 남는다.
- 실행이 끝나면 아래 리포트가 출력된다.

### 3. 리포트

```bash
python report.py                          # results/의 모든 실행을 프로필별로 합쳐 비교
python report.py results/a.json results/b.json
python report.py --separate               # 같은 프로필이라도 실행마다 따로 (설정 변경 전후 비교 등)
python report.py --review review.csv      # 정성 검토 시트 저장
python report.py --testset testsets/other.json     # 다른 테스트셋 파일의 정답으로 계산
```

같은 테스트셋·같은 프로필(이름과 설정이 같은)의 실행이 여러 개면 하나로 합친다. 케이스마다 성공 기록이 있는 가장 최근 실행의 기록을 쓰므로, 실패한 실행이나 일부만 다시 돌린 실행이 섞여 있어도 된다. 테스트셋이 여러 개면 테스트셋별로 따로 출력하고, 검토 시트도 `review_<테스트셋>.csv`로 나눠 저장한다. `--testset`을 주면 그 테스트셋으로 돌린 실행만 본다.

`evaluate.py`에 프로필을 여러 개 주면 Gemini 프로필끼리는 업로드한 영상을 공유한다 (영상당 한 번만 업로드).

출력은 두 개의 표다.

- **지표 표:** 행이 지표, 열이 프로필이다.
- **케이스별 표:** 케이스마다 top-1 IoU 평균, 디코이에 속은 횟수, "못 찾음" 응답 횟수를 보여준다.

### 지표 정의

| 구분 | 지표 | 정의 |
|---|---|---|
| 정확도 | R@1 / R@K IoU≥θ (Recall@1, Recall@K) | 1순위(또는 K개 후보 중 하나, 기본 K=5)가 정답 구간 중 하나와 IoU≥θ인 질의 비율. θ = 0.3/0.5/0.7. 정답 있는 케이스(normal+decoy)만 |
| | mIoU@1 | 1순위와 정답 구간의 IoU 평균 (결과 없으면 0) |
| 경계 오차 | 시작/끝 오차 | 1순위가 정답과 겹친 경우, 가장 많이 겹친 정답 구간과의 시작·끝 시점 차이(초). 평균/중앙값 |
| 디코이 | R@1 IoU≥0.5 | 디코이 케이스에서 1순위가 정답을 맞힌 비율 |
| | 디코이 오인율@1 | 1순위가 디코이와 IoU≥0.3이고 정답보다 디코이에 더 많이 겹친 비율 |
| 없음 처리 | '못 찾음' 응답률 | 정답 없는 케이스에서 빈 결과를 돌려준 비율. 나머지는 지어낸 답 |
| 비용 | 질의당/합계 ($) | 응답에 찍힌 실제 사용량 × [config.py](config.py) 단가 (아래 참고) |
| | 토큰 | 질의당 입력·캐시 적중·도구 호출 입력·출력·thinking 토큰 평균 (Gemini). agentic은 모델이 불러온 영상 구간이 도구 호출 입력 토큰으로 잡힌다 |
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

## 긴 영상 관련 참고 (실측)

- **Gemini static 처리:** low 해상도에서 영상 1초에 약 91토큰이 든다. 20~44분 영상은 질의당 평균 약 18만 토큰, 2시간 17분 영상은 약 75만 토큰이었다.
  - 3.1 Pro는 프롬프트가 200K 토큰을 넘으면 비싼 단가가 적용된다(2시간 17분 영상은 질의당 약 $3).
  - `media_resolution: high`면 토큰이 약 3배라, 1시간이 넘는 영상은 컨텍스트 한도(1M)를 넘을 수 있다.
- **Gemini agentic 처리:** 모델이 불러온 영상 구간은 도구 호출 입력 토큰(`tool_use_prompt_token_count`)으로 잡힌다. 20~44분 영상에서는 static의 약 35% 토큰을 썼지만, 2시간 17분 영상 1건에서는 오히려 더 많이 썼다.
- **암시적 캐싱:** 같은 영상에 질의를 연달아 보내면 캐시 적중으로 입력 비용이 크게 줄 수 있다. 리포트는 캐시 적중 토큰을 캐시 단가로 따로 계산한다.
- **영상 화질:** 720p로 받는다. 이번 영상들은 120~840MB였고, Gemini File API 한도(파일당 2GB)를 넘으면 업로드 전에 에러로 알려준다. Gemini 토큰 수는 원본 화질이 아니라 `media_resolution`으로 정해진다.
- **TwelveLabs:** 처음 실행할 때 인덱싱 시간이 걸린다(20~30분 영상 기준 1~2분). 이 시간은 준비 시간으로 따로 잡히고, 이후 실행은 기존 인덱싱을 재사용한다.
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
