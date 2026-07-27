"""
RAG 코퍼스 검색

검증·출처 에이전트(및 다른 에이전트)가 "이 메타데이터 스키마의 근거가 뭐지?"
같은 질문을 할 때, TTA/NCS 코퍼스에서 관련 청크를 찾아오는 함수.
"""

import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "tta_ncs_corpus"

# 2026-07-24 추가: capability_corpus 전용 컬렉션 이름. build_corpus.py의
# CAPABILITY_COLLECTION_NAME과 동일한 값이어야 한다(build/search 양쪽이 같은
# 컬렉션을 가리켜야 하므로).
CAPABILITY_COLLECTION_NAME = "capability_corpus"


def get_upstage_client() -> OpenAI:
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없습니다.")
    return OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")


def search_corpus(query: str, k: int = 5, doc_type: str = None) -> list[dict]:
    """query와 관련된 상위 k개 청크를 반환. doc_type='TTA' 또는 'NCS'로 필터링 가능."""
    client = get_upstage_client()
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

    query_embedding = client.embeddings.create(
        input=[query], model="solar-embedding-2-query"
    ).data[0].embedding

    where = {"doc_type": doc_type} if doc_type else None
    results = collection.query(query_embeddings=[query_embedding], n_results=k, where=where)

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        hits.append({"text": doc, "source_file": meta["source_file"], "doc_type": meta["doc_type"], "distance": dist})
    return hits


def search_capability_corpus(query: str, k: int = 3) -> list[dict]:
    """서비스 기능 안내 코퍼스(capability_corpus 전용 컬렉션) 검색.

    2026-07-24 추가: 원래는 search_corpus(doc_type="CAPABILITY")로 tta_ncs_corpus
    컬렉션을 함께 썼는데, 실측 결과(전체 1264개 중 CAPABILITY 3개) 근사 최근접
    검색(HNSW)이 doc_type 필터를 통과하는 진짜 근접 문서를 놓치는 문제가 재현되어
    (/tmp 재현 테스트: 군집형 데이터에서 필터 적용 시 3개 중 2개만 반환), capability
    전용 컬렉션을 새로 만들어 분리했다. 이 컬렉션에는 CAPABILITY 문서만 있으므로
    doc_type 필터가 필요 없다 — 항상 사실상 전수비교가 되어 위 문제가 발생하지 않는다.

    기존 search_corpus()는 verification.py가 TTA/NCS 검색에 그대로 쓰고 있으므로
    건드리지 않는다."""
    client = get_upstage_client()
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection(CAPABILITY_COLLECTION_NAME)

    query_embedding = client.embeddings.create(
        input=[query], model="solar-embedding-2-query"
    ).data[0].embedding

    results = collection.query(query_embeddings=[query_embedding], n_results=k)

    hits = []
    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    distances = results["distances"][0] if results["distances"] else []
    for doc, meta, dist in zip(documents, metadatas, distances):
        hits.append(
            {"text": doc, "source_file": meta["source_file"], "doc_type": meta["doc_type"], "distance": dist}
        )
    return hits


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "출처 메타데이터 스키마 설계 근거"
    for hit in search_corpus(q, k=3):
        print(f"[{hit['doc_type']}] {hit['source_file']} (거리 {hit['distance']:.3f})")
        print(f"  {hit['text'][:150]}...\n")
