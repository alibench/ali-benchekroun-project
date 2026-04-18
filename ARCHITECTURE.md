# ARCHITECTURE.md

## Context

The goal is an internal assistant for a Swiss SME, answering employee questions over HR documents, internal procedures, and security policies. The two hard constraints shaping every choice below are **nFADP compliance (100 % Swiss data residency)** and **simplicity** — this is an internal tool, not a research system, so I sometimes prefer fair and defensible (more optimal to our use case) choices over clever ones.

---

## 1. Document Ingestion

I split ingestion into four concerns: preprocessing, chunking, embeddings, and metadata/re-indexing. The pipeline runs as a nightly batch job on a Swiss VM (details in §4) and feeds the vector store described in §2.

### 1.1 Preprocessing

The corpus will be heterogeneous — native and scanned PDFs, `.docx`, intranet HTML, the occasional spreadsheet or PowerPoint. I would use `**unstructured`** as the main parser because it auto-detects file type and, crucially, returns a typed element tree (`Title`, `NarrativeText`, `Table`, `ListItem`) instead of a flat string. I need that structure in §1.2. For scanned PDFs I add an OCR fallback with `**pytesseract`**, isolated to that specific case so the OCR cost stays bounded.

After extraction I normalise everything to UTF-8 with Unicode NFC so a character like `é` always has the same byte representation, and I strip repeating headers, footers, page numbers, and HTML boilerplate (navigation, scripts, cookie banners) — otherwise they pollute every chunk. Tables I keep, serialised as Markdown, so the LLM can still read their rows and columns downstream.

I detect the dominant language of each document with `**fasttext-langdetect`** and store it as metadata. Swiss SMEs mix FR, DE, IT, and EN, so this lets me either filter retrieval by language or, more often, rely on the multilingual embedder (§1.3) for cross-lingual matching (a French query finding a German chunk).

For deduplication I compute a **SHA-256** hash of each raw file and drop exact duplicates. I pick SHA-256 over MD5 because MD5 has known collisions (it had been broken by attackers); the performance difference is negligible at this scale and SHA-256 is the default expectation of any security review. I could do near-duplicate detection, but it depends on the similarity of the internal procedures, I ahve to have more informations on the SME.

One note on PII: HR documents contain names, AVS numbers, salaries. I keep them inside chunks (authorised employees need to read them), but I never log chunk content in plain text, and chunks inherit the access tags of their source folder so confidential material is gated by RBAC rather than by redaction (see §1.4 and §5).

### 1.2 Chunking

I chose **structure-aware chunking with recursive fallback and title prepending**.

Concretely: the heading tree from `unstructured` gives me one chunk per terminal section. If a section is longer than my target size, I recursively split it on `\n\n → \n → ". " → " "`, always using the most respectful separator that produces pieces under the limit. I prepend the heading path ("HR Handbook > 3. Leave > 3.2 Sick leave") to every chunk, which is nearly free and measurably boosts retrieval because the topical anchor ends up inside the embedding.

**Target size: 500 tokens, with 15 % overlap (75 tokens).** I picked 500 because policy-style prose tends to have "one rule per paragraph of 300–600 tokens" — smaller chunks lose antecedents ("this rule does not apply to..." without the rule), larger chunks dilute the embedding. 500 is the common empirical sweet spot reported in the LangChain and LlamaIndex documentation for this kind of corpus, and it sits comfortably inside the 8 192-token context window of the embedder I picked in §1.3, leaving room for the title prefix. I picked 15 % overlap as the smallest value that reliably catches a rule/exception pair spanning a cut, without inflating storage beyond 15 %.

I rejected **fixed-size chunking** because it ignores structure and routinely cuts mid-sentence or mid-table. I also rejected **pure semantic chunking** (embedding each sentence and merging while similar): it's expensive at ingestion, threshold-sensitive, and gives me nothing on documents that already have explicit headings written by humans.

### 1.3 Embeddings

I need a model that is multilingual (FR / DE / IT / EN), self-hostable on Swiss infrastructure, commercially licensed, and good enough for cross-lingual retrieval. My choice is `**BAAI/bge-m3`**.

What I like about it:

