"""검색 백엔드. 각 모듈은 아래 세 가지를 제공한다.

- DEFAULT_MODEL: str
- make_client() -> 클라이언트
- search_moments(client, video_path, query, model, max_matches) -> list[Moment] (가능성 높은 순)
"""
import importlib

NAMES = ["gemini", "twelvelabs"]


def get_backend(name: str):
    if name not in NAMES:
        raise ValueError(f"알 수 없는 백엔드: {name} (가능: {', '.join(NAMES)})")
    # 쓰지 않는 백엔드의 SDK는 import하지 않도록 지연 로드
    return importlib.import_module(f"backends.{name}")
