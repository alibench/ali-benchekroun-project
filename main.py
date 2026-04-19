from __future__ import annotations  # we use modern type hints on older Pythons

from typing import Dict, List, Tuple 

import hashlib                       # used by the mock embedder to produce a stable pseudo-vector
import re                            # used to split text into sentences

import numpy as np                   # only "heavy" dependency; used for cosine similarity


# ----------------------------- helpers -----------------------------

# dimension of the mock embeddings. I made it small on purpose as this this is a toy embedder,
# we only need the cosine-similarity logic to be identical to a real system.
EMBEDDING_DIM: int = 64

# Target chunk size is in characters to keep the code dependency-free;
# approximately 400 chars aproximatly matches a paragraph of policy prose, which is consistent 
# with the "one chunk = one idea" principle I proposed from §1.2.
CHUNK_CHAR_BUDGET: int = 400


def _mock_embed(text: str) -> np.ndarray:
    """
    Does deterministic pseudo-embedding for a piece of text.

    It works here because:
      - A real embedder would map similar sentences to nearby vectors and here we
        only need a stable mapping so the data flow is correct; cosine-similarity
        behaviour is demonstrated on the query path.
      - We use SHA-256 of the lowercased text as a seed for a NumPy RNG, then we
        draw a fixed-size float vector. Same text -> same vector, different text -> almost certainly a different vector.
    """
    # here we normalise the text a bit so for example "Hello" and "hello" map to the same vector
    normalised: str = text.strip().lower()

    # we turn the text into a deterministic integer seed via a hash
    digest: bytes = hashlib.sha256(normalised.encode("utf-8")).digest()
    seed: int = int.from_bytes(digest[:8], "little", signed=False) % (2**32)

    # we draw a vector from a seeded RNG so the mapping is reproducible
    rng: np.random.Generator = np.random.default_rng(seed)
    vector: np.ndarray = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)

    # we L2-normalise so cosine similarity == dot product. This matches how real embedders like BGE-M3 are
    # used and makes the similarity formula cleaner
    norm: float = float(np.linalg.norm(vector))
    if norm > 0.0:
        vector = vector / norm
    return vector


def _split_into_sentences(text: str) -> List[str]:
    """
    This is again a simplified small sentence splitter

    A real system would use `unstructured` + a proper NLP splitter
    """
    # we collapse any run of whitespace (including newlines) into single spaces,
    # then split on '.', '!' or '?' followed by a space, keeping the punctuation
    cleaned: str = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    # we split after '.', '!' or '?' when followed by whitespace
    raw_parts: List[str] = re.split(r"(?<=[.!?])\s+", cleaned)
    # we drop empty fragments that the split may produce.
    return [p.strip() for p in raw_parts if p.strip()]


def _pack_sentences_into_chunks(sentences: List[str], budget: int) -> List[str]:
    """
    Packs sentences greedily into chunks whose length stays under "budget" characters

    this is again a simplified version, here we respect sentence boundaries (no mid-sentence cuts)
    and we keep several sentences together when they fit. A complete implementation would add overlap 
    and heading prefixes (as I described in ARCHITECTURE.md §1.2)
    """
    chunks: List[str] = []
    current: List[str] = []
    current_len: int = 0

    for sentence in sentences:
        sentence_len: int = len(sentence)
        # if adding this sentence would exceed the budget & the current chunk already has content,
        # we flush the current chunk first.
        if current and current_len + 1 + sentence_len > budget:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
        # we append the sentence to the in-progress chunk
        current.append(sentence)
        current_len += sentence_len + (1 if current_len > 0 else 0)  # +1 for the space

    # to not forget the trailing chunk
    if current:
        chunks.append(" ".join(current))
    return chunks


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:

    a_norm: float = float(np.linalg.norm(a))
    b_norm: float = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def _mock_llm(prompt: str, context_chunks: List[str]) -> str:
    """
    Deterministic mock of the LLM call.

    The behaviour is chosen such taht it mirrors the grounded-prompt rule I described from ARCHITECTURE.md
    in §3 and §6:
      - if there is no context, it replies "I don't know" rather than hallucinate
      - otherwise, it synthesises a short, explicit answer that quotes the
        retrieved chunks, allowing the caller to verify the citation
    A real (more advanced) deployment would replace this with an HTTP call to a Swiss-hosted
    LLM and only this function would change
    """
    if not context_chunks:
        return "I don't know — the provided policies do not cover this question."

    # Build a numbered citation list so the user can check the source of each claim.
    citations: str = "\n".join(
        f"  [{idx + 1}] {chunk}" for idx, chunk in enumerate(context_chunks)
    )
    # The 'answer' here is a grounded summary: in a real system, the LLM writes
    # this; in the mock, we simply expose the retrieved evidence transparently.
    return (
        f"Based on the internal policies, here is what is relevant to your question:\n"
        f"{citations}\n"
        f"(Prompt used internally: {prompt[:80]}...)"
    )


