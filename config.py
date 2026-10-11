"""실행 설정. 값은 환경변수(또는 프로젝트 루트의 .env)로 덮어쓸 수 있다.

비교할 모델·모드 조합은 profiles.json에 있다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent

# API 키 등을 .env에서 읽는다. 이미 설정된 환경변수가 있으면 그쪽이 우선.
load_dotenv(ROOT / ".env")

PROFILES_PATH = ROOT / "profiles.json"
DEFAULT_PROFILE = os.environ.get("VMS_PROFILE", "gemini-3.1-pro")
RESULTS_DIR = ROOT / "results"

# 질의 1회의 타임아웃(초). 1시간 영상 + thinking은 수 분 걸릴 수 있다.
REQUEST_TIMEOUT_SEC = int(os.environ.get("VMS_TIMEOUT_SEC", "600"))

# 업로드 후 서버 측 영상 처리를 기다리는 최대 시간(초).
PROCESSING_TIMEOUT_SEC = int(os.environ.get("VMS_PROCESSING_TIMEOUT_SEC", "600"))

# ---- Gemini ----

# File API 파일당 최대 크기.
GEMINI_MAX_FILE_BYTES = 2 * 1024**3

# agentic 영상 처리(processing: agentic)를 지원하는 모델. 나머지는 static만 가능.
# https://ai.google.dev/gemini-api/docs/video-understanding
GEMINI_AGENTIC_MODELS = {"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"}

# 비용 계산용 단가 (USD / 1M tokens). 응답에 찍힌 실제 토큰 수에 곱한다.
# 2026-10-03 https://ai.google.dev/gemini-api/docs/pricing 기준 — 쓰기 전에 페이지에서 다시 확인할 것.
# input_audio가 없으면 input과 같은 단가. long_*은 프롬프트가 long_threshold 토큰을 넘을 때 적용.
GEMINI_PRICING = {
    "gemini-3.1-pro-preview": {
        "input": 2.00, "output": 12.00, "cached": 0.20,
        "long_threshold": 200_000, "input_long": 4.00, "output_long": 18.00, "cached_long": 0.40,
    },
    "gemini-3-flash-preview": {"input": 0.50, "input_audio": 1.00, "output": 3.00, "cached": 0.05},
    # 3.8/3.7/3.6 Flash는 2027-01-01부터 단가가 2배가 된다.
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50, "cached": 0.03},
    "gemini-3.1-flash-lite": {"input": 0.25, "input_audio": 0.50, "output": 1.50, "cached": 0.025},
}

# ---- TwelveLabs ----

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

# 비용 계산용 단가 (USD). 2026-10-03 https://www.twelvelabs.io/pricing (Developer 플랜) 기준.
TL_PRICING = {"index_per_hour": 2.50, "search_per_query": 4 / 1000}
