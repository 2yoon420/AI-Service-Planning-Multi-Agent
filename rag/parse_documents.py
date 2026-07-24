"""
Upstage Document Parse를 이용해 PDF -> Markdown 변환

한 번 파싱한 결과는 rag/parsed/ 폴더에 캐시해서, 같은 파일을 다시 돌릴 때
API 크레딧을 중복 소모하지 않도록 한다.
"""

import hashlib
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
PARSE_URL = "https://api.upstage.ai/v1/document-digitization"
ASYNC_SUBMIT_URL = "https://api.upstage.ai/v1/document-digitization/async"
ASYNC_STATUS_URL = "https://api.upstage.ai/v1/document-digitization/requests/{request_id}"
PARSED_DIR = Path(__file__).parent / "parsed"
PARSED_DIR.mkdir(exist_ok=True)


def _cache_path(pdf_path: Path) -> Path:
    """파일 내용 해시를 캐시 키로 사용 (파일명이 바뀌어도 내용이 같으면 재사용)"""
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    return PARSED_DIR / f"{pdf_path.stem}_{file_hash}.md"


def _parse_sync(pdf_path: Path) -> requests.Response:
    with open(pdf_path, "rb") as f:
        return requests.post(
            PARSE_URL,
            headers={"Authorization": f"Bearer {UPSTAGE_API_KEY}"},
            files={"document": f},
            data={"model": "document-parse", "output_formats": "['markdown']", "ocr": "auto"},
            timeout=180,
        )


def _parse_async(pdf_path: Path, poll_interval: int = 5, max_wait: int = 900) -> str:
    """
    대용량 문서(413 등으로 sync 처리가 안 되는 경우) 전용 비동기 엔드포인트.
    작업을 제출하고, 완료될 때까지 poll_interval초마다 상태를 확인한 뒤,
    페이지 구간별 배치를 순서대로 이어붙여 전체 markdown을 만든다.
    """
    print(f"  -> 413(용량 초과)으로 async 엔드포인트로 재시도: {pdf_path.name}")
    with open(pdf_path, "rb") as f:
        submit = requests.post(
            ASYNC_SUBMIT_URL,
            headers={"Authorization": f"Bearer {UPSTAGE_API_KEY}"},
            files={"document": f},
            data={"model": "document-parse", "output_formats": "['markdown']", "ocr": "auto"},
            timeout=180,
        )
    submit.raise_for_status()
    request_id = submit.json()["request_id"]

    waited = 0
    while waited < max_wait:
        status_resp = requests.get(
            ASYNC_STATUS_URL.format(request_id=request_id),
            headers={"Authorization": f"Bearer {UPSTAGE_API_KEY}"},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json()

        if status["status"] == "completed":
            batches = sorted(status["batches"], key=lambda b: b["id"])
            markdown_parts = []
            for batch in batches:
                batch_result = requests.get(batch["download_url"], timeout=60).json()
                markdown_parts.append(batch_result["content"]["markdown"])
            return "\n\n".join(markdown_parts)

        if status["status"] == "failed":
            raise RuntimeError(f"Upstage async 파싱 실패: {status.get('failure_message')}")

        print(f"    ...처리 중 (status={status['status']}, {waited}초 경과)")
        time.sleep(poll_interval)
        waited += poll_interval

    raise TimeoutError(f"{pdf_path.name} async 파싱이 {max_wait}초 내에 끝나지 않았습니다.")


def parse_pdf_to_markdown(pdf_path: Path, force: bool = False) -> str:
    """PDF 파일 하나를 Upstage Document Parse로 markdown 변환. 캐시가 있으면 재사용.
    파일이 너무 크면(413) 자동으로 async 엔드포인트로 재시도한다."""
    cache_file = _cache_path(pdf_path)
    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8")

    if not UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 설정되어 있지 않습니다.")

    response = _parse_sync(pdf_path)

    if response.status_code == 413:
        markdown = _parse_async(pdf_path)
        pages = "? (async)"
    else:
        response.raise_for_status()
        result = response.json()
        markdown = result["content"]["markdown"]
        pages = result.get("usage", {}).get("pages", "?")

    cache_file.write_text(markdown, encoding="utf-8")
    print(f"  파싱 완료: {pdf_path.name} ({pages}페이지) -> {cache_file.name}")
    return markdown


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not target:
        print("사용법: python parse_documents.py <PDF 경로>")
        sys.exit(1)

    md = parse_pdf_to_markdown(target)
    print(f"\n--- 변환 결과 미리보기 (앞 500자) ---\n{md[:500]}")
