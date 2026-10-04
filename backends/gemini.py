"""Gemini 백엔드: 영상을 File API에 올리고, 쿼리에 해당하는 장면 구간을 구조화 출력으로 받는다."""
import enum
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

import config
from common import Moment, QueryResult, VideoSearchError, parse_timecode


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
- If nothing in the video clearly matches the description, return an empty matches list. Do not guess.
- Write reason in the same language as the scene description.
"""


def _log(msg: str) -> None:
    print(f"[gemini] {msg}", file=sys.stderr)


def make_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise VideoSearchError("GEMINI_API_KEY가 설정되지 않았습니다 (.env 확인).")
    return genai.Client(api_key=api_key)


def prepare(client: genai.Client, video_path: Path, profile: dict) -> tuple[types.File, dict]:
    if not video_path.is_file():
        raise VideoSearchError(f"영상 파일이 없습니다: {video_path}")
    size = video_path.stat().st_size
    if size > config.GEMINI_MAX_FILE_BYTES:
        raise VideoSearchError(
            f"파일이 너무 큽니다: {size / 1024**3:.2f}GB "
            f"(File API 한도 {config.GEMINI_MAX_FILE_BYTES / 1024**3:.0f}GB)"
        )

    _log(f"업로드: {video_path.name} ({size / 1024**2:.1f}MB)")
    file = client.files.upload(file=video_path)

    # 업로드 직후에는 PROCESSING 상태라 바로 쓸 수 없다. ACTIVE가 될 때까지 대기.
    deadline = time.monotonic() + config.PROCESSING_TIMEOUT_SEC
    while file.state == types.FileState.PROCESSING:
        if time.monotonic() > deadline:
            raise TimeoutError(f"영상 처리 대기 시간 초과 ({config.PROCESSING_TIMEOUT_SEC}s): {file.name}")
        time.sleep(5)
        file = client.files.get(name=file.name)

    if file.state != types.FileState.ACTIVE:
        raise RuntimeError(f"영상 처리 실패: state={file.state}, error={file.error}")
    _log(f"업로드 완료: {file.name}")
    return file, {"file": file.name, "size_bytes": size}


def cleanup(client: genai.Client, file: types.File) -> None:
    try:
        client.files.delete(name=file.name)
    except Exception as e:  # 정리 실패는 결과에 영향 없음 (48시간 후 자동 삭제)
        _log(f"업로드 파일 삭제 실패: {e}")


def _build_config(profile: dict) -> types.GenerateContentConfig:
    thinking_level = profile.get("thinking_level")
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SearchResult,
        media_resolution=f"MEDIA_RESOLUTION_{profile.get('media_resolution', 'low').upper()}",
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level.upper()) if thinking_level else None,
        http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT_SEC * 1000),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # 도구를 안 쓰므로 끈다
    )


def _parse(text: str | None, max_matches: int) -> tuple[list[Moment], list[str]]:
    """응답을 검증하고 쓸 수 있는 구간만 뽑는다. 형식 위반은 issues로 모은다."""
    if not text:
        return [], ["빈 응답"]
    try:
        result = SearchResult.model_validate_json(text)
    except ValidationError as e:
        return [], [f"JSON 스키마 불일치: {e.errors()[0]['msg']}"]

    issues = []
    if len(result.matches) > max_matches:
        issues.append(f"후보 수 초과 ({len(result.matches)} > {max_matches})")
    moments = []
    for m in result.matches[:max_matches]:
        try:
            start, end = parse_timecode(m.start), parse_timecode(m.end)
        except ValueError as e:
            issues.append(str(e))
            continue
        if m.start.count(":") != 2 or m.end.count(":") != 2:
            issues.append(f"HH:MM:SS 형식 아님 ({m.start} ~ {m.end})")
        if start > end:
            issues.append(f"start > end ({m.start} > {m.end})")
            start, end = end, start
        moments.append(Moment(start, end, m.confidence.value, m.reason))
    return moments, issues


def query(client: genai.Client, file: types.File, query: str, profile: dict, max_matches: int) -> QueryResult:
    video = types.Part(
        file_data=types.FileData(file_uri=file.uri, mime_type=file.mime_type),
        media_processing=profile["processing"].upper() if profile.get("processing") else None,
    )
    started = time.monotonic()
    response = client.models.generate_content(
        model=profile["model"],
        contents=[video, PROMPT.format(query=query, max_matches=max_matches)],
        config=_build_config(profile),
    )
    latency = time.monotonic() - started

    text = response.text
    moments, issues = _parse(text, max_matches)
    if not text and response.candidates:
        issues = [f"빈 응답 (finish_reason={response.candidates[0].finish_reason})"]
    usage = response.usage_metadata.model_dump(mode="json", exclude_none=True) if response.usage_metadata else {}
    return QueryResult(moments, latency, issues, text, usage, response.model_version)
