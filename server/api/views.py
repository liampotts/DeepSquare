from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Game
from .serializers import GameSerializer, MoveSerializer
import chess
# Import players - we will refactor usage later, for now we need a helper
from .players.stockfish_player import StockfishPlayer
# from .players.llm_player import LLMPlayer

class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all().order_by('-created_at')
    serializer_class = GameSerializer

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        game = self.get_object()
        serializer = MoveSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        move_uci = serializer.validated_data['move_uci']
        board = chess.Board(game.fen)
        
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
             return Response({"error": "Invalid UCI format"}, status=status.HTTP_400_BAD_REQUEST)

        if move not in board.legal_moves:
             return Response({"error": "Illegal move"}, status=status.HTTP_400_BAD_REQUEST)
             
        # Apply Human Move
        board.push(move)
        self._update_game_state(game, board)
        
        # If Game Over, return
        if board.is_game_over():
            return Response(GameSerializer(game).data)
            
        # Check if opponent is AI and it's their turn
        # Assume Human is White for now, or check game.white_player_type
        # Simple logic: If turn is Black and black_player_type != 'human'
        if board.turn == chess.BLACK and game.black_player_type == 'stockfish':
             self._make_stockfish_move(game, board)
        
        return Response(GameSerializer(game).data)

    def _update_game_state(self, game, board):
        game.fen = board.fen()
        # game.pgn = ... # Update PGN later
        if board.is_game_over():
            game.is_game_over = True
            game.winner = self._get_winner(board)
        game.save()

    def _get_winner(self, board):
        if board.is_checkmate():
            return "White" if board.turn == chess.BLACK else "Black"
        return "Draw"

    def _make_stockfish_move(self, game, board):
        try:
            # Instantiate player temporarily
            # Note: This opens/closes process every move. Inefficient but safe for stateless HTTP.
            player = StockfishPlayer("Stockfish", time_limit=0.5) 
            move = player.get_move(board)
            player.close()
            
            board.push(move)
            self._update_game_state(game, board)
        except Exception as e:
            print(f"Error AI move: {e}")
