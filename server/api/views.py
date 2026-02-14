import logging
import time

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from .models import Game
from .serializers import GameSerializer, MoveSerializer
import chess
from .players.stockfish_player import StockfishPlayer
from .players.llm_player import LLMPlayer
from .players.openai_client import OpenAIClient
from .players.anthropic_client import AnthropicClient
from .players.gemini_client import GeminiClient
from .players.local_client import LocalClient
from .analysis import (
    AnalysisTooShortError,
    AnalysisUnavailableError,
    GameAnalysisService,
)

logger = logging.getLogger(__name__)


class AIOptionsView(APIView):
    authentication_classes = []

    @staticmethod
    def _providers_payload():
        providers = {
            'openai': settings.LLM_ALLOWED_MODELS_OPENAI,
            'anthropic': settings.LLM_ALLOWED_MODELS_ANTHROPIC,
            'gemini': settings.LLM_ALLOWED_MODELS_GEMINI,
        }
        if settings.LOCAL_LLM_ENABLED:
            providers['local'] = settings.LLM_ALLOWED_MODELS_LOCAL
        return providers

    def get(self, request):
        if not settings.LLM_FEATURE_ENABLED:
            return Response(
                {
                    'providers': {},
                    'advanced_custom_model_enabled': settings.LLM_ADVANCED_CUSTOM_MODEL_ENABLED,
                }
            )

        return Response(
            {
                'providers': self._providers_payload(),
                'advanced_custom_model_enabled': settings.LLM_ADVANCED_CUSTOM_MODEL_ENABLED,
            }
        )


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all().order_by('-created_at')
    serializer_class = GameSerializer
    authentication_classes = []  # Disable CSRF check for this view

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            if 'error' in errors and 'code' in errors:
                error_value = errors.get('error')
                code_value = errors.get('code')

                if isinstance(error_value, list):
                    error_value = error_value[0]
                if isinstance(code_value, list):
                    code_value = code_value[0]

                return Response(
                    {'error': str(error_value), 'code': str(code_value)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

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
        if board.turn == chess.BLACK:
            ai_error = self._make_ai_move(game, board)
            if ai_error:
                return Response(
                    {"error": "Failed to generate AI move", "code": "ai_move_error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(GameSerializer(game).data)

    @action(detail=True, methods=['get'])
    def analysis(self, request, pk=None):
        game = self.get_object()

        if not settings.ANALYSIS_FEATURE_ENABLED:
            return Response(
                {"error": "Analysis engine unavailable", "code": "analysis_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            analysis_service = GameAnalysisService()
            payload = analysis_service.analyze_game(game)
            return Response(payload)
        except AnalysisTooShortError as exc:
            return Response(
                {
                    "error": "Not enough moves to analyze",
                    "code": "analysis_too_short",
                    "min_plies": exc.min_plies,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AnalysisUnavailableError:
            return Response(
                {"error": "Analysis engine unavailable", "code": "analysis_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception('analysis_failed game_id=%s', game.id)
            return Response(
                {"error": "Failed to analyze game", "code": "analysis_failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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

    def _make_ai_move(self, game, board):
        if game.black_player_type == 'stockfish':
            return self._make_stockfish_move(game, board)
        if game.black_player_type == 'llm':
            return self._make_llm_move(game, board)
        return None

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

    def _make_llm_move(self, game, board):
        config = game.black_player_config or {}
        provider = config.get('provider')
        model = (config.get('custom_model') or config.get('model') or '').strip()
        started = time.monotonic()
        try:
            client = self._build_llm_client(provider, model)
            player = LLMPlayer(
                name=f'LLM ({provider}:{model})',
                client=client,
                color=chess.BLACK,
            )
            move = player.get_move(board)
            if move not in board.legal_moves:
                raise ValueError('LLM generated illegal move')

            self._append_san_to_pgn(game, board, move)
            board.push(move)
            self._update_game_state(game, board)
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                'llm_move provider=%s model=%s attempts=%s fallback=%s latency_ms=%s',
                provider,
                model,
                player.last_attempt_count,
                player.used_fallback,
                latency_ms,
            )
            return None
        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.exception(
                'llm_move_error provider=%s model=%s latency_ms=%s error=%s',
                provider,
                model,
                latency_ms,
                e,
            )
            print(f"Error LLM move: {e}")
            return e

    def _build_llm_client(self, provider, model):
        timeout = settings.LLM_MOVE_TIMEOUT_SECONDS
        if provider == 'openai':
            return OpenAIClient(settings.OPENAI_API_KEY, model=model, timeout=timeout)
        if provider == 'anthropic':
            return AnthropicClient(settings.ANTHROPIC_API_KEY, model=model, timeout=timeout)
        if provider == 'gemini':
            return GeminiClient(settings.GEMINI_API_KEY, model=model, timeout=timeout)
        if provider == 'local':
            return LocalClient(
                model=model,
                base_url=settings.LOCAL_LLM_BASE_URL,
                timeout=timeout,
            )
        raise ValueError(f'Unsupported LLM provider: {provider}')
