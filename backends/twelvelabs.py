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
from common import Moment, VideoSearchError

DEFAULT_MODEL = config.TL_MODEL
POLL_SEC = 10


def make_client() -> TwelveLabs:
    api_key = os.environ.get("TWELVE_LABS_API_KEY")
    if not api_key:
        raise VideoSearchError("환경변수 TWELVE_LABS_API_KEY가 설정되지 않았습니다.")
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


def _find_indexed(client: TwelveLabs, index_id: str, key: str) -> str | None:
    """이 영상이 이미 인덱스에 있으면 indexed asset id를 돌려준다 (인덱싱 진행 중 포함)."""
    for item in client.indexes.indexed_assets.list(index_id, user_metadata={"vms_key": key}):
        if item.status == "failed":
            continue
        # 서버 필터를 그대로 믿지 않고 메타데이터를 직접 확인
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


def ensure_indexed(client: TwelveLabs, index_id: str, path: Path) -> str:
    """영상을 인덱스에 올리고(이미 있으면 재사용) 인덱싱이 끝난 indexed asset id를 돌려준다."""
    key = _source_key(path)
    indexed_id = _find_indexed(client, index_id, key)
    if indexed_id:
        _log(f"기존 인덱싱 재사용: {indexed_id}")
    else:
        asset_id = _upload_asset(client, path)
        indexed_id = client.indexes.indexed_assets.create(
            index_id, asset_id=asset_id, user_metadata={"vms_key": key},
        ).id
        _log(f"인덱싱 시작: {indexed_id}")
    _wait_indexed(client, index_id, indexed_id)
    return indexed_id


def search_moments(
    client: TwelveLabs,
    video_path: Path,
    query: str,
    model: str | None = None,
    max_matches: int = 5,
) -> list[Moment]:
    """영상 하나와 쿼리 하나로 장면 후보를 찾는다. 결과는 rank 순."""
    model = model or DEFAULT_MODEL
    if not video_path.is_file():
        raise VideoSearchError(f"영상 파일이 없습니다: {video_path}")
    size = video_path.stat().st_size
    if size > config.TL_MAX_FILE_BYTES:
        raise VideoSearchError(
            f"파일이 너무 큽니다: {size / 1024**3:.2f}GB "
            f"(Marengo 한도 {config.TL_MAX_FILE_BYTES / 1024**3:.0f}GB)"
        )

    index_id = get_or_create_index(client, model)
    video_id = ensure_indexed(client, index_id, video_path)

    _log(f"검색: {query}")
    pager = client.search.query(
        index_id=index_id,
        query_text=query,
        search_options=config.TL_SEARCH_OPTIONS,
        filter=json.dumps({"id": [video_id]}),  # 인덱스의 다른 영상은 제외
        group_by="clip",
        page_limit=min(max_matches, 50),
        request_options={"timeout_in_seconds": config.REQUEST_TIMEOUT_SEC},
    )
    # 결과는 이미 rank 순. Marengo는 신뢰도 점수를 주지 않는다.
    return [Moment(c.start, c.end) for c in itertools.islice(pager, max_matches)]