- Apache 2.0 license, so no commercial ambiguity.
- Covers 100+ languages including all four I care about, with strong cross-lingual performance.
- 8 192-token input window, which matches my 500-token chunks plus title prefix with margin to spare.
- 1 024-dim output — enough quality, not enough to bloat the vector store.
- Produces dense **and** sparse vectors simultaneously. **I will only use the dense side today**, but storing the sparse vectors at ingestion keeps the door open to hybrid search in §2 without re-indexing later.

I rejected **OpenAI** `text-embedding-3-large` despite its strong benchmarks because it is a proprietary API: every chunk would leave Switzerland. The only way to keep it Swiss-resident would be Azure OpenAI Switzerland North, which adds cost, vendor lock-in, and a new contractual layer for a marginal accuracy gain I think we don't necessarily need. I rejected `**multilingual-e5-large`** because its 512-token context is tight once the title prefix is added, and it has no sparse output. I rejected `**jina-embeddings-v3`** because its current CC-BY-NC license is ambiguous for commercial internal use.

I serve the model with **Text Embeddings Inference (TEI)** from Hugging Face, in a container on the same Swiss VM as the rest of the stack. It gives me batching and a stable HTTP endpoint without me writing a server from scratch.

One operational commitment: I record the embedding model in each chunk's metadata. Different models live in different vector spaces, so if I ever upgrade the embedder I must re-embed the whole corpus. That record makes the migration explicit instead of silently broken.

### 1.4 Metadata and incremental re-indexing

Every chunk stored in the vector database carries metadata I need for three jobs: citation, access control, and re-indexing.

For **citation**, I keep the source filename, document version, and the heading path of the section the chunk came from. When the LLM answers, it quotes those fields so employees can verify the claim against the original document, which is in my point of view non-negotiable for an internal tool.

For **access control**, each chunk inherits the access tags of its source folder in the document management system, plus a confidentiality level (internal / confidential / restricted). The vector store applies these as a **pre-filter** before similarity search, so a user never retrieves a chunk they are not authorised to see. Details in §5; the point here is that these fields must be set at ingestion, not later, so the cosine-similarity does not run more for nothing (it won't be efficient, and a lot of people make this mistake, here's an extreme example: if only 2 % of chunks are accessible to a user, we might retrieve 100 candidates and be left with 0 matching the filter).

For **re-indexing and compliance**, I store the file's SHA-256 hash, the last-modified and last-ingested timestamps, the chunk's index and total count within its document, and the name of the embedding model that produced the vector. The hash lets me detect changes cheaply; the timestamps let me prove freshness; the chunk indices let me pull neighbouring chunks if the LLM needs more context; the embedding-model field lets me migrate safely.

**Incremental re-indexing** runs as a nightly cron at 02:00 Swiss time — early enough that the morning's users see fresh content, cheap enough that I don't need event-driven infrastructure yet. A small SQLite ledger on the same Swiss VM maps `file_path → last_hash → last_ingested_at`. Four cases per run:

1. File new in source → parse, chunk, embed, insert, add to ledger.
2. File modified (hash changed) → delete all chunks where `source_file` matches, re-process, insert new chunks, update ledger.
3. File unchanged → skip.
4. File deleted from source → delete its chunks from the vector store, remove from ledger.

The same mechanism handles nFADP **right-to-erasure** requests: deletion by `source_file` or `source_hash` is a single query, logged to the audit trail.

### 1.5 End-to-end ingestion loop

```
For each file in the Swiss document source (SharePoint / Nextcloud / shared folder):
  1. Compute SHA-256 hash of the file
  2. Consult ingestion ledger → new / modified / unchanged / deleted
  3. If new or modified:
       a. Parse with unstructured (+ OCR fallback for scanned PDFs)
       b. Normalise (UTF-8, NFC, strip headers/footers, keep tables as Markdown)
       c. Detect language (FR / DE / IT / EN)
       d. Structure-aware chunk (~500 tokens, ~15 % overlap, recursive fallback)
       e. Prepend section-title breadcrumb to each chunk
       f. Embed with BGE-M3 on self-hosted TEI (Swiss VM)
       g. Attach metadata (provenance, freshness, language, access tags, bookkeeping)
       h. Upsert into the vector store (delete old chunks first if modified)
       i. Update the ingestion ledger
  4. If deleted from source: delete all matching chunks + update ledger
Log the run (file counts, timings, errors) to the audit log (Swiss soil).
```

## 2. Vector Store

### 2.1 What I need from the vector store

