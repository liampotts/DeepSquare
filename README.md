# DeepSquare

DeepSquare is a full-stack chess app with a Django REST backend and a React frontend.  
It supports human and Stockfish games end-to-end, and now includes a configurable multi-provider LLM opponent in the backend API.

## Current Highlights

- Django REST API for game lifecycle and move validation.
- React + Vite chess UI with move history, captures, promotion flow, and board interaction UX.
- AI opponent support:
  - `stockfish` (local binary via UCI).
  - `llm` (OpenAI, Anthropic, Gemini, and local Ollama via provider adapters).
- New server endpoint: `GET /api/ai/options/` for model allowlists and advanced toggle.
- New server endpoint: `GET /api/games/{id}/analysis/` for on-demand performance Elo and move-quality analysis.
- LLM game creation with structured config in `black_player_config`.
- Structured error codes for invalid move and invalid LLM configuration paths.

## Prerequisites

- Python 3.10+
- Node.js 18+
- Stockfish installed and available on `PATH` (macOS example: `brew install stockfish`)

## Quick Start

### 1. Clone + Python setup

```bash
git clone https://github.com/liampotts/DeepSquare.git
cd DeepSquare

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If Django packages are not already installed in your environment, install them once:

```bash
pip install django djangorestframework django-cors-headers
```

### 2. Run backend

```bash
cd server
python manage.py migrate
python manage.py runserver 8001
```

Backend base URL: `http://localhost:8001/api`

### 3. Run frontend

```bash
cd client
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

## LLM Configuration (Backend)

The backend reads these environment variables from your shell:

- `LLM_FEATURE_ENABLED` (default: `true`)
- `OPENAI_API_KEY` (default: empty)
- `ANTHROPIC_API_KEY` (default: empty)
- `GEMINI_API_KEY` (default: empty)
- `LOCAL_LLM_ENABLED` (default: `true`)
- `LOCAL_LLM_BASE_URL` (default: `http://127.0.0.1:11434`)
- `LLM_ALLOWED_MODELS_OPENAI` (CSV, default: `gpt-4.1-mini,gpt-4o-mini`)
- `LLM_ALLOWED_MODELS_ANTHROPIC` (CSV, default: `claude-3-5-sonnet-latest,claude-3-5-haiku-latest`)
- `LLM_ALLOWED_MODELS_GEMINI` (CSV, default: `gemini-1.5-pro,gemini-1.5-flash`)
- `LLM_ALLOWED_MODELS_LOCAL` (CSV, default: `llama3.1:8b`)
- `LLM_ADVANCED_CUSTOM_MODEL_ENABLED` (default: `true`)
- `LLM_MOVE_TIMEOUT_SECONDS` (default: `15`)
- `ANALYSIS_FEATURE_ENABLED` (default: `true`)
- `ANALYSIS_PROFILE_DEFAULT` (default: `balanced`)
- `ANALYSIS_MIN_PLIES` (default: `8`)
- `ANALYSIS_MAX_PLIES` (default: `160`)
- `ANALYSIS_TIME_LIMIT_SECONDS_BALANCED` (default: `0.10`)
- `ANALYSIS_KEY_MOVES_LIMIT` (default: `5`)
- `ANALYSIS_TURNING_POINTS_LIMIT` (default: `3`)

Example:

```bash
export LLM_FEATURE_ENABLED=true
export OPENAI_API_KEY=your_key_here
export LLM_ALLOWED_MODELS_OPENAI=gpt-4.1-mini,gpt-4o-mini
export LOCAL_LLM_ENABLED=true
export LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
export LLM_ALLOWED_MODELS_LOCAL=llama3.1:8b
export ANALYSIS_FEATURE_ENABLED=true
export ANALYSIS_PROFILE_DEFAULT=balanced
```

## API Quick Reference

All endpoints are under `/api`.

### Create game

`POST /api/games/`

Human vs human:

```json
{
  "white_player_type": "human",
  "black_player_type": "human"
}
```

Human vs Stockfish:

```json
{
  "white_player_type": "human",
  "black_player_type": "stockfish"
}
```

Human vs LLM:

```json
{
  "white_player_type": "human",
  "black_player_type": "llm",
  "black_player_config": {
    "provider": "local",
    "model": "llama3.1:8b",
    "custom_model": ""
  }
}
```

### Submit move

`POST /api/games/{id}/move/`

```json
{
  "move_uci": "e2e4"
}
```

If black is an AI player, the server makes the black move automatically after the white move.

### Query AI options

`GET /api/ai/options/`

Response:

```json
{
  "providers": {
    "openai": ["gpt-4.1-mini", "gpt-4o-mini"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash"],
    "local": ["llama3.1:8b"]
  },
  "advanced_custom_model_enabled": true
}
```

### Analyze game quality and performance

`GET /api/games/{id}/analysis/`

Response:

```json
{
  "game_id": 12,
  "analysis_profile": "balanced",
  "analyzed_plies": 24,
  "white": {
    "estimated_elo": 1710,
    "accuracy_percent": 79,
    "avg_centipawn_loss": 58,
    "move_counts": { "best": 7, "good": 8, "inaccuracy": 2, "mistake": 1, "blunder": 0 }
  },
  "black": {
    "estimated_elo": 1630,
    "accuracy_percent": 74,
    "avg_centipawn_loss": 70,
    "move_counts": { "best": 6, "good": 7, "inaccuracy": 3, "mistake": 2, "blunder": 0 }
  },
  "key_moves": [
    {
      "ply": 19,
      "side": "white",
      "san": "Qe2",
      "uci": "d1e2",
      "category": "mistake",
      "cp_loss": 162,
      "eval_before_cp": 34,
      "eval_after_cp": -128,
      "commentary": "Major inaccuracy that shifted momentum toward the opponent."
    }
  ],
  "turning_points": [
    {
      "ply": 20,
      "side": "black",
      "san": "Nxd4",
      "swing_cp": 190,
      "commentary": "This move produced one of the largest evaluation swings in the game."
    }
  ],
  "summary": "Detailed narrative summary ...",
  "reliability": {
    "sufficient_sample": true,
    "note": "Performance Elo estimate for this game only."
  }
}
```

## Error Codes

Move errors:

- `invalid_uci`
- `illegal_move`
- `game_over`
- `ai_move_error`

Analysis errors:

- `analysis_too_short`
- `analysis_unavailable`
- `analysis_failed`

LLM configuration errors:

- `llm_feature_disabled`
- `llm_config_invalid`
- `llm_provider_invalid`
- `llm_provider_not_configured`
- `llm_model_required`
- `llm_custom_model_disabled`
- `llm_model_not_allowed`

## FastAPI Evaluation

DeepSquare keeps this analysis feature in Django REST Framework for now.

Why DRF now:
- Existing API surface and serializer contracts already live in DRF.
- A second framework would add deployment and testing complexity without current scale pressure.
- This feature reuses existing game data flow directly.

When FastAPI could make sense later:
- sustained high analysis traffic,
- need for a dedicated async analysis worker service,
- desire to split analysis into an independently scalable API process.

## Tests

Backend API and LLM behavior tests:

```bash
cd server
python manage.py test api
```

## Project Structure

- `server/`
- `server/api/`
- `server/api/players/`
- `client/`
- `client/src/App.jsx`

## License

MIT
