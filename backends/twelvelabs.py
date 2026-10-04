"""TwelveLabs 백엔드: 영상을 Marengo 인덱스에 올리고 텍스트 쿼리로 클립을 검색한다.

TwelveLabs는 검색 전에 인덱싱이 필수라서 Gemini처럼 매번 올렸다 지우지 않는다.
- 인덱스는 "<prefix>-<모델>" 이름으로 하나 만들어 계속 재사용한다.
- 같은 영상(파일명+크기)이 이미 인덱싱돼 있으면 다시 올리지 않고 바로 검색한다.
"""
import itertools
import json
import os
import sys
import time
from pathlib import Path

from twelvelabs import TwelveLabs

import config
from common import Moment, QueryResult, VideoSearchError

POLL_SEC = 10


def make_client() -> TwelveLabs:
    api_key = os.environ.get("TWELVE_LABS_API_KEY")
    if not api_key:
        raise VideoSearchError("TWELVE_LABS_API_KEY가 설정되지 않았습니다 (.env 확인).")
    return TwelveLabs(api_key=api_key)


def _log(msg: str) -> None:
    print(f"[twelvelabs] {msg}", file=sys.stderr)


def get_or_create_index(client: TwelveLabs, model: str) -> str:
    name = f"{config.TL_INDEX_PREFIX}-{model}".replace(".", "-")
    for index in client.indexes.list(index_name=name):
        if index.index_name == name:
            return index.id
    _log(f"인덱스 생성: {name}")
    created = client.indexes.create(
        index_name=name,
        models=[{"model_name": model, "model_options": config.TL_MODEL_OPTIONS}],
    )
    return created.id


def _source_key(path: Path) -> str:
    """같은 영상인지 판별하는 키. 파일명과 바이트 크기로 충분하다고 본다."""
    return f"{path.name}|{path.stat().st_size}"


def _find_indexed(client: TwelveLabs, index_id: str, path: Path) -> str | None:
    """이 영상이 이미 인덱스에 있으면 indexed asset id를 돌려준다 (인덱싱 진행 중 포함)."""
    key = _source_key(path)
    # SDK의 user_metadata 필터는 서버가 거부하는 형식으로 보내져서(400) 파일명으로 좁히고 메타데이터는 직접 확인한다.
    for item in client.indexes.indexed_assets.list(index_id, filename=path.name):
        if item.status == "failed":
            continue
        detail = client.indexes.indexed_assets.retrieve(index_id, item.id)
        if (detail.user_metadata or {}).get("vms_key") == key:
            return item.id
    return None


def _upload_asset(client: TwelveLabs, path: Path) -> str:
    size = path.stat().st_size
    _log(f"업로드: {path.name} ({size / 1024**2:.1f}MB)")
    if size <= config.TL_DIRECT_UPLOAD_MAX_BYTES:
        with path.open("rb") as f:
            asset = client.assets.create(
                method="direct", file=f, filename=path.name,
                request_options={"timeout_in_seconds": config.REQUEST_TIMEOUT_SEC},
            )
        asset_id = asset.id
    else:
        result = client.multipart_upload.upload_file(
            path, filename=path.name,
            progress_callback=lambda p: _log(f"업로드 {p.percentage:.0f}%"),
        )
        asset_id = result.asset_id

    # 업로드 직후에는 processing 상태. ready가 될 때까지 대기.
    deadline = time.monotonic() + config.PROCESSING_TIMEOUT_SEC
    while True:
        asset = client.assets.retrieve(asset_id)
        if asset.status == "ready":
            return asset_id
        if asset.status == "failed":
            raise RuntimeError(f"업로드 처리 실패: {getattr(asset, 'error', None)}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"업로드 처리 대기 시간 초과 ({config.PROCESSING_TIMEOUT_SEC}s): {asset_id}")
        time.sleep(POLL_SEC)


def _wait_indexed(client: TwelveLabs, index_id: str, indexed_id: str) -> None:
    deadline = time.monotonic() + config.TL_INDEXING_TIMEOUT_SEC
    last_status = None
    while True:
        status = client.indexes.indexed_assets.retrieve(index_id, indexed_id).status
        if status != last_status:
            _log(f"인덱싱 상태: {status}")
            last_status = status
        if status == "ready":
            return
        if status == "failed":
            raise RuntimeError(f"인덱싱 실패: {indexed_id}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"인덱싱 대기 시간 초과 ({config.TL_INDEXING_TIMEOUT_SEC}s): {indexed_id}")
        time.sleep(POLL_SEC)


def ensure_indexed(client: TwelveLabs, index_id: str, path: Path) -> tuple[str, bool]:
    """영상을 인덱스에 올리고(이미 있으면 재사용) 인덱싱이 끝난 indexed asset id와 재사용 여부를 돌려준다."""
    key = _source_key(path)
    indexed_id = _find_indexed(client, index_id, path)
    reused = indexed_id is not None
    if reused:
        _log(f"기존 인덱싱 재사용: {indexed_id}")
    else:
        asset_id = _upload_asset(client, path)
        indexed_id = client.indexes.indexed_assets.create(
            index_id, asset_id=asset_id, user_metadata={"vms_key": key},
        ).id
        _log(f"인덱싱 시작: {indexed_id}")
    _wait_indexed(client, index_id, indexed_id)
    return indexed_id, reused


def prepare(client: TwelveLabs, video_path: Path, profile: dict) -> tuple[tuple[str, str], dict]:
    if not video_path.is_file():
        raise VideoSearchError(f"영상 파일이 없습니다: {video_path}")
    size = video_path.stat().st_size
    if size > config.TL_MAX_FILE_BYTES:
        raise VideoSearchError(
            f"파일이 너무 큽니다: {size / 1024**3:.2f}GB "
            f"(Marengo 한도 {config.TL_MAX_FILE_BYTES / 1024**3:.0f}GB)"
        )

    index_id = get_or_create_index(client, profile["model"])
    video_id, reused = ensure_indexed(client, index_id, video_path)
    meta = client.indexes.indexed_assets.retrieve(index_id, video_id).system_metadata
    info = {
        "index_id": index_id,
        "video_id": video_id,
        "reused": reused,  # True면 이번 실행에서 인덱싱 비용이 들지 않았음
        "duration_sec": meta.duration if meta else None,
    }
    return (index_id, video_id), info


def cleanup(client: TwelveLabs, handle: tuple[str, str]) -> None:
    """인덱스와 영상은 재사용하므로 지우지 않는다."""


def query(client: TwelveLabs, handle: tuple[str, str], query: str, profile: dict, max_matches: int) -> QueryResult:
    index_id, video_id = handle
    started = time.monotonic()
    pager = client.search.query(
        index_id=index_id,
        query_text=query,
        search_options=config.TL_SEARCH_OPTIONS,
        filter=json.dumps({"id": [video_id]}),  # 인덱스의 다른 영상은 제외
        group_by="clip",
        page_limit=min(max_matches, 50),
        request_options={"timeout_in_seconds": config.REQUEST_TIMEOUT_SEC},
    )
    clips = list(itertools.islice(pager, max_matches))
    latency = time.monotonic() - started
    # 결과는 이미 rank 순. Marengo는 신뢰도 점수를 주지 않고, 구조화된 API라 형식 위반이 없다.
    moments = [Moment(c.start, c.end) for c in clips]
    raw = json.dumps([{"start": c.start, "end": c.end, "rank": c.rank} for c in clips])
    return QueryResult(moments, latency, raw_text=raw, usage={"search_queries": 1})
