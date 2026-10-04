"""검색 백엔드와 프로필.

각 백엔드 모듈이 제공하는 것:
- make_client() -> 클라이언트
- prepare(client, video_path, profile) -> (handle, info)   영상 업로드/인덱싱. info는 기록용 dict
- query(client, handle, query, profile, max_matches) -> QueryResult
- cleanup(client, handle) -> None                         prepare로 만든 임시 자원 정리
"""
import importlib
import json

import config
from common import VideoSearchError

NAMES = ["gemini", "twelvelabs"]


def get_backend(name: str):
    if name not in NAMES:
        raise VideoSearchError(f"알 수 없는 백엔드: {name} (가능: {', '.join(NAMES)})")
    # 쓰지 않는 백엔드의 SDK는 import하지 않도록 지연 로드
    return importlib.import_module(f"backends.{name}")


def load_profiles() -> dict[str, dict]:
    data = json.loads(config.PROFILES_PATH.read_text(encoding="utf-8"))
    return {name: p for name, p in data.items() if not name.startswith("_")}


def get_profile(name: str) -> dict:
    profiles = load_profiles()
    if name not in profiles:
        raise VideoSearchError(f"프로필 없음: {name} (profiles.json에 있는 것: {', '.join(profiles)})")
    profile = profiles[name]
    for key in ("backend", "model"):
        if key not in profile:
            raise VideoSearchError(f"프로필 {name}에 {key}가 없습니다.")
    if profile.get("processing") == "agentic" and profile["model"] not in config.GEMINI_AGENTIC_MODELS:
        raise VideoSearchError(
            f"프로필 {name}: {profile['model']}은 agentic 처리를 지원하지 않습니다 "
            f"(지원: {', '.join(sorted(config.GEMINI_AGENTIC_MODELS))})"
        )
    return profile
