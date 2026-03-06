import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import axios from 'axios'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || (import.meta.env.DEV ? 'http://127.0.0.1:8001/api' : '/api')

const PROMOTION_OPTIONS = ['q', 'r', 'b', 'n']
const STOCKFISH_ESTIMATED_ELO = '~2500 (0.5s/move)'
const ANALYSIS_MIN_PLIES = 8
const PIECE_VALUES = {
  p: 1,
  n: 3,
  b: 3,
  r: 5,
  q: 9,
  k: 0,
}
const PROVIDER_LABELS = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
  local: 'Local (Ollama)',
}
const DEFAULT_AI_OPTIONS = {
  providers: {},
  advanced_custom_model_enabled: false,
}
const TTC_POLICY_OPTIONS = [
  { value: 'baseline', label: 'Baseline' },
  { value: 'self_consistency', label: 'Self-Consistency' },
  { value: 'verifier', label: 'Verifier' },
  { value: 'uncertainty_fallback', label: 'Uncertainty Fallback' },
]

const createArenaPlayer = () => ({
  provider: 'local',
  model: '',
  customModel: '',
  policyName: 'baseline',
  samples: 3,
  maxAttempts: 3,
  agreementThreshold: 0.67,
  verifierProvider: '',
  verifierModel: '',
  fallbackProvider: '',
  fallbackModel: '',
})

const normalizeArenaPlayer = (player, providersMap) => {
  const localModels = (providersMap || {}).local || []
  if (localModels.length === 0) {
    return {
      ...player,
      provider: '',
      model: '',
      verifierProvider: '',
      verifierModel: '',
      fallbackProvider: '',
      fallbackModel: '',
    }
  }

  const provider = 'local'
  const model = localModels.includes(player.model) ? player.model : localModels[0] || ''

  let verifierModel = player.verifierModel
  if (verifierModel && !localModels.includes(verifierModel)) {
    verifierModel = localModels[0] || ''
  }

  let fallbackModel = player.fallbackModel
  if (fallbackModel && !localModels.includes(fallbackModel)) {
    fallbackModel = localModels[0] || ''
  }

  return {
    ...player,
    provider,
    model,
    verifierProvider: verifierModel ? 'local' : '',
    verifierModel,
    fallbackProvider: fallbackModel ? 'local' : '',
    fallbackModel,
  }
}

const buildTtcPolicyConfig = (player) => ({
  name: player.policyName,
  samples: Number(player.samples) || 3,
  max_attempts: Number(player.maxAttempts) || 3,
  agreement_threshold: Number(player.agreementThreshold) || 0.67,
  verifier_provider: player.verifierModel ? 'local' : '',
  verifier_model: player.verifierModel,
  fallback_provider: player.fallbackModel ? 'local' : '',
  fallback_model: player.fallbackModel,
})

const buildArenaPayloadPlayer = (player) => ({
  provider: 'local',
  model: player.model,
  custom_model: player.customModel.trim(),
  ttc_policy: buildTtcPolicyConfig(player),
})

const percentText = (value) => `${Math.round((Number(value) || 0) * 100)}%`

const getOpponentProfile = (blackPlayerType, blackPlayerConfig = {}) => {
  if (blackPlayerType === 'human') {
    return {
      title: 'Human Opponent',
      details: ['Another player controls the black pieces.'],
      estimatedElo: null,
    }
  }

  if (blackPlayerType === 'stockfish') {
    return {
      title: 'Stockfish Engine',
      details: [
        'Engine: Stockfish (UCI)',
        'Runtime: Local server binary',
        'Strength profile: ~0.5s search per move',
      ],
      estimatedElo: STOCKFISH_ESTIMATED_ELO,
    }
  }

  if (blackPlayerType === 'llm') {
    const provider = (blackPlayerConfig.provider || '').toLowerCase()
    const effectiveModel = blackPlayerConfig.custom_model || blackPlayerConfig.model || 'Unknown model'
    const runtimeDetail =
      provider === 'local' ? 'Runtime: local model server (no external API required)' : null
    return {
      title: 'LLM Opponent',
      details: [
        `Provider: ${PROVIDER_LABELS[provider] || provider || 'Unknown provider'}`,
        `Model: ${effectiveModel}`,
        ...(runtimeDetail ? [runtimeDetail] : []),
        'Move policy: constrained legal-move selection',
      ],
      estimatedElo: 'Experimental / model-dependent',
    }
  }

  return {
    title: blackPlayerType || 'Unknown Opponent',
    details: ['No additional details available.'],
    estimatedElo: null,
  }
}

const getPieceIcon = (pieceChar) => {
  const icons = {
    p: '♟',
    n: '♞',
    b: '♝',
    r: '♜',
    q: '♛',
    k: '♚',
  }
  return icons[pieceChar] || pieceChar
}

const getMaterialScore = (chessGame) => {
  const board = chessGame.board()
  let score = 0

  for (const row of board) {
    for (const square of row) {
      if (!square) continue
      const value = PIECE_VALUES[square.type] || 0
      score += square.color === 'w' ? value : -value
    }
  }

  return score
}

const getPositionStrengthLabel = (score) => {
  if (score >= 3) return `White clearly better (+${score})`
  if (score >= 1) return `White slightly better (+${score})`
  if (score <= -3) return `Black clearly better (${score})`
  if (score <= -1) return `Black slightly better (${score})`
  return 'Roughly equal (0)'
}

const createGameFromSnapshot = (snapshot) => {
  const nextGame = new Chess()
  if (snapshot.prevPgn) {
    nextGame.loadPgn(snapshot.prevPgn)
  } else {
    nextGame.load(snapshot.prevFen)
  }
  return nextGame
}

