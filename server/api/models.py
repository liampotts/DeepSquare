from django.db import models


class Game(models.Model):
    # FEN string representing current board state
    fen = models.CharField(max_length=100, default='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    
    # Store moves in PGN format or a list of UCI moves
    pgn = models.TextField(blank=True, default='')
    
    # Status
    is_game_over = models.BooleanField(default=False)
    winner = models.CharField(max_length=10, blank=True, null=True) # "white", "black", "draw"
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Players (could be generic "white_player_type", "black_player_type")
    # For now, simple strings identifying mode/player
    white_player_type = models.CharField(max_length=20, default='human')
    white_player_config = models.JSONField(default=dict, blank=True)
    black_player_type = models.CharField(max_length=20, default='human') # human, stockfish, llm
    black_player_config = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Game {self.id} ({self.white_player_type} vs {self.black_player_type})"


class ArenaRun(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = (
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    config = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ArenaRun {self.id} ({self.status})"
