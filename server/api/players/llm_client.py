from abc import ABC, abstractmethod
import random
import chess

class LLMClient(ABC):
    @abstractmethod
    def get_completion(self, system_prompt: str, user_prompt: str) -> str:
        pass

class MockLLMClient(LLMClient):
    """A mock client that returns random legal moves for testing."""
    def __init__(self, board: chess.Board = None):
        # We might need access to the board to generate legal moves for the mock,
        # or we can just make it return a fixed move if we don't have the board state.
        # Ideally, the client just returns text.
        pass

    def get_completion(self, system_prompt: str, user_prompt: str) -> str:
        # In a real scenario, this would call an API.
        # For the mock, we can't easily generate a legal move without the board state unless passed in.
        # But the client interface just takes prompts. 
        # So this mock might be limited or we need to pass context differently.
        # For simplicity, let's just return a placeholder or try to extract valid moves if they were in the prompt.
        
        # Heuristic: if the prompt contains a list of legal moves, pick one.
        if "Legal moves:" in user_prompt:
            try:
                # Extract part after "Legal moves:"
                moves_str = user_prompt.split("Legal moves:")[1].split(".")[0]
                moves = [m.strip() for m in moves_str.split(",")]
                if moves:
                    return random.choice(moves)
            except:
                pass
        return "e2e4" # Fallback