const createGameFromServer = (gameData) => {
  const nextGame = new Chess()
  if (gameData.pgn) {
    try {
      nextGame.loadPgn(gameData.pgn)
    } catch {
      nextGame.load(gameData.fen)
    }
  } else {
    nextGame.load(gameData.fen)
  }
  return nextGame
}

function App() {
  const [game, setGame] = useState(new Chess())
  const [gameId, setGameId] = useState(null)
  const [fen, setFen] = useState(game.fen())
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('Select a mode to start')
  const [selectedSquare, setSelectedSquare] = useState(null)
  const [legalTargetSquares, setLegalTargetSquares] = useState([])
  const [pendingPromotion, setPendingPromotion] = useState(null)
  const [isSubmittingMove, setIsSubmittingMove] = useState(false)
  const [moveError, setMoveError] = useState(null)
  const [opponentProfile, setOpponentProfile] = useState(null)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState(null)

  const [aiOptions, setAiOptions] = useState(DEFAULT_AI_OPTIONS)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [customModelOverride, setCustomModelOverride] = useState('')
  const [aiOptionsError, setAiOptionsError] = useState(null)
  const [activeTab, setActiveTab] = useState('play')

  const [arenaPlayerA, setArenaPlayerA] = useState(createArenaPlayer)
  const [arenaPlayerB, setArenaPlayerB] = useState(createArenaPlayer)
  const [arenaNumGames, setArenaNumGames] = useState(20)
  const [arenaMaxPlies, setArenaMaxPlies] = useState(120)
  const [arenaAlternateColors, setArenaAlternateColors] = useState(true)
  const [arenaRunId, setArenaRunId] = useState(null)
  const [arenaRunStatus, setArenaRunStatus] = useState('idle')
  const [arenaRunResult, setArenaRunResult] = useState(null)
  const [arenaRunError, setArenaRunError] = useState(null)
  const [arenaSubmitting, setArenaSubmitting] = useState(false)
  const [arenaRecentRuns, setArenaRecentRuns] = useState([])

  const [liveArenaGame, setLiveArenaGame] = useState(new Chess())
  const [liveArenaFen, setLiveArenaFen] = useState(new Chess().fen())
  const [liveArenaGameId, setLiveArenaGameId] = useState(null)
  const [liveArenaStatus, setLiveArenaStatus] = useState('No live LLM arena game started.')
  const [liveArenaBusy, setLiveArenaBusy] = useState(false)
  const [liveArenaError, setLiveArenaError] = useState(null)
  const [liveArenaAuto, setLiveArenaAuto] = useState(false)

  const gameRef = useRef(game)
  const gameIdRef = useRef(gameId)
  const liveArenaBusyRef = useRef(false)
  const arenaPollRef = useRef(null)

  useEffect(() => {
    gameRef.current = game
  }, [game])

  useEffect(() => {
    gameIdRef.current = gameId
  }, [gameId])

  useEffect(() => {
    liveArenaBusyRef.current = liveArenaBusy
  }, [liveArenaBusy])

  useEffect(() => {
    let cancelled = false

    const fetchAiOptions = async () => {
      try {
        const response = await axios.get(`${API_BASE}/ai/options/`)
        const options = {
          providers: response.data?.providers || {},
          advanced_custom_model_enabled: Boolean(response.data?.advanced_custom_model_enabled),
        }

        if (cancelled) return

        setAiOptions(options)
        setAiOptionsError(null)

        const providers = Object.keys(options.providers)
        if (providers.length === 0) {
          setSelectedProvider('')
          setSelectedModel('')
          setAiOptionsError('LLM opponents are currently unavailable on this server.')
          return
        }

        const defaultProvider = providers[0]
        setSelectedProvider(defaultProvider)
        setSelectedModel(options.providers[defaultProvider]?.[0] || '')
        setArenaPlayerA((previous) =>
          normalizeArenaPlayer(previous, options.providers, providers[0]),
        )
        setArenaPlayerB((previous) =>
          normalizeArenaPlayer(previous, options.providers, providers[1] || providers[0]),
        )
      } catch {
        if (cancelled) return
        setAiOptions(DEFAULT_AI_OPTIONS)
        setAiOptionsError('Failed to load LLM options.')
      }
    }

    void fetchAiOptions()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedProvider) return
    const models = aiOptions.providers[selectedProvider] || []
    if (models.length === 0) {
      if (selectedModel !== '') {
        setSelectedModel('')
      }
      return
    }
    if (!models.includes(selectedModel)) {
      setSelectedModel(models[0])
    }
  }, [aiOptions.providers, selectedProvider, selectedModel])

  useEffect(() => {
    const providers = aiOptions.providers || {}
    const providerKeys = Object.keys(providers)
    if (providerKeys.length === 0) return
    setArenaPlayerA((previous) => normalizeArenaPlayer(previous, providers, providerKeys[0]))
    setArenaPlayerB((previous) =>
      normalizeArenaPlayer(previous, providers, providerKeys[1] || providerKeys[0]),
    )
  }, [aiOptions.providers])

  const clearSelection = () => {
    setSelectedSquare(null)
    setLegalTargetSquares([])
  }

  const syncLocalGame = (nextGame) => {
    setGame(nextGame)
    gameRef.current = nextGame
    setFen(nextGame.fen())
  }

  const getGameSnapshot = (chessGame) => ({
    prevPgn: chessGame.pgn(),
    prevFen: chessGame.fen(),
  })

  const getLegalMovesFromSquare = (chessGame, square) => {
    const legalMoves = chessGame.moves({ square, verbose: true })
    const targets = new Set(legalMoves.map((move) => move.to))
    return [...targets]
  }

  const selectSquare = (square) => {
    const currentGame = gameRef.current
    const piece = currentGame.get(square)
    if (!piece || piece.color !== currentGame.turn()) {
      clearSelection()
      return
    }

    setSelectedSquare(square)
    setLegalTargetSquares(getLegalMovesFromSquare(currentGame, square))
    setMoveError(null)
  }

  const hydrateFromServer = (gameData) => {
    const nextGame = createGameFromServer(gameData)
    syncLocalGame(nextGame)
    setOpponentProfile(getOpponentProfile(gameData.black_player_type, gameData.black_player_config || {}))
    setAnalysisResult(null)
    setAnalysisError(null)

    if (gameData.is_game_over) {
      setStatus(`Game Over! Winner: ${gameData.winner}`)
    }
  }

  const makeMove = async (moveUci, prevState, currentGameId = gameIdRef.current) => {
    if (!currentGameId) return

    setIsSubmittingMove(true)
    setMoveError(null)
    setAnalysisError(null)

    try {
      const response = await axios.post(`${API_BASE}/games/${currentGameId}/move/`, {
        move_uci: moveUci,
      })
      hydrateFromServer(response.data)
    } catch (error) {
      const rollbackGame = createGameFromSnapshot(prevState)
      syncLocalGame(rollbackGame)
      setMoveError(error.response?.data?.error || 'Error making move')
    } finally {
      setIsSubmittingMove(false)
    }
  }

  const executeMove = (sourceSquare, targetSquare, promotion = null) => {
    const currentGame = gameRef.current
    const activeGameId = gameIdRef.current

    if (!currentGame || !activeGameId) return false

    const prevState = getGameSnapshot(currentGame)
    const tempGame = createGameFromSnapshot(prevState)

    const moveInput = {
      from: sourceSquare,
      to: targetSquare,
    }

    if (promotion) {
      moveInput.promotion = promotion
    }

    const move = tempGame.move(moveInput)
    if (!move) return false

    syncLocalGame(tempGame)
    clearSelection()
    setPendingPromotion(null)

    const promotionSuffix = move.promotion || ''
    const moveUci = `${move.from}${move.to}${promotionSuffix}`
    void makeMove(moveUci, prevState, activeGameId)
    return true
  }

  const attemptMove = (sourceSquare, targetSquare) => {
    const activeGameId = gameIdRef.current
    const currentGame = gameRef.current

    if (!activeGameId || !currentGame || isSubmittingMove || currentGame.isGameOver()) {
      return false
    }

    const candidates = currentGame
      .moves({ verbose: true })
      .filter((move) => move.from === sourceSquare && move.to === targetSquare)

    if (candidates.length === 0) {
      setMoveError('Illegal move')
      return false
    }

    if (candidates.some((move) => move.promotion)) {
      setPendingPromotion({ sourceSquare, targetSquare })
      setMoveError(null)
      return false
    }

    return executeMove(sourceSquare, targetSquare)
  }

  const handlePieceDrop = ({ sourceSquare, targetSquare }) => {
    if (!sourceSquare || !targetSquare) return false
    return attemptMove(sourceSquare, targetSquare)
  }

  const handleSquareClick = ({ piece, square }) => {
    const currentGame = gameRef.current
    const activeGameId = gameIdRef.current

    if (!activeGameId || !currentGame || isSubmittingMove || currentGame.isGameOver() || pendingPromotion) {
      return
    }

    if (selectedSquare && legalTargetSquares.includes(square)) {
      attemptMove(selectedSquare, square)
      return
    }

    if (selectedSquare && square !== selectedSquare) {
      if (piece && piece.pieceType && piece.pieceType[0] === currentGame.turn()) {
        selectSquare(square)
        return
      }
      setMoveError('Illegal move')
      clearSelection()
      return
    }

    if (selectedSquare === square) {
      clearSelection()
      return
    }

    if (piece && piece.pieceType && piece.pieceType[0] === currentGame.turn()) {
      selectSquare(square)
      return
    }

    clearSelection()
  }

  const handlePromotionChoice = (promotion) => {
    if (!pendingPromotion) return
    executeMove(pendingPromotion.sourceSquare, pendingPromotion.targetSquare, promotion)
  }

  const handlePromotionCancel = () => {
    setPendingPromotion(null)
    clearSelection()
  }

  const startGame = async ({ blackPlayerType, blackPlayerConfig = null }) => {
    setLoading(true)
    setMoveError(null)
    setAnalysisError(null)
    setAnalysisResult(null)
    clearSelection()
    setPendingPromotion(null)

    const payload = {
      white_player_type: 'human',
      black_player_type: blackPlayerType,
    }

    if (blackPlayerType === 'llm') {
      payload.black_player_config = blackPlayerConfig || {}
    }

    try {
      const response = await axios.post(`${API_BASE}/games/`, payload)

      const gameData = response.data
      setGameId(gameData.id)
      gameIdRef.current = gameData.id
      hydrateFromServer(gameData)
      setStatus(`${gameData.white_player_type} vs ${gameData.black_player_type}`)
    } catch (error) {
      console.error('Error starting game', error)
      setStatus('Error starting game')
      setMoveError(error.response?.data?.error || 'Failed to start game')
    } finally {
      setLoading(false)
    }
  }

  const handleStartLlmGame = () => {
    if (!selectedProvider || !selectedModel) {
      setMoveError('Choose an LLM provider and model first.')
      return
    }

    void startGame({
      blackPlayerType: 'llm',
      blackPlayerConfig: {
        provider: selectedProvider,
        model: selectedModel,
        custom_model: aiOptions.advanced_custom_model_enabled ? customModelOverride.trim() : '',
      },
    })
  }

  const handleAnalyzeGame = async () => {
    const currentGameId = gameIdRef.current
    if (!currentGameId) return

    setIsAnalyzing(true)
    setAnalysisError(null)

    try {
      const response = await axios.get(`${API_BASE}/games/${currentGameId}/analysis/`)
      setAnalysisResult(response.data)
    } catch (error) {
      const message = error.response?.data?.error || 'Failed to analyze game'
      setAnalysisError(message)
    } finally {
      setIsAnalyzing(false)
    }
  }

  const setArenaPlayerField = (side, field, value) => {
    const updater = side === 'a' ? setArenaPlayerA : setArenaPlayerB
    updater((previous) => ({ ...previous, [field]: value }))
  }

  const loadArenaRuns = async () => {
    try {
      const response = await axios.get(`${API_BASE}/arena/runs/?limit=8`)
      setArenaRecentRuns(response.data?.runs || [])
    } catch {
      setArenaRecentRuns([])
    }
  }

  const loadArenaRunDetail = async (runId, includeGames = false) => {
    const response = await axios.get(
      `${API_BASE}/arena/runs/${runId}/?include_games=${includeGames ? '1' : '0'}`,
    )
    const payload = response.data
    setArenaRunStatus(payload.status || 'unknown')
    setArenaRunResult(payload.result || null)
    setArenaRunError(payload.error || null)
    return payload
  }

  const handleRunArenaBatch = async () => {
    const required = [
      [arenaPlayerA.model, 'Player A model'],
      [arenaPlayerB.model, 'Player B model'],
    ]
    const missing = required.find(([value]) => !value)
    if (missing) {
      setArenaRunError(`${missing[1]} is required.`)
      return
    }

    setArenaSubmitting(true)
    setArenaRunError(null)
    setArenaRunResult(null)
    setArenaRunStatus('queued')

    try {
      const payload = {
        run_async: true,
        num_games: Number(arenaNumGames),
        max_plies: Number(arenaMaxPlies),
        alternate_colors: Boolean(arenaAlternateColors),
        player_a: buildArenaPayloadPlayer(arenaPlayerA),
        player_b: buildArenaPayloadPlayer(arenaPlayerB),
      }
      const response = await axios.post(`${API_BASE}/arena/runs/`, payload)
      setArenaRunId(response.data.id)
      setArenaRunStatus(response.data.status || 'queued')
      await loadArenaRuns()
    } catch (error) {
      setArenaRunStatus('failed')
      setArenaRunError(error.response?.data?.error || 'Failed to start arena run.')
    } finally {
      setArenaSubmitting(false)
    }
  }

  const hydrateLiveArenaGame = useCallback((gameData) => {
    const nextGame = createGameFromServer(gameData)
    setLiveArenaGame(nextGame)
    setLiveArenaFen(nextGame.fen())
    if (gameData.is_game_over) {
      setLiveArenaStatus(`Live game complete. Winner: ${gameData.winner}`)
      setLiveArenaAuto(false)
    } else {
      setLiveArenaStatus(
        `Live game #${gameData.id} in progress (${nextGame.history().length} plies).`,
      )
    }
  }, [])

  const handleStartLiveArenaGame = async () => {
    if (!arenaPlayerA.model || !arenaPlayerB.model) {
      setLiveArenaError('Both players must have a local model selected.')
      return
    }

    setLiveArenaBusy(true)
    setLiveArenaError(null)
    setLiveArenaAuto(false)

    try {
      const payload = {
        white_player_type: 'llm',
        black_player_type: 'llm',
        white_player_config: buildArenaPayloadPlayer(arenaPlayerA),
        black_player_config: buildArenaPayloadPlayer(arenaPlayerB),
      }
      const response = await axios.post(`${API_BASE}/games/`, payload)
      setLiveArenaGameId(response.data.id)
      hydrateLiveArenaGame(response.data)
    } catch (error) {
      setLiveArenaError(error.response?.data?.error || 'Failed to start live arena game.')
    } finally {
      setLiveArenaBusy(false)
    }
  }

  const stepLiveArena = useCallback(async (maxPlies = 2) => {
    if (!liveArenaGameId || liveArenaBusyRef.current) return
    liveArenaBusyRef.current = true
    setLiveArenaBusy(true)
    setLiveArenaError(null)
    try {
      const response = await axios.post(`${API_BASE}/games/${liveArenaGameId}/autoplay/`, {
        max_plies: maxPlies,
      })
      hydrateLiveArenaGame(response.data)
    } catch (error) {
      setLiveArenaError(error.response?.data?.error || 'Failed to advance live arena game.')
      setLiveArenaAuto(false)
    } finally {
      liveArenaBusyRef.current = false
      setLiveArenaBusy(false)
    }
  }, [liveArenaGameId, hydrateLiveArenaGame])

  useEffect(() => {
    if (activeTab !== 'arena') return
    void loadArenaRuns()
  }, [activeTab])

  useEffect(() => {
    const isRunning = arenaRunStatus === 'queued' || arenaRunStatus === 'running'
    if (!arenaRunId || !isRunning) {
      if (arenaPollRef.current) {
        clearInterval(arenaPollRef.current)
        arenaPollRef.current = null
      }
      return
    }

    arenaPollRef.current = setInterval(async () => {
      try {
        const payload = await loadArenaRunDetail(arenaRunId, false)
        if (payload.status === 'completed' || payload.status === 'failed') {
          await loadArenaRunDetail(arenaRunId, true)
          await loadArenaRuns()
          if (arenaPollRef.current) {
            clearInterval(arenaPollRef.current)
            arenaPollRef.current = null
          }
        }
      } catch {
        setArenaRunStatus('failed')
        setArenaRunError('Failed to poll arena run status.')
        if (arenaPollRef.current) {
          clearInterval(arenaPollRef.current)
          arenaPollRef.current = null
        }
      }
    }, 2000)

    return () => {
      if (arenaPollRef.current) {
        clearInterval(arenaPollRef.current)
        arenaPollRef.current = null
      }
    }
  }, [arenaRunId, arenaRunStatus])

  useEffect(() => {
    if (!liveArenaAuto || !liveArenaGameId) return
    const intervalId = setInterval(() => {
      void stepLiveArena(2)
    }, 900)
    return () => clearInterval(intervalId)
  }, [liveArenaAuto, liveArenaGameId, stepLiveArena])

  const captures = useMemo(() => {
    const history = game.history({ verbose: true })
    const captured = { w: [], b: [] }

    for (const move of history) {
      if (!move.captured) continue
      if (move.color === 'w') {
        captured.w.push(move.captured)
      } else {
        captured.b.push(move.captured)
      }
    }

    return captured
  }, [game])

  const historyRows = useMemo(() => {
    const history = game.history({ verbose: true })
    const rows = []

    for (let i = 0; i < history.length; i += 2) {
      rows.push({
        num: Math.floor(i / 2) + 1,
        white: history[i],
        black: history[i + 1] || null,
      })
    }

    return rows
  }, [game])

  const positionStrength = useMemo(() => {
    const score = getMaterialScore(game)
    return getPositionStrengthLabel(score)
  }, [game])

  const plyCount = useMemo(() => game.history().length, [game])
  const liveArenaHistoryRows = useMemo(() => {
    const history = liveArenaGame.history({ verbose: true })
    const rows = []
    for (let index = 0; index < history.length; index += 2) {
      rows.push({
        num: Math.floor(index / 2) + 1,
        white: history[index],
        black: history[index + 1] || null,
      })
    }
    return rows
  }, [liveArenaGame])

  const squareStyles = useMemo(() => {
    const styles = {}

    if (selectedSquare) {
      styles[selectedSquare] = {
        boxShadow: 'inset 0 0 0 4px rgba(255, 196, 0, 0.9)',
      }
    }

    for (const square of legalTargetSquares) {
      styles[square] = {
        ...(styles[square] || {}),
        background:
          'radial-gradient(circle at center, rgba(77, 187, 121, 0.7) 0%, rgba(77, 187, 121, 0.18) 60%, transparent 62%)',
      }
    }

    return styles
  }, [selectedSquare, legalTargetSquares])

  const canInteract = Boolean(gameId) && !isSubmittingMove && !game.isGameOver() && !pendingPromotion
  const canAnalyze = Boolean(gameId) && !isAnalyzing && !isSubmittingMove && plyCount >= ANALYSIS_MIN_PLIES
  const localArenaModels = aiOptions.providers.local || []
  const canRunArenaBatch = !arenaSubmitting
    && localArenaModels.length > 0
    && Boolean(arenaPlayerA.model)
    && Boolean(arenaPlayerB.model)

  const boardOptions = {
    id: 'deepsquare-board',
    position: fen,
    onPieceDrop: handlePieceDrop,
    onSquareClick: handleSquareClick,
    squareStyles,
    boardStyle: {
      borderRadius: '4px',
      boxShadow: '0 5px 15px rgba(0, 0, 0, 0.5)',
    },
    darkSquareStyle: { backgroundColor: '#779556' },
    lightSquareStyle: { backgroundColor: '#ebecd0' },
    canDragPiece: ({ piece }) => {
      if (!canInteract) return false
      return piece?.pieceType?.[0] === game.turn()
    },
  }

  const liveArenaBoardOptions = {
    id: 'deepsquare-arena-board',
    position: liveArenaFen,
    arePiecesDraggable: false,
    boardStyle: {
      borderRadius: '4px',
      boxShadow: '0 5px 15px rgba(0, 0, 0, 0.5)',
    },
    darkSquareStyle: { backgroundColor: '#779556' },
    lightSquareStyle: { backgroundColor: '#ebecd0' },
  }

  return (
    <div className="app-container">
      <h1 className="title">DeepSquare</h1>

      <div className="tab-strip">
        <button
          type="button"
          className={`tab-button ${activeTab === 'play' ? 'active' : ''}`}
          onClick={() => setActiveTab('play')}
        >
          Play
        </button>
        <button
          type="button"
          className={`tab-button ${activeTab === 'arena' ? 'active' : ''}`}
          onClick={() => setActiveTab('arena')}
        >
          Arena
        </button>
      </div>

      {activeTab === 'play' ? (
        <div className="game-layout">
          <div className="glass-panel controls-panel">
            <h3>Game Mode</h3>
            <div className="mode-select">
              <button
                onClick={() => startGame({ blackPlayerType: 'human' })}
                disabled={loading || isSubmittingMove}
              >
                Play vs Friend
              </button>
              <button
                onClick={() => startGame({ blackPlayerType: 'stockfish' })}
                disabled={loading || isSubmittingMove}
              >
                Play vs Stockfish
              </button>
            </div>

            <div className="llm-config">
              <h4>LLM Opponent</h4>
              <label htmlFor="llm-provider">Provider</label>
              <select
                id="llm-provider"
                value={selectedProvider}
                onChange={(event) => setSelectedProvider(event.target.value)}
                disabled={loading || isSubmittingMove || Object.keys(aiOptions.providers).length === 0}
              >
                {Object.keys(aiOptions.providers).length === 0 ? (
                  <option value="">Unavailable</option>
                ) : (
                  Object.keys(aiOptions.providers).map((provider) => (
                    <option key={provider} value={provider}>
                      {PROVIDER_LABELS[provider] || provider}
                    </option>
                  ))
                )}
              </select>

              <label htmlFor="llm-model">Model</label>
              <select
                id="llm-model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={loading || isSubmittingMove || !selectedProvider}
              >
                {(aiOptions.providers[selectedProvider] || []).map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>

              {aiOptions.advanced_custom_model_enabled ? (
                <>
                  <label htmlFor="llm-custom-model">Custom model override (optional)</label>
                  <input
                    id="llm-custom-model"
                    type="text"
                    value={customModelOverride}
                    placeholder="provider-specific model id"
                    onChange={(event) => setCustomModelOverride(event.target.value)}
                    disabled={loading || isSubmittingMove || !selectedProvider}
                  />
                </>
              ) : null}

              <button
                onClick={handleStartLlmGame}
                disabled={
                  loading ||
                  isSubmittingMove ||
                  !selectedProvider ||
                  !selectedModel ||
                  Object.keys(aiOptions.providers).length === 0
                }
              >
                Play vs LLM
              </button>

              {aiOptionsError ? <div className="llm-config-error">{aiOptionsError}</div> : null}
            </div>

            <div className="status">{status}</div>
            {opponentProfile ? (
              <div className="opponent-info">
                <div className="opponent-title">{opponentProfile.title}</div>
                {opponentProfile.details.map((detail) => (
                  <div key={detail} className="opponent-detail">
                    {detail}
                  </div>
                ))}
                {opponentProfile.estimatedElo ? (
                  <div className="opponent-metric">Estimated Elo: {opponentProfile.estimatedElo}</div>
                ) : null}
                <div className="opponent-metric">Position strength: {positionStrength}</div>
              </div>
            ) : null}
            {moveError ? <div className="status error-status">{moveError}</div> : null}
            {isSubmittingMove ? <div className="status info-status">Submitting move...</div> : null}

            <div className="analysis-controls">
              <button
                type="button"
                className="analyze-button"
                onClick={handleAnalyzeGame}
                disabled={!canAnalyze}
              >
                Analyze Game
              </button>
              <div className="analysis-hint">
                {plyCount < ANALYSIS_MIN_PLIES
                  ? `Play at least ${ANALYSIS_MIN_PLIES} plies before analysis (${plyCount}/${ANALYSIS_MIN_PLIES}).`
                  : 'Run analysis to estimate both sides and highlight key moments.'}
              </div>
            </div>
            {analysisError ? <div className="status error-status analysis-error">{analysisError}</div> : null}
            {isAnalyzing ? <div className="status info-status">Analyzing game...</div> : null}
          </div>

          <div className="board-wrapper">
            <div className="board-shell">
              <Chessboard options={boardOptions} />
            </div>
          </div>

          <div className="glass-panel info-panel">
            <h3>Captures</h3>
            <div className="captures-container">
              <div className="capture-row">
                <span>White: </span>
                {captures.w.map((piece, index) => (
                  <span key={`${piece}-${index}`} className="piece-icon black-piece">
                    {getPieceIcon(piece)}
                  </span>
                ))}
              </div>
              <div className="capture-row">
                <span>Black: </span>
                {captures.b.map((piece, index) => (
                  <span key={`${piece}-${index}`} className="piece-icon white-piece">
                    {getPieceIcon(piece)}
                  </span>
                ))}
              </div>
            </div>

            <h3>Move History</h3>
            <div className="history-container">
              <table className="history-table">
                <tbody>
                  {historyRows.map((row) => (
                    <tr key={row.num}>
                      <td className="move-num">{row.num}.</td>
                      <td className="white-move">{row.white.san}</td>
                      <td className="black-move">{row.black ? row.black.san : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {gameId ? (
              <div style={{ marginTop: '1rem', borderTop: '1px solid #ffffff20', paddingTop: '1rem' }}>
                <small>Game ID: {gameId}</small>
              </div>
            ) : null}

            {analysisResult ? (
              <div className="analysis-panel">
                <h3>Performance Analysis</h3>
                <div className="analysis-card-grid">
                  <div className="analysis-card">
                    <div className="analysis-card-title">Your Performance Elo</div>
                    <div className="analysis-elo">{analysisResult.white.estimated_elo}</div>
                    <div className="analysis-metric">
                      Accuracy: {analysisResult.white.accuracy_percent}% | Avg CPL:{' '}
                      {analysisResult.white.avg_centipawn_loss}
                    </div>
                    <div className="analysis-metric">
                      Best {analysisResult.white.move_counts.best} | Good {analysisResult.white.move_counts.good} |
                      Inaccuracy {analysisResult.white.move_counts.inaccuracy} | Mistake{' '}
                      {analysisResult.white.move_counts.mistake} | Blunder {analysisResult.white.move_counts.blunder}
                    </div>
                  </div>
                  <div className="analysis-card">
                    <div className="analysis-card-title">Opponent Performance Elo</div>
                    <div className="analysis-elo">{analysisResult.black.estimated_elo}</div>
                    <div className="analysis-metric">
                      Accuracy: {analysisResult.black.accuracy_percent}% | Avg CPL:{' '}
                      {analysisResult.black.avg_centipawn_loss}
                    </div>
                    <div className="analysis-metric">
                      Best {analysisResult.black.move_counts.best} | Good {analysisResult.black.move_counts.good} |
                      Inaccuracy {analysisResult.black.move_counts.inaccuracy} | Mistake{' '}
                      {analysisResult.black.move_counts.mistake} | Blunder {analysisResult.black.move_counts.blunder}
                    </div>
                  </div>
                </div>

                <h4>Key Moves</h4>
                {analysisResult.key_moves.length === 0 ? (
                  <div className="analysis-empty">No major key moves found in this sample.</div>
                ) : (
                  <div className="analysis-list">
                    {analysisResult.key_moves.map((move) => (
                      <div key={`key-${move.ply}-${move.uci}`} className={`analysis-item ${move.category}`}>
                        <div className="analysis-item-title">
                          #{move.ply} {move.side} {move.san} ({move.category})
                        </div>
                        <div className="analysis-item-meta">
                          Impact: {move.cp_loss} cp | Eval: {move.eval_before_cp} to {move.eval_after_cp}
                        </div>
                        <div className="analysis-item-copy">{move.commentary}</div>
                      </div>
                    ))}
                  </div>
                )}

                <h4>Turning Points</h4>
                {analysisResult.turning_points.length === 0 ? (
                  <div className="analysis-empty">No major turning points identified.</div>
                ) : (
                  <div className="analysis-list">
                    {analysisResult.turning_points.map((point) => (
                      <div key={`tp-${point.ply}-${point.san}`} className="analysis-item turning-point">
                        <div className="analysis-item-title">
                          #{point.ply} {point.side} {point.san}
                        </div>
                        <div className="analysis-item-meta">Swing: {point.swing_cp} cp</div>
                        <div className="analysis-item-copy">{point.commentary}</div>
                      </div>
                    ))}
                  </div>
                )}

                <h4>Game Summary</h4>
                <p className="analysis-summary">{analysisResult.summary}</p>
                <div className="analysis-note">{analysisResult.reliability?.note}</div>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="arena-layout">
          <div className="glass-panel arena-controls">
            <h3>LLM Arena Config</h3>
            <p className="arena-note">Configure both players, run batch matches, and compare policy metrics.</p>

            {[
              { key: 'a', title: 'Player A' },
              { key: 'b', title: 'Player B' },
            ].map((entry) => {
              const player = entry.key === 'a' ? arenaPlayerA : arenaPlayerB
              const modelOptions = localArenaModels
              const verifierModels = localArenaModels
              const fallbackModels = localArenaModels
              return (
                <div key={entry.key} className="arena-player-card">
                  <h4>{entry.title}</h4>
                  <label>Provider</label>
                  <div className="arena-provider-fixed">Local (Ollama)</div>

                  <label>Model</label>
                  <select
                    value={player.model}
                    onChange={(event) => setArenaPlayerField(entry.key, 'model', event.target.value)}
                    disabled={modelOptions.length === 0}
                  >
                    {modelOptions.length === 0 ? (
                      <option value="">No local models available</option>
                    ) : null}
                    {modelOptions.map((model) => (
                      <option key={`${entry.key}-model-${model}`} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>

                  {aiOptions.advanced_custom_model_enabled ? (
                    <>
                      <label>Custom model override</label>
                      <input
                        type="text"
                        value={player.customModel}
                        placeholder="optional custom model id"
                        onChange={(event) => setArenaPlayerField(entry.key, 'customModel', event.target.value)}
                      />
                    </>
                  ) : null}

                  <label>TTC Policy</label>
                  <select
                    value={player.policyName}
                    onChange={(event) => setArenaPlayerField(entry.key, 'policyName', event.target.value)}
                  >
                    {TTC_POLICY_OPTIONS.map((option) => (
                      <option key={`${entry.key}-policy-${option.value}`} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>

                  {player.policyName !== 'baseline' ? (
                    <>
                      <label>Samples</label>
                      <input
                        type="number"
                        min={1}
                        max={12}
                        value={player.samples}
                        onChange={(event) => setArenaPlayerField(entry.key, 'samples', event.target.value)}
                      />
                      <label>Max Attempts</label>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={player.maxAttempts}
                        onChange={(event) => setArenaPlayerField(entry.key, 'maxAttempts', event.target.value)}
                      />
                    </>
                  ) : null}

                  {player.policyName === 'verifier' ? (
                    <>
                      <label>Verifier Model</label>
                      <select
                        value={player.verifierModel}
                        onChange={(event) => {
                          const model = event.target.value
                          setArenaPlayerField(entry.key, 'verifierModel', model)
                          setArenaPlayerField(entry.key, 'verifierProvider', model ? 'local' : '')
                        }}
                      >
                        <option value="">None</option>
                        {verifierModels.map((model) => (
                          <option key={`${entry.key}-verifier-model-${model}`} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </>
                  ) : null}

                  {player.policyName === 'uncertainty_fallback' ? (
                    <>
                      <label>Agreement Threshold</label>
                      <input
                        type="number"
                        min={0.5}
                        max={1}
                        step={0.01}
                        value={player.agreementThreshold}
                        onChange={(event) =>
                          setArenaPlayerField(entry.key, 'agreementThreshold', event.target.value)
                        }
                      />
                      <label>Fallback Model</label>
                      <select
                        value={player.fallbackModel}
                        onChange={(event) => {
                          const model = event.target.value
                          setArenaPlayerField(entry.key, 'fallbackModel', model)
                          setArenaPlayerField(entry.key, 'fallbackProvider', model ? 'local' : '')
                        }}
                      >
                        <option value="">None</option>
                        {fallbackModels.map((model) => (
                          <option key={`${entry.key}-fallback-model-${model}`} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </>
                  ) : null}
                </div>
              )
            })}

            <div className="arena-run-config">
              <label>Number of Games</label>
              <input
                type="number"
                min={1}
                max={100}
                value={arenaNumGames}
                onChange={(event) => setArenaNumGames(event.target.value)}
              />
              <label>Max Plies per Game</label>
              <input
                type="number"
                min={2}
                max={300}
                value={arenaMaxPlies}
                onChange={(event) => setArenaMaxPlies(event.target.value)}
              />
              <label className="arena-checkbox">
                <input
                  type="checkbox"
                  checked={arenaAlternateColors}
                  onChange={(event) => setArenaAlternateColors(event.target.checked)}
                />
                Alternate colors between games
              </label>
            </div>

            <div className="arena-actions">
              <button type="button" onClick={handleRunArenaBatch} disabled={!canRunArenaBatch}>
                {arenaSubmitting ? 'Starting...' : 'Run Batch'}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!arenaRunId) return
                  void loadArenaRunDetail(arenaRunId, true)
                }}
                disabled={!arenaRunId}
              >
                Refresh Run
              </button>
            </div>

            <div className="status">
              Arena Run: {arenaRunId ? `#${arenaRunId} (${arenaRunStatus})` : 'none'}
            </div>
            {localArenaModels.length === 0 ? (
              <div className="status error-status">No local Ollama models in server allowlist.</div>
            ) : null}
            {arenaRunError ? <div className="status error-status">{arenaRunError}</div> : null}
            {aiOptionsError ? <div className="llm-config-error">{aiOptionsError}</div> : null}
          </div>

          <div className="glass-panel arena-live-panel">
            <h3>Live Arena</h3>
            <div className="arena-actions">
              <button type="button" onClick={handleStartLiveArenaGame} disabled={liveArenaBusy || arenaSubmitting}>
                Start Live Match
              </button>
              <button
                type="button"
                onClick={() => void stepLiveArena(2)}
                disabled={!liveArenaGameId || liveArenaBusy}
              >
                Step 2 Plies
              </button>
              <button
                type="button"
                onClick={() => setLiveArenaAuto((value) => !value)}
                disabled={!liveArenaGameId}
              >
                {liveArenaAuto ? 'Pause Auto' : 'Auto Play'}
              </button>
            </div>
            <div className="status">{liveArenaStatus}</div>
            {liveArenaError ? <div className="status error-status">{liveArenaError}</div> : null}
            <div className="board-shell arena-board-shell">
              <Chessboard options={liveArenaBoardOptions} />
            </div>
            <div className="history-container arena-history">
              <table className="history-table">
                <tbody>
                  {liveArenaHistoryRows.map((row) => (
                    <tr key={`live-${row.num}`}>
                      <td className="move-num">{row.num}.</td>
                      <td className="white-move">{row.white.san}</td>
                      <td className="black-move">{row.black ? row.black.san : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {liveArenaGameId ? <small>Live Game ID: {liveArenaGameId}</small> : null}
          </div>

          <div className="glass-panel arena-results-panel">
            <h3>Batch Results</h3>
            {arenaRunResult ? (
              <>
                <div className="arena-metric-grid">
                  <div className="analysis-card">
                    <div className="analysis-card-title">Player A</div>
                    <div className="analysis-metric">
                      W/L/D: {arenaRunResult.player_a.wins}/{arenaRunResult.player_a.losses}/
                      {arenaRunResult.player_a.draws}
                    </div>
                    <div className="analysis-metric">Win rate: {percentText(arenaRunResult.player_a.win_rate)}</div>
                    <div className="analysis-metric">Score: {arenaRunResult.player_a.score}</div>
                    <div className="analysis-metric">
                      Avg attempts/move: {arenaRunResult.player_a.avg_attempts_per_move}
                    </div>
                    <div className="analysis-metric">
                      Fallback rate: {percentText(arenaRunResult.player_a.fallback_rate)}
                    </div>
                    <div className="analysis-metric">
                      Avg latency: {arenaRunResult.player_a.avg_latency_ms} ms
                    </div>
                    <div className="analysis-metric">
                      Est. cost: ${arenaRunResult.player_a.estimated_cost_usd}
                    </div>
                  </div>
                  <div className="analysis-card">
                    <div className="analysis-card-title">Player B</div>
                    <div className="analysis-metric">
                      W/L/D: {arenaRunResult.player_b.wins}/{arenaRunResult.player_b.losses}/
                      {arenaRunResult.player_b.draws}
                    </div>
                    <div className="analysis-metric">Win rate: {percentText(arenaRunResult.player_b.win_rate)}</div>
                    <div className="analysis-metric">Score: {arenaRunResult.player_b.score}</div>
                    <div className="analysis-metric">
                      Avg attempts/move: {arenaRunResult.player_b.avg_attempts_per_move}
                    </div>
                    <div className="analysis-metric">
                      Fallback rate: {percentText(arenaRunResult.player_b.fallback_rate)}
                    </div>
                    <div className="analysis-metric">
                      Avg latency: {arenaRunResult.player_b.avg_latency_ms} ms
                    </div>
                    <div className="analysis-metric">
                      Est. cost: ${arenaRunResult.player_b.estimated_cost_usd}
                    </div>
                  </div>
                </div>
                <div className="analysis-card">
                  <div className="analysis-card-title">Run Summary</div>
                  <div className="analysis-metric">Average plies: {arenaRunResult.summary?.avg_plies}</div>
                  <div className="analysis-metric">
                    Decisive rate: {percentText(arenaRunResult.summary?.decisive_rate)}
                  </div>
                  <div className="analysis-metric">Draw rate: {percentText(arenaRunResult.summary?.draw_rate)}</div>
                </div>
              </>
            ) : (
              <div className="analysis-empty">No run result yet. Start a batch to generate metrics.</div>
            )}

            <h4>Recent Runs</h4>
            <div className="history-container arena-runs-list">
              <table className="history-table">
                <tbody>
                  {arenaRecentRuns.map((run) => (
                    <tr key={`run-${run.id}`}>
                      <td className="move-num">#{run.id}</td>
                      <td className="white-move">{run.status}</td>
                      <td className="black-move">{run.config?.num_games || '-'}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => {
                            setArenaRunId(run.id)
                            setArenaRunStatus(run.status)
                            void loadArenaRunDetail(run.id, run.status === 'completed')
                          }}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'play' && pendingPromotion ? (
        <div className="promotion-overlay" role="dialog" aria-modal="true" aria-label="Choose promotion piece">
          <div className="promotion-modal">
            <h3>Choose Promotion</h3>
            <div className="promotion-options">
              {PROMOTION_OPTIONS.map((piece) => (
                <button
                  key={piece}
                  type="button"
                  className="promotion-button"
                  data-promo={piece}
                  onClick={() => handlePromotionChoice(piece)}
                >
                  {getPieceIcon(piece)}
                </button>
              ))}
            </div>
            <button type="button" className="promotion-cancel" onClick={handlePromotionCancel}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default App
