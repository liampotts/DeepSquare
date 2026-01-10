from rest_framework import serializers
from .models import Game
import chess

class GameSerializer(serializers.ModelSerializer):
    legal_moves = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ['id', 'fen', 'pgn', 'is_game_over', 'winner', 'white_player_type', 'black_player_type', 'legal_moves', 'created_at']

    def get_legal_moves(self, obj):
        board = chess.Board(obj.fen)
        if board.is_game_over():
            return []
        return [move.uci() for move in board.legal_moves]

class MoveSerializer(serializers.Serializer):
    move_uci = serializers.CharField(max_length=5)
