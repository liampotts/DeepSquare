import chess
from players.base import Player

class ChessGame:
    def __init__(self, white_player: Player, black_player: Player):
        self.board = chess.Board()
        self.white_player = white_player
        self.black_player = black_player

    def play(self):
        print("Starting game...")
        print(self.board)
        
        while not self.board.is_game_over():
            if self.board.turn == chess.WHITE:
                current_player = self.white_player
            else:
                current_player = self.black_player
            
            print(f"\n{current_player.name}'s turn ({'White' if self.board.turn == chess.WHITE else 'Black'})")
            move = current_player.get_move(self.board)
            self.board.push(move)
            print("--------------------------------")
            print(self.board)
        
        print("\nGame Over!")
        if self.board.is_checkmate():
            winner = "Black" if self.board.turn == chess.WHITE else "White"
            print(f"Checkmate! {winner} wins.")
        elif self.board.is_stalemate():
            print("Stalemate!")
        elif self.board.is_insufficient_material():
            print("Draw by insufficient material.")
        else:
            print(f"Game ended. Result: {self.board.result()}")
