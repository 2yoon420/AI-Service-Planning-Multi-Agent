"""테스트 전역 설정.

agents/* 모듈이 임포트 시점에 환경변수를 읽는 경우가 있어, 어떤 테스트 모듈보다
먼저 더미 값을 심어둔다. 실제 API는 호출하지 않는다(모든 테스트가 mock 기반)."""

import os

os.environ.setdefault("UPSTAGE_API_KEY", "test-dummy-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-dummy-key")
os.environ.setdefault("HEAVY_MODEL", "test-heavy")
os.environ.setdefault("LIGHT_MODEL", "test-light")
