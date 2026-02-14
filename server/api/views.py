from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Game
from .serializers import GameSerializer, MoveSerializer
import chess
# Import players - we will refactor usage later, for now we need a helper
from .players.stockfish_player import StockfishPlayer
# from .players.llm_player import LLMPlayer

class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all().order_by('-created_at')
    serializer_class = GameSerializer
    authentication_classes = []  # Disable CSRF check for this view

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        game = self.get_object()

        if game.is_game_over:
            return Response(
                {"error": "Game is already over", "code": "game_over"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MoveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid UCI format", "code": "invalid_uci"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        move_uci = serializer.validated_data['move_uci']
        board = chess.Board(game.fen)

        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            return Response(
                {"error": "Invalid UCI format", "code": "invalid_uci"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if move not in board.legal_moves:
            return Response(
                {
                    "error": "Illegal move",
                    "code": "illegal_move",
                    "move_uci": move_uci,
                    "legal_moves": [legal_move.uci() for legal_move in board.legal_moves],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._append_san_to_pgn(game, board, move)

        # Apply Human Move
        board.push(move)
        self._update_game_state(game, board)

        # If Game Over, return
        if board.is_game_over():
            return Response(GameSerializer(game).data)

        # Check if opponent is AI and it's their turn
        if board.turn == chess.BLACK and game.black_player_type == 'stockfish':
            ai_error = self._make_stockfish_move(game, board)
            if ai_error:
                return Response(
                    {"error": "Failed to generate AI move", "code": "ai_move_error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(GameSerializer(game).data)

    def _update_game_state(self, game, board):
        game.fen = board.fen()
        if board.is_game_over():
            game.is_game_over = True
            game.winner = self._get_winner(board)
        game.save()

    def _append_san_to_pgn(self, game, board, move):
        san = board.san(move)
        if board.turn == chess.WHITE:
            game.pgn += f"{board.fullmove_number}. {san} "
        else:
            game.pgn += f"{san} "

    def _get_winner(self, board):
        if board.is_checkmate():
            return "White" if board.turn == chess.BLACK else "Black"
        return "Draw"

    def _make_stockfish_move(self, game, board):
        player = None
        try:
            # Instantiate player temporarily.
            # This opens/closes process every move. Inefficient but safe for stateless HTTP.
            player = StockfishPlayer("Stockfish", time_limit=0.5)
            move = player.get_move(board)
            if move not in board.legal_moves:
                raise ValueError("AI generated illegal move")

            self._append_san_to_pgn(game, board, move)
            board.push(move)
            self._update_game_state(game, board)
            return None
        except Exception as e:
            print(f"Error AI move: {e}")
            return e
        finally:
            if player is not None:
                try:
                    player.close()
                except Exception:
                    pass
