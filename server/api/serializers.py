from rest_framework import serializers
from django.conf import settings
from .models import ArenaRun, Game
import chess
from .players.ttc_policy import SUPPORTED_TTC_POLICIES


SUPPORTED_PROVIDERS = {'openai', 'anthropic', 'gemini', 'local'}


def provider_is_configured(provider):
    if provider == 'openai':
        return bool(settings.OPENAI_API_KEY)
    if provider == 'anthropic':
        return bool(settings.ANTHROPIC_API_KEY)
    if provider == 'gemini':
        return bool(settings.GEMINI_API_KEY)
    if provider == 'local':
        return bool(settings.LOCAL_LLM_ENABLED)
    return False


def allowed_models(provider):
    if provider == 'openai':
        return settings.LLM_ALLOWED_MODELS_OPENAI
    if provider == 'anthropic':
        return settings.LLM_ALLOWED_MODELS_ANTHROPIC
    if provider == 'gemini':
        return settings.LLM_ALLOWED_MODELS_GEMINI
    if provider == 'local':
        return settings.LLM_ALLOWED_MODELS_LOCAL
    return []


def normalize_ttc_policy(raw_policy):
    if raw_policy in (None, ''):
        return {
            'name': 'baseline',
            'samples': 3,
            'max_attempts': 3,
            'agreement_threshold': 0.67,
            'verifier_provider': '',
            'verifier_model': '',
            'fallback_provider': '',
            'fallback_model': '',
        }

    if not isinstance(raw_policy, dict):
        raise serializers.ValidationError(
            {'error': 'Invalid TTC policy payload', 'code': 'ttc_policy_invalid'}
        )

    name = (raw_policy.get('name') or 'baseline').strip().lower()
    if name not in SUPPORTED_TTC_POLICIES:
        raise serializers.ValidationError(
            {'error': 'Unsupported TTC policy', 'code': 'ttc_policy_unsupported'}
        )

    try:
        samples = int(raw_policy.get('samples', 3))
        max_attempts = int(raw_policy.get('max_attempts', 3))
        agreement_threshold = float(raw_policy.get('agreement_threshold', 0.67))
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError(
            {'error': 'Invalid TTC policy numeric fields', 'code': 'ttc_policy_invalid'}
        ) from exc

    samples = max(1, min(samples, 12))
    max_attempts = max(1, min(max_attempts, 10))
    agreement_threshold = max(0.5, min(agreement_threshold, 1.0))

    verifier_provider = (raw_policy.get('verifier_provider') or '').strip().lower()
    verifier_model = (raw_policy.get('verifier_model') or '').strip()
    fallback_provider = (raw_policy.get('fallback_provider') or '').strip().lower()
    fallback_model = (raw_policy.get('fallback_model') or '').strip()

    if verifier_provider or verifier_model:
        if verifier_provider not in SUPPORTED_PROVIDERS:
            raise serializers.ValidationError(
                {'error': 'Unsupported verifier provider', 'code': 'ttc_verifier_provider_invalid'}
            )
        if not verifier_model:
            raise serializers.ValidationError(
                {'error': 'Verifier model is required', 'code': 'ttc_verifier_model_required'}
            )
        if not provider_is_configured(verifier_provider):
            raise serializers.ValidationError(
                {'error': 'Verifier provider is not configured', 'code': 'ttc_verifier_not_configured'}
            )
        if verifier_model not in allowed_models(verifier_provider):
            raise serializers.ValidationError(
                {'error': 'Verifier model is not in allowlist', 'code': 'ttc_verifier_model_not_allowed'}
            )

    if fallback_provider or fallback_model:
        if fallback_provider not in SUPPORTED_PROVIDERS:
            raise serializers.ValidationError(
                {'error': 'Unsupported fallback provider', 'code': 'ttc_fallback_provider_invalid'}
            )
        if not fallback_model:
            raise serializers.ValidationError(
                {'error': 'Fallback model is required', 'code': 'ttc_fallback_model_required'}
            )
        if not provider_is_configured(fallback_provider):
            raise serializers.ValidationError(
                {'error': 'Fallback provider is not configured', 'code': 'ttc_fallback_not_configured'}
            )
        if fallback_model not in allowed_models(fallback_provider):
            raise serializers.ValidationError(
                {'error': 'Fallback model is not in allowlist', 'code': 'ttc_fallback_model_not_allowed'}
            )

    return {
        'name': name,
        'samples': samples,
        'max_attempts': max_attempts,
        'agreement_threshold': agreement_threshold,
        'verifier_provider': verifier_provider,
        'verifier_model': verifier_model,
        'fallback_provider': fallback_provider,
        'fallback_model': fallback_model,
    }