For this use case I have five criteria, in roughly this order of importance: (1) self-hostable on a Swiss VM, because nFADP rules out any managed cloud outside Switzerland; (2) permissive commercial license — Apache 2.0 or equivalent — so the SME is not forced into re-licensing conversations later; (3) strong metadata pre-filtering, because RBAC (§5) depends on filtering *before* the similarity search, not after; (4) native hybrid-search support so I can enable dense + sparse retrieval later without re-indexing; (5) low operational burden — one container, one volume, one port — because the SME's IT team is small.

### 2.2 My choice: Qdrant, self-hosted, single-node

I would use **Qdrant**, running as a single Docker container on a Swiss VM (§4), with a persistent volume for vector data and periodic snapshots for backup.

Qdrant fits all six criteria without compromise. It is Apache 2.0, written in Rust (so it runs in a single binary and is memory-efficient), and its metadata filtering uses an implementation they call "filterable HNSW" that integrates the filter directly into the graph walk. That matters to me because my RBAC filters are often selective, a given user may only be entitled to a small fraction of the corpus, and in that regime a post-filter approach returns too few matches. Hybrid search (dense + sparse + RRF) is native and behind a single configuration switch, which is exactly the upgrade path I want.

I considered four alternatives and rejected them:

- **Milvus** is engineered for billion-vector workloads with a distributed, multi-component architecture. Over-engineered for my scale (roughly 10⁵–10⁶ chunks).
- **Weaviate** is a strong option with good filters and native hybrid, but operationally heavier than Qdrant (more configuration, more moving parts). I didn't find any quality gain to justify the extra surface area for a SME team.
- **Chroma** is very light to run, but its filter implementation degrades on selective queries and hybrid support is limited. Good for prototypes, not where I'd bet production RBAC.
- **pgvector** (PostgreSQL extension) is genuinely tempting if the SME already runs Postgres: vector search becomes "just another column," and backups, replication, and access control are inherited from a system the IT team already knows. I rejected it here because hybrid search has to be hand-wired (Postgres full-text search + vector column, fused in the application), its HNSW is less tuned than Qdrant's, and filter quality relies on the Postgres query planner. If I later discovered the SME already had a Postgres DBA and a lightweight corpus, I would revisit this decision.

### 2.3 Index and search configuration

I'd configure Qdrant with an **HNSW index** (graph-based approximate nearest-neighbour search) using **cosine similarity** as the metric, consistent with how BGE-M3 was trained. HNSW is the default in Qdrant and trades around one percent of recall for a 10–100× speedup over brute-force search — a very acceptable loss.

Every query carries a **metadata pre-filter** on `access_tags` and, when relevant, `language`. Pre-filtering (as opposed to post-filtering) is non-negotiable here: if a user is only entitled to 5 % of the corpus, a post-filter retrieves the global top-k first and may leave us with zero accessible matches. Qdrant's filterable-HNSW walks the graph only through vectors that already satisfy the filter, which keeps both recall and latency stable regardless of how selective the filter is.

For day-one sizing, a single Qdrant instance with a few GB of RAM handles the SME's expected corpus (~10⁵–10⁶ chunks × 1 024-dim vectors ≈ a few GB of vectors + index) with sub-100 ms query latency. Snapshots are scheduled nightly to the same Swiss storage used for the rest of the stack (§4), which also keeps the disaster-recovery story aligned with nFADP retention rules.

### 2.4 Hybrid search: why dense-only at v1, and how I kept hybrid ready

Dense embeddings alone struggle on rare tokens — form codes, acronyms, policy IDs, proper names — because those strings carry little semantic content and the embedder averages them out. Hybrid search fixes this by running dense retrieval in parallel with a sparse/keyword retrieval (BM25-style) and fusing the two rankings into a single ranked list, typically with **Reciprocal Rank Fusion (RRF)** because it is scale-free and needs no tuning.

I still chose **dense-only for v1**. The corpus is prose — HR policies, procedures, security documents — where paraphrases and synonyms dominate (which is the regime where dense shines). Shipping hybrid on day one would mean tuning a fusion weight against queries I haven't seen yet, which is guesswork. Starting dense-only lets the query logs tell me whether hybrid would actually help before I add the complexity.

What makes this safe rather than lazy is that I already picked BGE-M3, which emits a sparse vector alongside the dense one in the same forward pass (§1.3), and I picked Qdrant, which supports hybrid dense + sparse + RRF natively. Enabling hybrid later is just a configuration change, not a re-indexing.