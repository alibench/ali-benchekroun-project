from typing import List

class SimpleRAG:
    def __init__(self):
        """
        Initialize your Vector Store (in-memory or simple DB) here.
        """
        self.vector_store = []
        pass

    def ingest(self, text_content: str) -> None:
        """
        1. Split text into chunks (Bonus: respect sentence boundaries).
        2. Vectorize chunks (can be mocked).
        3. Store vectors and text.
        """
        raise NotImplementedError("To be implemented")

    def retrieve(self, query: str, k: int = 3) -> List[str]:
        """
        Retrieve the top-k most relevant chunks for the given query.
        (Use cosine similarity or a keyword search if no embeddings available).
        """
        raise NotImplementedError("To be implemented")

    def generate_response(self, query: str) -> str:
        """
        1. Retrieve context based on query.
        2. Simulate an LLM generation using that context.
        """
        # Example logic:
        # context = self.retrieve(query)
        # prompt = f"Context: {context}\nQuestion: {query}"
        # return llm_call(prompt)
        raise NotImplementedError("To be implemented")

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