def normalize_llm_config(raw_config):
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

    if provider not in SUPPORTED_PROVIDERS:
        raise serializers.ValidationError(
            {'error': 'Unsupported LLM provider', 'code': 'llm_provider_invalid'}
        )

    if not provider_is_configured(provider):
        error_message = 'Provider API key is not configured'
        if provider == 'local':
            error_message = 'Local LLM provider is not enabled on this server'
        raise serializers.ValidationError(
            {'error': error_message, 'code': 'llm_provider_not_configured'}
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
    if not custom_model and effective_model not in allowed_models(provider):
        raise serializers.ValidationError(
            {'error': 'Model is not in allowlist', 'code': 'llm_model_not_allowed'}
        )

    ttc_policy = normalize_ttc_policy(raw_config.get('ttc_policy'))
    return {
        'provider': provider,
        'model': model,
        'custom_model': custom_model,
        'ttc_policy': ttc_policy,
    }


class GameSerializer(serializers.ModelSerializer):
    legal_moves = serializers.SerializerMethodField()

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
            'white_player_config',
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
        white_player_type = attrs.get(
            'white_player_type',
            self.instance.white_player_type if self.instance else 'human',
        )
        black_player_type = attrs.get(
            'black_player_type',
            self.instance.black_player_type if self.instance else 'human',
        )
        raw_white_config = attrs.get(
            'white_player_config',
            self.instance.white_player_config if self.instance else {},
        )
        raw_black_config = attrs.get(
            'black_player_config',
            self.instance.black_player_config if self.instance else {},
        )

        if white_player_type != 'llm':
            attrs['white_player_config'] = {}
        else:
            attrs['white_player_config'] = normalize_llm_config(raw_white_config)

        if black_player_type != 'llm':
            attrs['black_player_config'] = {}
        else:
            attrs['black_player_config'] = normalize_llm_config(raw_black_config)
        return attrs


class ArenaSimulationSerializer(serializers.Serializer):
    num_games = serializers.IntegerField(min_value=1, max_value=100)
    max_plies = serializers.IntegerField(min_value=2, max_value=300, default=160)
    alternate_colors = serializers.BooleanField(default=True)
    player_a = serializers.DictField()
    player_b = serializers.DictField()

    def validate(self, attrs):
        player_a = normalize_llm_config(attrs.get('player_a') or {})
        player_b = normalize_llm_config(attrs.get('player_b') or {})

        # Arena is intentionally local-model only for simple setup and predictable costs.
        for player in (player_a, player_b):
            if player.get('provider') != 'local':
                raise serializers.ValidationError(
                    {'error': 'Arena supports local provider only', 'code': 'arena_local_only'}
                )

            policy = player.get('ttc_policy') or {}
            verifier_provider = policy.get('verifier_provider') or ''
            fallback_provider = policy.get('fallback_provider') or ''
            if verifier_provider not in {'', 'local'} or fallback_provider not in {'', 'local'}:
                raise serializers.ValidationError(
                    {'error': 'Arena supports local provider only', 'code': 'arena_local_only'}
                )

        attrs['player_a'] = player_a
        attrs['player_b'] = player_b
        return attrs


class ArenaRunCreateSerializer(ArenaSimulationSerializer):
    run_async = serializers.BooleanField(default=True)


class ArenaRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArenaRun
        fields = [
            'id',
            'status',
            'config',
            'result',
            'error',
            'started_at',
            'finished_at',
            'created_at',
            'updated_at',
        ]


class MoveSerializer(serializers.Serializer):
    move_uci = serializers.RegexField(
        regex=r'^[a-h][1-8][a-h][1-8][qrbn]?$',
        max_length=5,
        error_messages={
            'invalid': 'Move must be valid UCI format: e2e4 or e7e8q.',
        },
    )
