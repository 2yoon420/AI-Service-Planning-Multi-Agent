"""저장 경로 단일 관리 (2026-07-28, 배포 대비).

## 왜 필요한가

저장 경로가 전부 소스 트리 안에 하드코딩돼 있었다. 그중 `fact_store.db`는 **git에
추적까지 되고 있다**(`git ls-files`로 확인). 이 상태로 서버에 배포하면 다음이 일어난다.

    서버에서 git pull  →  fact_store.db가 저장소 버전으로 덮임  →  수집한 fact 소멸

CI/CD로 자동 배포하면 **배포할 때마다** 그렇게 된다. 조용히 일어나므로 알아채기도
어렵다 — 에러가 나지 않고 그냥 fact 수가 줄어 있을 뿐이다.

## 어떻게 푸는가

`DATA_DIR` 환경변수를 둔다.

- **설정하면** 모든 가변 데이터가 그 아래로 간다. 서버에서는 영구 디스크(/mnt/data)를
  가리키게 해 소스 트리와 데이터를 분리한다. git pull이 데이터를 건드릴 수 없다.
- **설정하지 않으면** 종전 경로 그대로다. 로컬 개발과 CLI 동작이 바뀌지 않는다.

## 실패를 흡수하지 않는 유일한 곳

이 파일은 이 프로젝트의 "실패를 흡수한다" 원칙을 **일부러 따르지 않는다.**
`DATA_DIR`이 설정됐는데 쓸 수 없으면 예외를 던진다. 조용히 종전 경로로 폴백하면
데이터가 소스 트리에 쌓이고, 그건 바로 위에서 막으려던 사고 그 자체이기 때문이다.
설정 오류는 시끄럽게 실패하는 편이 낫다.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path | None:
    """DATA_DIR 환경변수를 Path로. 미설정이면 None."""
    raw = os.getenv("DATA_DIR")
    if not raw or not raw.strip():
        return None
    return Path(raw.strip()).expanduser()


def data_path(name: str, fallback: Path) -> Path:
    """DATA_DIR이 있으면 그 아래 `name`, 없으면 `fallback`을 그대로 돌려준다.

    name은 파일명이거나 하위 디렉터리명일 수 있다(예: "fact_store.db", "outputs").
    """
    base = data_dir()
    if base is None:
        return fallback
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"DATA_DIR={base} 를 만들 수 없습니다({e}). 경로와 권한을 확인하세요. "
            f"소스 트리로 폴백하지 않는 이유는 paths.py 상단 주석을 참고하세요."
        ) from e
    if not os.access(base, os.W_OK):
        raise RuntimeError(
            f"DATA_DIR={base} 에 쓸 수 없습니다. 소유자/권한을 확인하세요."
        )
    return base / name
