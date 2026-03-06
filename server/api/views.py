from concurrent.futures import ThreadPoolExecutor
import logging
import time

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.utils import timezone
from .models import ArenaRun, Game
from .serializers import (
    ArenaRunCreateSerializer,
    ArenaRunSerializer,
    ArenaSimulationSerializer,
    GameSerializer,
    MoveSerializer,
)
from .arena import ArenaSimulationService
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
arena_executor = ThreadPoolExecutor(max_workers=2)


def build_llm_client(provider, model):
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


def serializer_error_response(errors):
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


def compact_arena_result(result, include_games=False):
    if include_games:
        return result
    if not isinstance(result, dict):
        return result
    compact = dict(result)
    if isinstance(compact.get('games'), list):
        compact.pop('games')
    return compact


def process_arena_run(run_id):
    run = ArenaRun.objects.get(pk=run_id)
    run.status = ArenaRun.STATUS_RUNNING
    run.started_at = timezone.now()
    run.error = ''
    run.save(update_fields=['status', 'started_at', 'error', 'updated_at'])

    config = run.config or {}
    service = ArenaSimulationService(build_llm_client=build_llm_client)

    try:
        result = service.run(
            player_a_config=config['player_a'],
            player_b_config=config['player_b'],
            num_games=config['num_games'],
            max_plies=config['max_plies'],
            alternate_colors=config['alternate_colors'],
        )
        run.result = result
        run.status = ArenaRun.STATUS_COMPLETED
        run.finished_at = timezone.now()
        run.save(update_fields=['result', 'status', 'finished_at', 'updated_at'])
    except Exception as exc:
        logger.exception('arena_run_failed id=%s', run_id)
        run.status = ArenaRun.STATUS_FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error', 'finished_at', 'updated_at'])


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
            return serializer_error_response(serializer.errors)

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

        ai_error, _ = self._play_ai_turns(game, board, max_plies=2)
        if ai_error:
            return Response(
                {"error": "Failed to generate AI move", "code": "ai_move_error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(GameSerializer(game).data)

    @action(detail=True, methods=['post'])
    def autoplay(self, request, pk=None):
        game = self.get_object()
        board = chess.Board(game.fen)

        if board.is_game_over():
            payload = GameSerializer(game).data
            payload['autoplay_plies'] = 0
            return Response(payload)

        try:
            requested_max = int(request.data.get('max_plies', 40))
        except (TypeError, ValueError):
            requested_max = 40
        max_plies = max(1, min(requested_max, 200))

        ai_error, played_plies = self._play_ai_turns(game, board, max_plies=max_plies)
        if ai_error:
            return Response(
                {"error": "Failed to generate AI move", "code": "ai_move_error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        payload = GameSerializer(game).data
        payload['autoplay_plies'] = played_plies
        return Response(payload)

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
        player_type = self._player_type_for_turn(game, board)
        if player_type == 'stockfish':
            return self._make_stockfish_move(game, board)
        if player_type == 'llm':
            return self._make_llm_move(game, board)
        return None

    def _play_ai_turns(self, game, board, max_plies):
        played_plies = 0
        while not board.is_game_over() and played_plies < max_plies:
            if self._player_type_for_turn(game, board) == 'human':
                break
            ai_error = self._make_ai_move(game, board)
            if ai_error:
                return ai_error, played_plies
            played_plies += 1
        return None, played_plies

    def _player_type_for_turn(self, game, board):
        if board.turn == chess.WHITE:
            return game.white_player_type
        return game.black_player_type

    def _player_config_for_turn(self, game, board):
        if board.turn == chess.WHITE:
            return game.white_player_config or {}
        return game.black_player_config or {}

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
        config = self._player_config_for_turn(game, board)
        provider = config.get('provider')
        model = (config.get('custom_model') or config.get('model') or '').strip()
        ttc_policy = config.get('ttc_policy') or {}
        started = time.monotonic()
        try:
            client = self._build_llm_client(provider, model)
            verifier_client = self._build_aux_llm_client(
                provider=ttc_policy.get('verifier_provider'),
                model=ttc_policy.get('verifier_model'),
            )
            fallback_client = self._build_aux_llm_client(
                provider=ttc_policy.get('fallback_provider'),
                model=ttc_policy.get('fallback_model'),
            )
            player = LLMPlayer(
                name=f'LLM ({provider}:{model})',
                client=client,
                color=board.turn,
                max_attempts=ttc_policy.get('max_attempts', 3),
                ttc_policy=ttc_policy,
                verifier_client=verifier_client,
                fallback_client=fallback_client,
            )
            move = player.get_move(board)
            if move not in board.legal_moves:
                raise ValueError('LLM generated illegal move')

            self._append_san_to_pgn(game, board, move)
            board.push(move)
            self._update_game_state(game, board)
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                'llm_move provider=%s model=%s policy=%s attempts=%s fallback=%s latency_ms=%s',
                provider,
                model,
                ttc_policy.get('name', 'baseline'),
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
        return build_llm_client(provider, model)

    def _build_aux_llm_client(self, *, provider, model):
        if not provider or not model:
            return None
        return self._build_llm_client(provider, model)


class ArenaSimulateView(APIView):
    authentication_classes = []

    def post(self, request):
        serializer = ArenaSimulationSerializer(data=request.data)
        if not serializer.is_valid():
            return serializer_error_response(serializer.errors)

        payload = serializer.validated_data
        service = ArenaSimulationService(build_llm_client=build_llm_client)
        result = service.run(
            player_a_config=payload['player_a'],
            player_b_config=payload['player_b'],
            num_games=payload['num_games'],
            max_plies=payload['max_plies'],
            alternate_colors=payload['alternate_colors'],
        )
        return Response(result)


class ArenaRunsView(APIView):
    authentication_classes = []

    def get(self, request):
        include_games = request.query_params.get('include_games') == '1'
        limit_raw = request.query_params.get('limit', '20')
        try:
            limit = max(1, min(int(limit_raw), 100))
        except (TypeError, ValueError):
            limit = 20

        runs = ArenaRun.objects.all().order_by('-created_at')[:limit]
        payload = []
        for run in runs:
            row = ArenaRunSerializer(run).data
            row['result'] = compact_arena_result(row.get('result'), include_games=include_games)
            payload.append(row)

        return Response({'runs': payload})

    def post(self, request):
        serializer = ArenaRunCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return serializer_error_response(serializer.errors)

        payload = dict(serializer.validated_data)
        run_async = bool(payload.pop('run_async', True))
        run = ArenaRun.objects.create(
            status=ArenaRun.STATUS_QUEUED,
            config=payload,
        )

        if run_async:
            arena_executor.submit(process_arena_run, run.id)
            status_code = status.HTTP_202_ACCEPTED
        else:
            process_arena_run(run.id)
            status_code = status.HTTP_201_CREATED

        response = ArenaRunSerializer(ArenaRun.objects.get(pk=run.id)).data
        response['result'] = compact_arena_result(response.get('result'), include_games=False)
        return Response(response, status=status_code)


class ArenaRunDetailView(APIView):
    authentication_classes = []

    def get(self, request, run_id):
        include_games = request.query_params.get('include_games') == '1'
        run = ArenaRun.objects.filter(pk=run_id).first()
        if run is None:
            return Response(
                {'error': 'Arena run not found', 'code': 'arena_run_not_found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = ArenaRunSerializer(run).data
        payload['result'] = compact_arena_result(payload.get('result'), include_games=include_games)
        return Response(payload)
