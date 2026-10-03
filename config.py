"""실행 설정. 모든 값은 환경변수로 덮어쓸 수 있다."""
import os

# ---- Gemini ----

# 사용할 모델 ID. preview 모델은 이름이 바뀔 수 있으니 아래 문서에서 확인할 것.
# https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = os.environ.get("VMS_GEMINI_MODEL", "gemini-3.1-pro-preview")

# generate_content 요청 하나의 타임아웃(초). 긴 영상은 응답이 오래 걸린다.
REQUEST_TIMEOUT_SEC = int(os.environ.get("VMS_TIMEOUT_SEC", "300"))

# 업로드 후 서버 측 영상 처리(PROCESSING -> ACTIVE)를 기다리는 최대 시간(초).
PROCESSING_TIMEOUT_SEC = int(os.environ.get("VMS_PROCESSING_TIMEOUT_SEC", "600"))

# Gemini File API 파일당 최대 크기.
GEMINI_MAX_FILE_BYTES = 2 * 1024**3

# ---- TwelveLabs ----

# 인덱스 모델. 검색용은 Marengo 3.0. https://docs.twelvelabs.io/v1.3/docs/concepts/models/marengo
TL_MODEL = os.environ.get("VMS_TL_MODEL", "marengo3.0")

# 인덱스 이름 앞부분. 실제 이름은 "<prefix>-<모델>"이라 모델을 바꾸면 인덱스도 따로 생긴다.
TL_INDEX_PREFIX = os.environ.get("VMS_TL_INDEX_PREFIX", "vid-moment-search")

# 인덱싱 대상과 검색 대상 모달리티.
TL_MODEL_OPTIONS = ["visual", "audio"]
TL_SEARCH_OPTIONS = ["visual", "audio"]

# 영상 인덱싱 완료를 기다리는 최대 시간(초). 긴 영상은 수십 분 걸릴 수 있다.
TL_INDEXING_TIMEOUT_SEC = int(os.environ.get("VMS_TL_INDEXING_TIMEOUT_SEC", "3600"))

# 업로드 크기 한도: 200MB까지는 단일 업로드, 그 이상은 multipart. Marengo 3.0 파일 한도는 4GB.
TL_DIRECT_UPLOAD_MAX_BYTES = 200 * 1024**2
TL_MAX_FILE_BYTES = 4 * 1024**3
