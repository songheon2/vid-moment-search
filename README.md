# vid-moment-search

로컬 영상 파일과 자연어 쿼리(찾을 장면 묘사)를 받아, 해당 장면의 타임코드를 찾는 테스트용 도구.
백엔드 두 가지를 같은 CLI·평가 스크립트로 비교할 수 있다.

| 백엔드 | 방식 |
|---|---|
| `gemini` (기본) | 영상을 Gemini File API에 그대로 올리고, 구조화 출력(JSON 스키마)으로 구간 후보를 받는다. 끝나면 업로드 파일 삭제. |
| `twelvelabs` | 영상을 TwelveLabs Marengo 인덱스에 올리고 텍스트 검색으로 클립을 받는다. 인덱스와 인덱싱된 영상은 재사용한다. |

별도 DB나 전처리(샷 경계 검출, 프레임 추출)는 없다.

## 설치

```bash
conda activate vid-moment-search   # 없으면: conda create -n vid-moment-search python=3.12 -y
pip install -r requirements.txt
```

## API 키 설정

| 백엔드 | 환경변수 | 발급 |
|---|---|---|
| gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |
| twelvelabs | `TWELVE_LABS_API_KEY` | [TwelveLabs Playground](https://playground.twelvelabs.io/) → API Keys |

```powershell
# PowerShell (현재 세션)
$env:GEMINI_API_KEY = "발급받은_키"
$env:TWELVE_LABS_API_KEY = "발급받은_키"

# PowerShell (영구 저장, 새 터미널부터 적용)
setx TWELVE_LABS_API_KEY "발급받은_키"
```

```bash
# bash
export TWELVE_LABS_API_KEY="발급받은_키"
```

## 단일 검색

```bash
python search.py <영상 경로> "<찾을 장면 묘사>" [--backend gemini|twelvelabs]
python search.py videos/sample.mp4 "빨간 우산을 든 여자가 횡단보도를 건너는 장면"
python search.py videos/sample.mp4 "빨간 우산을 든 여자가 횡단보도를 건너는 장면" --backend twelvelabs
```

출력 예 (gemini):

```
백엔드: gemini / 모델: gemini-3.1-pro-preview
쿼리: 빨간 우산을 든 여자가 횡단보도를 건너는 장면

1. 15:23 ~ 15:28  [high]  빨간 우산을 든 여성이 횡단보도를 건넌다.
2. 41:02 ~ 41:05  [low]   우산은 보이지만 색이 분명하지 않다.
```

twelvelabs는 신뢰도·근거 없이 타임코드만 rank 순으로 나온다.
타임코드는 1시간 미만이면 `mm:ss`, 이상이면 `hh:mm:ss`. 후보는 가능성 높은 순서다.
옵션: `--model <모델 ID>`, `--max-matches <N>` (기본 5).

## 일괄 평가

1. `testsets/template.json`을 복사해 케이스를 채운다. (`gt_start`/`gt_end`는 초 단위, 영상 경로가 상대경로면 JSON 파일 위치 기준)
2. 실행:

```bash
python evaluate.py testsets/my_testset.json                        # gemini
python evaluate.py testsets/my_testset.json --backend twelvelabs
```

케이스별로 아래 값을 표로 출력하고, 마지막에 평균을 낸다. pass/fail 판정은 하지 않는다.

| 컬럼 | 의미 |
|---|---|
| IoU@1 | 1순위 후보와 정답 구간의 IoU |
| best IoU | 모든 후보 중 최고 IoU |
| #cand | 모델이 돌려준 후보 수 (0이면 IoU는 0) |
| sec | 업로드(+인덱싱) + 검색 소요 시간 |

정답이 비어 있거나 영상이 없는 케이스는 `SKIP`, API 오류는 `ERROR`로 표시되고 평균에서 빠진다.
템플릿을 그대로 실행하면 API 호출 없이 전부 `SKIP`으로 나온다.

## TwelveLabs 동작 방식

TwelveLabs는 검색 전에 인덱싱이 필수라 Gemini처럼 매번 올렸다 지우지 않는다.

- 인덱스 `vid-moment-search-marengo3-0`을 처음 실행 때 만들고 이후 계속 재사용한다.
- 영상은 파일명+크기를 키로 인덱스에 기록해 두고, 같은 영상이면 다시 올리지 않고 바로 검색한다.
  그래서 같은 영상에 대한 첫 검색만 느리고(업로드+인덱싱, 영상 길이에 따라 수 분~수십 분), 이후는 몇 초다.
  평가 표의 `sec`도 첫 케이스에만 인덱싱 시간이 포함된다.
- 검색은 그 영상으로만 범위를 제한한다 (인덱스에 다른 영상이 있어도 섞이지 않음).
- 200MB 이하는 단일 업로드, 그보다 크면 multipart 업로드. 파일은 4GB, 길이는 4초~4시간까지 (Marengo 3.0 제한).
- 인덱스·영상 삭제는 [Playground](https://playground.twelvelabs.io/)에서 한다. 인덱싱된 영상 시간은 요금·한도에 포함된다.
- Marengo는 짧은 클립 단위로 결과를 주기 때문에, 정답 구간이 길면 1순위 클립의 IoU가 낮게 나올 수 있다.

## 설정

모든 값은 [config.py](config.py)에 있고 환경변수로 덮어쓸 수 있다. CLI의 `--model`이 가장 우선한다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `VMS_GEMINI_MODEL` | `gemini-3.1-pro-preview` | Gemini 모델 ID |
| `VMS_TL_MODEL` | `marengo3.0` | TwelveLabs 인덱스 모델 |
| `VMS_TL_INDEX_PREFIX` | `vid-moment-search` | TwelveLabs 인덱스 이름 앞부분 |
| `VMS_TIMEOUT_SEC` | `300` | 추론/검색 요청 타임아웃(초) |
| `VMS_PROCESSING_TIMEOUT_SEC` | `600` | 업로드 후 서버 측 영상 처리 대기 한도(초) |
| `VMS_TL_INDEXING_TIMEOUT_SEC` | `3600` | TwelveLabs 인덱싱 대기 한도(초) |

Gemini 모델 ID는 preview라 바뀔 수 있다. 최신 이름은 [Gemini 모델 문서](https://ai.google.dev/gemini-api/docs/models)에서 확인.
다른 Gemini 모델(예: `gemini-3-flash-preview`)은 모델 ID만 바꾸면 된다.

다른 서비스(Qwen3-VL-Plus 등)를 추가하려면 [backends/](backends/)에 모듈을 하나 만들고
`DEFAULT_MODEL`, `make_client()`, `search_moments()`를 구현한 뒤 [backends/\_\_init\_\_.py](backends/__init__.py)의 `NAMES`에 이름을 추가한다.

## 제약

- Gemini File API는 파일당 최대 2GB. 넘으면 업로드 전에 에러로 중단한다 (자동 압축·분할 없음).
- Gemini는 기본적으로 영상을 초당 1프레임으로 샘플링하므로, 타임코드 정밀도는 대략 1초 단위다.
- Gemini에 업로드한 파일은 검색이 끝나면 바로 삭제한다 (삭제에 실패해도 48시간 후 자동 삭제).
