import chess

from .base import Player
from .llm_client import LLMClient


class LLMPlayer(Player):
    def __init__(self, name: str, client: LLMClient, color: chess.Color, max_attempts=3):
        super().__init__(name)
        self.client = client
        self.color = color
        self.max_attempts = max_attempts
        self.last_attempt_count = 0
        self.used_fallback = False

    def get_move(self, board: chess.Board) -> chess.Move:
        legal_moves = sorted(move.uci() for move in board.legal_moves)
        side_to_move = 'w' if board.turn == chess.WHITE else 'b'
        self.last_attempt_count = 0
        self.used_fallback = False

        for attempt in range(self.max_attempts):
            self.last_attempt_count = attempt + 1
            try:
                move_uci = self.client.choose_move_uci(
                    fen=board.fen(),
                    legal_moves_uci=legal_moves,
                    side_to_move=side_to_move,
                    pgn_context='',
                )
            except Exception:
                continue

            if move_uci in legal_moves:
                return chess.Move.from_uci(move_uci)

        # Deterministic fallback keeps matches moving and tests stable.
        self.used_fallback = True
        return chess.Move.from_uci(legal_moves[0])
