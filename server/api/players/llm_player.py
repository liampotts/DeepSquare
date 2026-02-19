import chess

from .base import Player
from .llm_client import LLMClient
from .ttc_policy import TTCPolicyEngine


class LLMPlayer(Player):
    def __init__(
        self,
        name: str,
        client: LLMClient,
        color: chess.Color,
        max_attempts=3,
        ttc_policy=None,
        verifier_client=None,
        fallback_client=None,
    ):
        super().__init__(name)
        self.client = client
        self.color = color
        self.max_attempts = max_attempts
        self.policy_engine = TTCPolicyEngine.from_config(ttc_policy, max_attempts=max_attempts)
        self.verifier_client = verifier_client
        self.fallback_client = fallback_client
        self.last_attempt_count = 0
        self.used_fallback = False
        self.policy_trace = {}

    def get_move(self, board: chess.Board) -> chess.Move:
        legal_moves = sorted(move.uci() for move in board.legal_moves)
        side_to_move = 'w' if board.turn == chess.WHITE else 'b'
        self.last_attempt_count = 0
        self.used_fallback = False

        result = self.policy_engine.choose_move(
            primary_client=self.client,
            fallback_client=self.fallback_client,
            verifier_client=self.verifier_client,
            fen=board.fen(),
            legal_moves_uci=legal_moves,
            side_to_move=side_to_move,
            pgn_context='',
        )
        self.last_attempt_count = result.attempts
        self.used_fallback = result.used_fallback
        self.policy_trace = result.trace

        move_uci = result.move_uci
        if move_uci not in legal_moves:
            self.used_fallback = True
            move_uci = legal_moves[0]

        return chess.Move.from_uci(move_uci)
