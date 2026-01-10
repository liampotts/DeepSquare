import chess
from players.base import Player

class HumanPlayer(Player):
    def get_move(self, board: chess.Board) -> chess.Move:
        while True:
            try:
                move_uci = input(f"{self.name}, enter your move (e.g., e2e4): ")
                move = chess.Move.from_uci(move_uci)
                if move in board.legal_moves:
                    return move
                else:
                    print("Illegal move. Please try again.")
            except ValueError:
                print("Invalid format. Use UCI format (e.g., e2e4).")
