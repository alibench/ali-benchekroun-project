# Exponent – Technical Assessment
**Role:** AI Software Engineer Internship

## General Instructions
* **Goal:** This assessment evaluates your ability to design a secure AI architecture and implement a basic RAG (Retrieval-Augmented Generation) pipeline.
* **Format:** You must deliver your work as a GitHub Repository.
* **AI Policy:** You are allowed to use AI tools (ChatGPT, Claude, Copilot, etc.) to assist you. However, you must be able to explain every line of code and every architectural decision. Blind copy-pasting will be penalized.

### How to submit
1.  Initialize a new private or public GitHub repository.
2.  Commit your work regularly so we can see your progress (we look at the commit history).
3.  Send us the link to the repository (ensure we have access if it is private).

---

## PART 1 — RAG Case Study (Architecture)
**Context:** A Swiss-based SME wants to implement an internal assistant that allows employees to ask questions about HR documents, internal procedures, and security policies. All data must be hosted 100% in Switzerland according to nFADP (LPD) standards.

**Task:** In your repository, create a file named `ARCHITECTURE.md`. Describe how you would implement a simple and secure RAG pipeline, specifying:

1.  **Document Ingestion:** How you handle preprocessing, chunking strategy, and which embedding models you would choose.
2.  **Vector Store:** Choice of vector database suitable for a Swiss SME context.
3.  **LLM Orchestrator:** Choice of framework (LangChain, LlamaIndex, etc.) and rationale.
4.  **100% Switzerland-based Hosting:** Precise strategy for hosting both Compute (LLM inference) and Storage ensuring data sovereignty.
5.  **Security:** Critical points regarding access control (RBAC) and data residency.
6.  **Hallucinations:** Explain 2-3 specific techniques you would use to limit hallucinations in this context.

*Bonus: Include a simple diagram of the pipeline in your MD file (ASCII art or an image).*

---

## PART 2 — Coding Exercise (Implementation)
**Goal:** Demonstrate your Python skills by implementing a simplified, object-oriented RAG logic.

**Instructions:**
1.  Create a file named `main.py` in your repository.
2.  Copy the **Skeleton Code** provided below.
3.  Implement the missing methods (`ingest`, `retrieve`, `generate_response`).

**Constraints:**
* You do not need to set up a real heavy database. You can use in-memory storage (lists/dictionaries) or lightweight libraries (like chromadb or sklearn for cosine similarity).
* For the embedding and LLM parts, if you cannot run models locally, you may mock the functions (simulate them), but the logic and data flow must be correct.
* The code must be clean, typed, and documented.

### Skeleton Code to copy into main.py:
(Please use the `main.py` file provided in this repository template).