# ------------------------------ main class ------------------------------
class SimpleRAG:
    def __init__(self):
        """
        Initialize your Vector Store (in-memory or simple DB) here.
        ------------------------------------------------------------------------
        In-memory vector store: list of dicts with chunk_id, text, embedding."""
        self.vector_store: List[Dict[str, object]] = []


    def ingest(self, text_content: str) -> None:
        """
        1. Split text into chunks (Bonus: respect sentence boundaries).
        2. Vectorize chunks (can be mocked).
        3. Store vectors and text.
        
        ------------------------------------------------------------------------
        
        We ingest a raw block of text: split into chunks, embed each chunk,
        and store (chunk_text, embedding) in the vector store.

        Steps (we mirror what I described inARCHITECTURE.md §1, simplified):
            1. split the text into sentences (respecting sentence boundaries)
            2. pack sentences greedily into chunks under a character budget
            3. embed every chunk with the mock embedder
            4. append each (text, embedding) to the in-memory vector store
        """
        # 1. sentence-aware splitting
        sentences: List[str] = _split_into_sentences(text_content)

        # there's nothing to ingest if the input is empty or whitespace-only
        if not sentences:
            return

        # 2. greedy packing into chunks of reasonable size
        chunks: List[str] = _pack_sentences_into_chunks(sentences, CHUNK_CHAR_BUDGET)

        # 3 + 4. Embed each chunk and store it.
        for chunk_text in chunks:
            embedding: np.ndarray = _mock_embed(chunk_text)
            record: Dict[str, object] = {
                "chunk_id": len(self.vector_store),  # simple monotonic id
                "text": chunk_text,
                "embedding": embedding,
            }
            self.vector_store.append(record)


    def retrieve(self, query: str, k: int = 3) -> List[str]:
        """
        Retrieve the top-k most relevant chunks for the given query.
        (Use cosine similarity or a keyword search if no embeddings available).
        
        ------------------------------------------------------------------------
                
        Return the top-k chunk texts most similar to `query` by cosine similarity.

        This is analogue of Qdrant's HNSW + cosine search from ARCHITECTURE.md §2.3,
        we iterate over every stored record, compute cosine similarity, sort by descending score,
        and return the top k chunk texts; we return only the chunk *texts* because the skeleton declares the
        return type as List[str], and the scores and ids stay internal to the class.
        """
        
        # empty store -> nothing to retrieve
        if not self.vector_store:
            return []

        # we embed the query with the SAME embedder used at ingestion
        query_vec: np.ndarray = _mock_embed(query)

        # we compute (score, text) for every chunk in the store.
        scored: List[Tuple[float, str]] = []
        for record in self.vector_store:
            chunk_vec: np.ndarray = record["embedding"]  
            chunk_text: str = record["text"]             
            score: float = _cosine_similarity(query_vec, chunk_vec)
            scored.append((score, chunk_text))

        # we sort by descending similarity (largest cosine first) and keep top-k.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top_k: List[Tuple[float, str]] = scored[: max(0, k)]

        # returns only the texts as requiered
        return [text for _, text in top_k]

    def generate_response(self, query: str) -> str:
        """
        1. Retrieve context based on query.
        2. Simulate an LLM generation using that context.
        
        ------------------------------------------------------------------------
        Produces an answer to `query` using the retrieved context.

        the pipeline is the folllwing (it mirrors what I described in ARCHITECTURE.md §3):
            1. retrieves the top-k chunks for the query
            2. builds a grounded prompt: the LLM must answer only from those
               chunks and must say "I don't know" if the context is empty
            3. calls the mocked LLM
            4. returns the final answer
        """

        # we retrieve relevant context.
        context_chunks: List[str] = self.retrieve(query, k=3)

        # we build the grounded prompt
        # (in a real system this would be the single reviewed system prompt described in §3, with explicit citation instructions)
        joined_context: str = "\n".join(f"- {c}" for c in context_chunks)
        prompt: str = (
            "You are the internal assistant of a Swiss SME. "
            "Answer ONLY from the provided context. "
            "If the context is insufficient, reply 'I don't know'. "
            "Cite the source chunks.\n\n"
            f"Context:\n{joined_context}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )

        # we call the mocked LLM (this is the single place to swap if we want to do a real HTTP call later)
        answer: str = _mock_llm(prompt, context_chunks)

        # returns the grounded answer
        return answer

# --- Test Execution ---
if __name__ == "__main__":
    # Example Data
    policy_text = """
    Employees can work remotely 2 days a week. 
    Expenses are refunded up to 25 CHF for lunch. 
    Security requires all data to stay in Switzerland.
    """

    rag = SimpleRAG()
    
    print("--- Ingesting ---")
    try:
        rag.ingest(policy_text)
        print("Ingestion successful (if implemented)")
    except NotImplementedError:
        print("Ingest method not implemented yet.")
    
    query = "What is the remote work policy?"
    print(f"\n--- Querying: {query} ---")
    
    try:
        response = rag.generate_response(query)
        print(f"Result: {response}")
    except NotImplementedError:
        print("Generate Response method not implemented yet.")
