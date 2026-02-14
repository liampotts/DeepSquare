from rest_framework import serializers
from django.conf import settings
from .models import Game
import chess


class GameSerializer(serializers.ModelSerializer):
    legal_moves = serializers.SerializerMethodField()
    SUPPORTED_PROVIDERS = {'openai', 'anthropic', 'gemini'}

    class Meta:
        model = Game
        fields = [
            'id',
            'fen',
            'pgn',
            'is_game_over',
            'winner',
            'white_player_type',
            'black_player_type',
            'black_player_config',
            'legal_moves',
            'created_at',
        ]

    def get_legal_moves(self, obj):
        board = chess.Board(obj.fen)
        if board.is_game_over():
            return []
        return [move.uci() for move in board.legal_moves]

    def validate(self, attrs):
        black_player_type = attrs.get(
            'black_player_type',
            self.instance.black_player_type if self.instance else 'human',
        )
        raw_config = attrs.get(
            'black_player_config',
            self.instance.black_player_config if self.instance else {},
        )

        if black_player_type != 'llm':
            attrs['black_player_config'] = {}
            return attrs

        if not settings.LLM_FEATURE_ENABLED:
            raise serializers.ValidationError(
                {'error': 'LLM opponents are disabled', 'code': 'llm_feature_disabled'}
            )

        if not isinstance(raw_config, dict):
            raise serializers.ValidationError(
                {'error': 'Invalid LLM config payload', 'code': 'llm_config_invalid'}
            )

        provider = (raw_config.get('provider') or '').strip().lower()
        model = (raw_config.get('model') or '').strip()
        custom_model = (raw_config.get('custom_model') or '').strip()

        if provider not in self.SUPPORTED_PROVIDERS:
            raise serializers.ValidationError(
                {'error': 'Unsupported LLM provider', 'code': 'llm_provider_invalid'}
            )

        if not self._provider_has_key(provider):
            raise serializers.ValidationError(
                {'error': 'Provider API key is not configured', 'code': 'llm_provider_not_configured'}
            )

        if not model:
            raise serializers.ValidationError(
                {'error': 'Model is required for LLM games', 'code': 'llm_model_required'}
            )

        if custom_model and not settings.LLM_ADVANCED_CUSTOM_MODEL_ENABLED:
            raise serializers.ValidationError(
                {'error': 'Custom model override is disabled', 'code': 'llm_custom_model_disabled'}
            )

        effective_model = custom_model or model
        if not custom_model and effective_model not in self._allowed_models(provider):
            raise serializers.ValidationError(
                {'error': 'Model is not in allowlist', 'code': 'llm_model_not_allowed'}
            )

        attrs['black_player_config'] = {
            'provider': provider,
            'model': model,
            'custom_model': custom_model,
        }
        return attrs

    def _provider_has_key(self, provider):
        if provider == 'openai':
            return bool(settings.OPENAI_API_KEY)
        if provider == 'anthropic':
            return bool(settings.ANTHROPIC_API_KEY)
        if provider == 'gemini':
            return bool(settings.GEMINI_API_KEY)
        return False

    def _allowed_models(self, provider):
        if provider == 'openai':
            return settings.LLM_ALLOWED_MODELS_OPENAI
        if provider == 'anthropic':
            return settings.LLM_ALLOWED_MODELS_ANTHROPIC
        if provider == 'gemini':
            return settings.LLM_ALLOWED_MODELS_GEMINI
        return []


class MoveSerializer(serializers.Serializer):
    move_uci = serializers.RegexField(
        regex=r'^[a-h][1-8][a-h][1-8][qrbn]?$',
        max_length=5,
        error_messages={
            'invalid': 'Move must be valid UCI format: e2e4 or e7e8q.',
        },
    )
