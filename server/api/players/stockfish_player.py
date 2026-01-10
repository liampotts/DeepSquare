import chess
import chess.engine
from .base import Player
import shutil

class StockfishPlayer(Player):
    def __init__(self, name: str, time_limit: float = 0.1):
        super().__init__(name)
        self.time_limit = time_limit
        # Auto-detect stockfish path
        self.engine_path = shutil.which("stockfish")
        if not self.engine_path:
             # Fallback for common locations if not in PATH (though brew should be in PATH)
            self.engine_path = "/opt/homebrew/bin/stockfish"
            
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Stockfish engine not found at {self.engine_path}. Please install specific stockfish.")

    def get_move(self, board: chess.Board) -> chess.Move:
        result = self.engine.play(board, chess.engine.Limit(time=self.time_limit))
        return result.move

    def close(self):
        self.engine.quit()
