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


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "출처 메타데이터 스키마 설계 근거"
    for hit in search_corpus(q, k=3):
        print(f"[{hit['doc_type']}] {hit['source_file']} (거리 {hit['distance']:.3f})")
        print(f"  {hit['text'][:150]}...\n")
