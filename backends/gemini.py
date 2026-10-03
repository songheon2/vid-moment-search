"""Gemini 백엔드: 영상을 File API에 올리고, 쿼리에 해당하는 장면 구간을 구조화 출력으로 받는다."""
import enum
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

import config
from common import Moment, VideoSearchError, parse_timecode

DEFAULT_MODEL = config.GEMINI_MODEL


# ---- 모델 응답 스키마 (response_schema로 전달) ----

class Confidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Match(BaseModel):
    start: str = Field(description="Segment start timecode, HH:MM:SS")
    end: str = Field(description="Segment end timecode, HH:MM:SS")
    confidence: Confidence
    reason: str = Field(description="One sentence on why this segment matches")


class SearchResult(BaseModel):
    matches: list[Match]


PROMPT = """\
You are given a video and a description of a scene.
Find the segments of the video where the described scene appears.

Scene description: {query}

Rules:
- Timecodes are relative to the start of the video, formatted HH:MM:SS (zero-padded, e.g. 00:01:05).
- start must be <= end, and both must be within the video duration.
- Order matches from most to least likely. Return at most {max_matches} matches.
- If nothing in the video matches the description, return an empty matches list.
- Write reason in the same language as the scene description.
"""


# ---- API 호출 ----

def make_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise VideoSearchError("환경변수 GEMINI_API_KEY가 설정되지 않았습니다.")
    return genai.Client(api_key=api_key)


def upload_video(client: genai.Client, path: Path) -> types.File:
    if not path.is_file():
        raise VideoSearchError(f"영상 파일이 없습니다: {path}")
    size = path.stat().st_size
    if size > config.GEMINI_MAX_FILE_BYTES:
        raise VideoSearchError(
            f"파일이 너무 큽니다: {size / 1024**3:.2f}GB "
            f"(File API 한도 {config.GEMINI_MAX_FILE_BYTES / 1024**3:.0f}GB)"
        )

    print(f"[upload] {path.name} ({size / 1024**2:.1f}MB) 업로드 중...", file=sys.stderr)
    file = client.files.upload(file=path)

    # 업로드 직후에는 PROCESSING 상태라 바로 쓸 수 없다. ACTIVE가 될 때까지 대기.
    deadline = time.monotonic() + config.PROCESSING_TIMEOUT_SEC
    while file.state == types.FileState.PROCESSING:
        if time.monotonic() > deadline:
            raise TimeoutError(f"영상 처리 대기 시간 초과 ({config.PROCESSING_TIMEOUT_SEC}s): {file.name}")
        time.sleep(5)
        file = client.files.get(name=file.name)

    if file.state != types.FileState.ACTIVE:
        raise RuntimeError(f"영상 처리 실패: state={file.state}, error={file.error}")
    print(f"[upload] 완료: {file.name}", file=sys.stderr)
    return file


def search_moments(
    client: genai.Client,
    video_path: Path,
    query: str,
    model: str | None = None,
    max_matches: int = 5,
) -> list[Moment]:
    """영상 하나와 쿼리 하나로 장면 후보를 찾는다. 결과는 가능성 높은 순."""
    model = model or DEFAULT_MODEL
    file = upload_video(client, video_path)
    try:
        print(f"[query] {model} 호출 중... (timeout {config.REQUEST_TIMEOUT_SEC}s)", file=sys.stderr)
        response = client.models.generate_content(
            model=model,
            contents=[file, PROMPT.format(query=query, max_matches=max_matches)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SearchResult,
                http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT_SEC * 1000),
            ),
        )
    finally:
        try:
            client.files.delete(name=file.name)
        except Exception as e:  # 정리 실패는 결과에 영향 없음 (48시간 후 자동 삭제)
            print(f"[cleanup] 업로드 파일 삭제 실패: {e}", file=sys.stderr)

    result = response.parsed
    if result is None:
        if not response.text:
            reason = response.candidates[0].finish_reason if response.candidates else response.prompt_feedback
            raise RuntimeError(f"모델 응답이 비었습니다: {reason}")
        result = SearchResult.model_validate_json(response.text)

    moments = []
    for m in result.matches:
        start, end = sorted((parse_timecode(m.start), parse_timecode(m.end)))
        moments.append(Moment(start, end, m.confidence.value, m.reason))
    return moments
