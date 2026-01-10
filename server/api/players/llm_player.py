import chess
from .base import Player
from .llm_client import LLMClient
import re

class LLMPlayer(Player):
    def __init__(self, name: str, client: LLMClient, color: chess.Color):
        super().__init__(name)
        self.client = client
        self.color = color
        self.system_prompt = (
            "You are a chess grandmaster. You play aggressively but soundly. "
            "You will be provided with the current board state in FEN notation and a list of legal moves. "
            "You must select the best move from the legal moves. "
            "Reply ONLY with the move in Standard Algebraic Notation (SAN). Do not explain."
        )

    def get_move(self, board: chess.Board) -> chess.Move:
        legal_moves = [board.san(move) for move in board.legal_moves]
        fen = board.fen()
        color_str = "White" if self.color == chess.WHITE else "Black"
        
        user_prompt = (
            f"You are playing as {color_str}.\n"
            f"Current FEN: {fen}\n"
            f"Legal moves: {', '.join(legal_moves)}.\n"
            "What is your move?"
        )

        # Retry logic could go here
        attempts = 3
        for _ in range(attempts):
            response = self.client.get_completion(self.system_prompt, user_prompt)
            move_san = self._clean_response(response)
            
            try:
                move = board.parse_san(move_san)
                if move in board.legal_moves:
                    return move
            except ValueError:
                # print(f"Invalid move returned: {response}") # Debugging
                pass
        
        # Fallback: random move to avoid crashing
        print(f"{self.name} failed to generate a valid move after {attempts} attempts. Playing random move.")
        import random
        return random.choice(list(board.legal_moves))

    def _clean_response(self, response: str) -> str:
        # Remove any whitespace or extra punctuation
        return response.strip().strip(".").split()[0]
