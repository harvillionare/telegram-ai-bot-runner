from typing import List, Protocol

class EmbeddingClient(Protocol):
    """Protocol for embedding providers."""

    @property
    def dimensions(self) -> int:
        """int: The number of floating-point values in each embedding vector."""
        ...

    def embed(self, text: str) -> List[float]: 
        """Compute an embedding vector for the given text.
        
        Args:
            text (str): The text to encode into an embedding vector.

        Returns:
            List[float]: The numeric embedding representation of the input text.
        """
        ...