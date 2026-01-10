# DeepSquare

DeepSquare is a full-stack AI Chess Platform built with **Django** and **React**. It features a premium glassmorphic UI, real-time move history, and integration with the **Stockfish** chess engine.

## Features

- **Backend**: Django REST Framework API.
- **Frontend**: React + Vite with a modern "Glassmorphism" design.
- **AI Opponents**:
  - **Stockfish**: Play against the world's strongest open-source engine.
  - **Mock AI**: Framework for future LLM integration.
- **Live Updates**: Real-time board state, move validation, and PGN move history.

## Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- Stockfish (installed via Homebrew on Mac: `brew install stockfish`)

### 1. Backend Setup
```bash
# Clone the repo
git clone https://github.com/liampotts/DeepSquare.git
cd DeepSquare

# Create and activate virtual env
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
cd server
python manage.py migrate

# Start server (runs on port 8001)
python manage.py runserver 8001
```

### 2. Frontend Setup
```bash
# Open a new terminal
cd DeepSquare/client

# Install dependencies
npm install

# Start development server
npm run dev
```

Visit `http://localhost:5173` to play!

## Project Structure
- `server/`: Django backend.
  - `api/`: Main application logic (Game models, Views, Engine wrappers).
  - `api/players/`: Player implementations (Human, Stockfish, LLM).
- `client/`: React frontend.
  - `src/App.jsx`: Main UI logic.
  - `src/index.css`: Global theme (Dark mode).

## License
MIT
