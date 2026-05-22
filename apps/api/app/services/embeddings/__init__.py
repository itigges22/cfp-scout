"""Embeddings pipeline.

Public surface:
    embed_owner(db, owner_type, owner_id, text)  — chunk + embed + persist
    similar_chunks(db, query, owner_types, k)    — vector similarity search
    chunk_text(text)                              — sentence-aware chunker

See ``PLANS/phase-1/11-embeddings-and-chunking.md`` for the design.
"""

from app.services.embeddings.chunker import ChunkData, chunk_text
from app.services.embeddings.pipeline import embed_owner, get_active_embedding_model
from app.services.embeddings.search import similar_chunks

__all__ = [
    "ChunkData",
    "chunk_text",
    "embed_owner",
    "get_active_embedding_model",
    "similar_chunks",
]
