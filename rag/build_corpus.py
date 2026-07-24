"""
RAG 최소 코퍼스 적재 (TTA 4건 + NCS 9건)

절차: PDF -> (parse_documents.py) markdown -> 청크 분할 -> Upstage 임베딩
(solar-embedding-2-passage) -> Chroma persistent DB에 저장

주의: 이 스크립트를 실행하면 Upstage Document Parse(페이지당 과금)와
Embeddings API 크레딧이 소모됩니다. 처음 실행 시 파일 개수가 많으니
1개 파일로 먼저 테스트해보고 전체를 돌리는 것을 권장합니다.
"""

import os
import re
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

from rag.parse_documents import parse_pdf_to_markdown

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # multi-agent-system의 상위 = 프로젝트 폴더
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "tta_ncs_corpus"

CHUNK_SIZE = 800   # 문자 기준 (한국어 특성상 토큰보다 문자 기준이 다루기 쉬움)
CHUNK_OVERLAP = 100

# 청크의 '내용 밀도' 최소 기준. 목차(TOC) 페이지는 점선·페이지번호가 대부분이라
# 실제 한글/영문/숫자 비율이 낮다. 이 비율보다 낮으면 노이즈로 간주해 버린다.
MIN_ALNUM_RATIO = 0.4

# 목차에서 흔한 점선 리더(dot leader) 패턴: "제목 ······· 21" 같은 형태
DOT_LEADER_PATTERN = re.compile(r"[·.…]{3,}")
# 줄 전체가 숫자(페이지 번호)만 있는 경우
PAGE_NUMBER_LINE_PATTERN = re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE)

SOURCE_DOCS = {
    "TTA": PROJECT_ROOT / "tta",
    "NCS": PROJECT_ROOT / "NCS",
}


def get_upstage_client() -> OpenAI:
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없습니다.")
    return OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")


def clean_markdown(text: str) -> str:
    """목차(TOC) 페이지의 점선 리더·페이지번호 줄을 제거해 청크 품질을 높인다."""
    text = DOT_LEADER_PATTERN.sub(" ", text)
    text = PAGE_NUMBER_LINE_PATTERN.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)  # 빈 줄이 여러 개면 2개로 축소
    return text


def _content_density(text: str) -> float:
    """텍스트 중 한글/영문/숫자가 차지하는 비율. 목차 잔여물처럼 기호·공백만
    남은 청크를 걸러내기 위한 지표."""
    if not text:
        return 0.0
    alnum = len(re.findall(r"[가-힣a-zA-Z0-9]", text))
    return alnum / len(text)


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = clean_markdown(text)
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    # strip 후 빈 청크 제거 + 내용 밀도가 너무 낮은(목차 잔여물) 청크 제거
    cleaned = [c.strip() for c in chunks if c.strip()]
    return [c for c in cleaned if _content_density(c) >= MIN_ALNUM_RATIO]


EMBED_BATCH_SIZE = 80  # Upstage 제한(요청당 최대 100개 문자열)보다 여유를 두고 잡음


def embed_passages(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Upstage 임베딩 API는 요청당 최대 100개 문자열까지만 허용하므로,
    청크가 많은(대용량) 문서는 여러 번에 나눠서 호출한다."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        response = client.embeddings.create(input=batch, model="solar-embedding-2-passage")
        all_embeddings.extend(d.embedding for d in response.data)
    return all_embeddings


def build_corpus(doc_type: str, folder: Path, client: OpenAI, collection) -> int:
    pdf_files = sorted(folder.glob("*.pdf"))
    total_chunks = 0
    for pdf_path in pdf_files:
        print(f"[{doc_type}] 처리 중: {pdf_path.name}")
        markdown = parse_pdf_to_markdown(pdf_path)
        chunks = chunk_text(markdown)
        if not chunks:
            continue

        if len(chunks) > EMBED_BATCH_SIZE:
            print(f"  청크 {len(chunks)}개 -> {EMBED_BATCH_SIZE}개씩 나눠서 임베딩")

        embeddings = embed_passages(client, chunks)
        ids = [f"{doc_type}_{pdf_path.stem}_{i}" for i in range(len(chunks))]
        metadatas = [
            {"doc_type": doc_type, "source_file": pdf_path.name, "chunk_index": i}
            for i in range(len(chunks))
        ]
        collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        total_chunks += len(chunks)
        print(f"  -> {len(chunks)}개 청크 저장")
    return total_chunks


def main(only: str = None, reset: bool = False):
    """
    only: 'TTA' 또는 'NCS'만 처리하고 싶을 때 지정 (테스트용)
    reset: True면 기존 컬렉션을 지우고 새로 만든다. 청크 분할 로직(clean_markdown 등)을
           바꾼 뒤에는 예전 청크가 새 청크와 섞여 남아있을 수 있으므로 reset=True로 재실행 권장.
           (parse_documents.py의 캐시는 그대로 재사용되므로 Document Parse 비용은 다시 들지 않음)
    """
    client = get_upstage_client()
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if reset:
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            print(f"기존 컬렉션 '{COLLECTION_NAME}' 삭제 완료 — 새로 적재합니다.")
        except Exception:
            pass  # 컬렉션이 원래 없었으면 무시
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

    total = 0
    for doc_type, folder in SOURCE_DOCS.items():
        if only and doc_type != only:
            continue
        if not folder.exists():
            print(f"경고: {folder} 폴더가 없습니다. 건너뜁니다.")
            continue
        total += build_corpus(doc_type, folder, client, collection)

    print(f"\n총 {total}개 청크가 '{COLLECTION_NAME}' 컬렉션에 저장되었습니다.")
    print(f"저장 위치: {CHROMA_DIR}")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    reset_flag = "--reset" in args
    args = [a for a in args if a != "--reset"]
    only_arg = args[0] if args else None
    main(only=only_arg, reset=reset_flag)
