/*
 * dashboard.h
 * Terrain-Aware Rover — WiFi web dashboard (embedded HTML/CSS/JS)
 *
 * Served by ESP32 HTTP server at http://192.168.4.1
 * Communicates with firmware via WebSocket on ws://192.168.4.1:81
 *
 * Two modes rendered in the same single-page app:
 *   TRAINING — terrain selector, motor control, live gauges, REC/Download
 *   TESTING  — prediction display, YES/NO feedback, correction panel, stats
 */

#pragma once

const char DASHBOARD_HTML[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terrain-Aware Rover</title>
<style>
  :root {
    --bg:        #0d1117;
    --surface:   #161b22;
    --border:    #30363d;
    --accent:    #58a6ff;
    --green:     #3fb950;
    --red:       #f85149;
    --amber:     #d29922;
    --text:      #e6edf3;
    --muted:     #8b949e;
    --tile-c:    #58a6ff;
    --mat-c:     #a371f7;
    --carpet-c:  #3fb950;
    --gravel-c:  #d29922;
    --radius:    10px;
    --shadow:    0 4px 24px rgba(0,0,0,.5);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    min-height: 100vh;
    padding: 0 0 40px 0;
  }

  /* ── header ─────────────────────────────────────────────────────────────── */
  header {
    background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
    border-bottom: 1px solid var(--border);
    padding: 16px 20px 12px;
    text-align: center;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(8px);
  }
  header h1 {
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: .04em;
    color: var(--text);
  }
  header h1 span { color: var(--accent); }
  .status-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-top: 6px;
    font-size: .78rem;
    color: var(--muted);
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--red);
    display: inline-block;
    transition: background .3s;
  }
  .dot.on  { background: var(--green); box-shadow: 0 0 6px var(--green); }

  /* ── layout ─────────────────────────────────────────────────────────────── */
  .container { max-width: 540px; margin: 0 auto; padding: 16px; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    margin-bottom: 14px;
    box-shadow: var(--shadow);
  }
  .card-title {
    font-size: .72rem;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
  }

  /* ── mode switcher ───────────────────────────────────────────────────────── */
  .mode-tabs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .mode-btn {
    padding: 10px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-size: .85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all .2s;
  }
  .mode-btn.active[data-mode="train"] {
    background: rgba(88,166,255,.15);
    border-color: var(--accent);
    color: var(--accent);
  }
  .mode-btn.active[data-mode="test"] {
    background: rgba(63,185,80,.15);
    border-color: var(--green);
    color: var(--green);
  }

  /* ── terrain buttons ─────────────────────────────────────────────────────── */
  .terrain-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .terrain-btn {
    padding: 14px 8px;
    border-radius: var(--radius);
    border: 2px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-size: .88rem;
    font-weight: 700;
    letter-spacing: .04em;
    cursor: pointer;
    transition: all .2s;
    position: relative;
    overflow: hidden;
  }
  .terrain-btn::before {
    content: '';
    position: absolute;
    inset: 0;
    opacity: 0;
    transition: opacity .2s;
  }
  .terrain-btn[data-t="tile"]   { border-color: #1a3a5e; }
  .terrain-btn[data-t="mat"]    { border-color: #2d1f4e; }
  .terrain-btn[data-t="carpet"] { border-color: #1a3a28; }
  .terrain-btn[data-t="gravel"] { border-color: #3a2d0d; }
  .terrain-btn[data-t="tile"].selected   { border-color: var(--tile-c);   color: var(--tile-c);   background: rgba(88,166,255,.12); }
  .terrain-btn[data-t="mat"].selected    { border-color: var(--mat-c);    color: var(--mat-c);    background: rgba(163,113,247,.12); }
  .terrain-btn[data-t="carpet"].selected { border-color: var(--carpet-c); color: var(--carpet-c); background: rgba(63,185,80,.12); }
  .terrain-btn[data-t="gravel"].selected { border-color: var(--gravel-c); color: var(--gravel-c); background: rgba(210,153,34,.12); }
  .terrain-btn .t-icon { font-size: 1.4rem; display: block; margin-bottom: 4px; }

  /* ── prediction card (Testing) ───────────────────────────────────────────── */
  .prediction-box {
    text-align: center;
    padding: 10px 0;
  }
  .pred-label-small { font-size: .75rem; color: var(--muted); margin-bottom: 4px; }
  .pred-value {
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: .06em;
    transition: color .3s;
  }
  .pred-value[data-t="tile"]   { color: var(--tile-c); }
  .pred-value[data-t="mat"]    { color: var(--mat-c); }
  .pred-value[data-t="carpet"] { color: var(--carpet-c); }
  .pred-value[data-t="gravel"] { color: var(--gravel-c); }

  .confidence-bar-wrap {
    margin: 8px auto 0;
    max-width: 200px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }
  .confidence-bar {
    height: 100%;
    background: var(--accent);
    border-radius: 3px;
    transition: width .5s;
  }
  .confidence-label { font-size: .72rem; color: var(--muted); margin-top: 4px; }

  .feedback-prompt {
    font-size: .85rem;
    color: var(--muted);
    text-align: center;
    margin: 12px 0 8px;
  }
  .feedback-btns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .fb-btn {
    padding: 14px;
    border-radius: var(--radius);
    border: 2px solid;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    transition: all .18s;
  }
  .fb-yes { border-color: var(--green); background: rgba(63,185,80,.1); color: var(--green); }
  .fb-yes:hover { background: rgba(63,185,80,.25); }
  .fb-no  { border-color: var(--red);   background: rgba(248,81,73,.1);  color: var(--red);   }
  .fb-no:hover  { background: rgba(248,81,73,.25); }
  .fb-btn:disabled { opacity: .35; cursor: not-allowed; }

  .feedback-result {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px;
    border-radius: var(--radius);
    font-size: .9rem;
    font-weight: 600;
    margin-top: 8px;
  }
  .feedback-result.correct   { background: rgba(63,185,80,.15); color: var(--green); }
  .feedback-result.incorrect { background: rgba(248,81,73,.15); color: var(--red); }

  /* correction panel */
  .correction-panel {
    display: none;
    margin-top: 12px;
  }
  .correction-panel.visible { display: block; }
  .correction-hint {
    font-size: .75rem;
    color: var(--amber);
    margin-bottom: 8px;
    text-align: center;
  }

  /* ── motor control ───────────────────────────────────────────────────────── */
  .pwm-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }
  .pwm-row label { font-size: .8rem; color: var(--muted); min-width: 32px; }
  input[type=range] {
    flex: 1;
    accent-color: var(--accent);
    height: 4px;
    cursor: pointer;
  }
  .pwm-val {
    font-size: .9rem;
    font-weight: 700;
    min-width: 30px;
    text-align: right;
    color: var(--accent);
  }
  .motor-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .btn-go, .btn-stop {
    padding: 13px;
    border-radius: var(--radius);
    border: 2px solid;
    font-size: .95rem;
    font-weight: 700;
    cursor: pointer;
    transition: all .18s;
  }
  .btn-go   { border-color: var(--green); background: rgba(63,185,80,.1);  color: var(--green); }
  .btn-go:hover   { background: rgba(63,185,80,.25); }
  .btn-go.active  { background: var(--green); color: #0d1117; }
  .btn-stop { border-color: var(--red);   background: rgba(248,81,73,.1);  color: var(--red);   }
  .btn-stop:hover { background: rgba(248,81,73,.25); }
  .speed-info { font-size: .78rem; color: var(--muted); text-align: center; margin-top: 8px; }

  /* ── d-pad ────────────────────────────────────────────────────────────────── */
  .dpad { display: flex; flex-direction: column; align-items: center; gap: 4px; margin-top: 4px; }
  .dpad-row { display: flex; gap: 4px; }
  .dpad-btn {
    width: 48px; height: 48px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    font-size: 1.1rem;
    cursor: pointer;
    transition: all .15s;
    display: flex; align-items: center; justify-content: center;
  }
  .dpad-btn:hover  { background: var(--border); }
  .dpad-btn:active { transform: scale(.92); background: var(--accent); color: #0d1117; }
  .dpad-stop { color: var(--red); border-color: var(--red); }
  .dpad-stop:active { background: var(--red); color: #fff; }
  .dpad-spin { width: 56px; font-size: 1.3rem; color: var(--amber); border-color: var(--amber); }
  .dpad-spin:active { background: var(--amber); color: #0d1117; }

  /* ── vibration gauges ────────────────────────────────────────────────────── */
  .gauge-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .gauge-name  { font-size: .75rem; font-weight: 600; color: var(--muted); min-width: 30px; }
  .gauge-track {
    flex: 1;
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
  }
  .gauge-fill {
    height: 100%;
    border-radius: 4px;
    background: var(--accent);
    transition: width .4s ease;
  }
  .gauge-val   { font-size: .78rem; font-weight: 600; min-width: 46px; text-align: right; }

  /* ── recording / logging ─────────────────────────────────────────────────── */
  .rec-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }
  .btn-rec {
    padding: 9px 16px;
    border-radius: var(--radius);
    border: 2px solid var(--red);
    background: transparent;
    color: var(--red);
    font-size: .85rem;
    font-weight: 700;
    cursor: pointer;
    transition: all .18s;
  }
  .btn-rec.active { background: var(--red); color: #fff; }
  .rec-status { font-size: .8rem; color: var(--muted); }
  .rec-count  { font-size: .8rem; font-weight: 700; color: var(--text); }
  .btn-dl {
    display: block;
    width: 100%;
    padding: 10px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: transparent;
    color: var(--accent);
    font-size: .85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all .18s;
    text-align: center;
  }
  .btn-dl:hover { background: rgba(88,166,255,.1); }

  /* ── session stats ───────────────────────────────────────────────────────── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 10px;
  }
  .stat-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    text-align: center;
  }
  .stat-val   { font-size: 1.5rem; font-weight: 800; }
  .stat-label { font-size: .68rem; color: var(--muted); margin-top: 2px; }
  .stat-box.s-total .stat-val { color: var(--accent); }
  .stat-box.s-ok    .stat-val { color: var(--green);  }
  .stat-box.s-err   .stat-val { color: var(--red);    }

  /* ── misc ────────────────────────────────────────────────────────────────── */
  .hidden { display: none !important; }
  .divider { border: none; border-top: 1px solid var(--border); margin: 4px 0 12px; }
</style>
</head>
<body>

<header>
  <h1>🚗 <span>Terrain-Aware</span> Rover</h1>
  <div class="status-bar">
    <span><span id="wsDot" class="dot"></span> <span id="wsLabel">Disconnected</span></span>
    <span>Uptime: <b id="uptime">0s</b></span>
    <span>Speed: <b id="speedVal">0.00</b> m/s</span>
  </div>
</header>

<div class="container">

  <!-- ── Mode Switcher ─────────────────────────────────────────────────────── -->
  <div class="card">
    <div class="card-title">Operating Mode</div>
    <div class="mode-tabs">
      <button class="mode-btn active" data-mode="train" id="btnTrain"
              onclick="switchMode('train')">🟦 Training Mode</button>
      <button class="mode-btn" data-mode="test" id="btnTest"
              onclick="switchMode('test')">🟩 Testing Mode</button>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════════════════ -->
  <!-- TRAINING MODE PANEL                                                    -->
  <!-- ══════════════════════════════════════════════════════════════════════ -->
  <div id="trainPanel">

    <!-- Terrain Selector -->
    <div class="card">
      <div class="card-title">Select Terrain Surface</div>
      <div class="terrain-grid">
        <button class="terrain-btn selected" data-t="tile"   onclick="setLabel('tile')">
          <span class="t-icon">🪨</span>TILE
        </button>
        <button class="terrain-btn" data-t="mat"    onclick="setLabel('mat')">
          <span class="t-icon">🟫</span>MAT
        </button>
        <button class="terrain-btn" data-t="carpet" onclick="setLabel('carpet')">
          <span class="t-icon">🧶</span>CARPET
        </button>
        <button class="terrain-btn" data-t="gravel" onclick="setLabel('gravel')">
          <span class="t-icon">⚫</span>GRAVEL
        </button>
      </div>
    </div>

    <!-- Motor Control -->
    <div class="card">
      <div class="card-title">Motor Control</div>
      <div class="pwm-row">
        <label>PWM</label>
        <input id="pwmSlider" type="range" min="0" max="255" value="150"
               oninput="onPwmChange(this.value)">
        <div class="pwm-val" id="pwmDisp">150</div>
      </div>
      <div class="motor-btns">
        <button class="btn-go"   id="btnGo"   onclick="sendGo()">▶ GO</button>
        <button class="btn-stop" id="btnStop" onclick="sendStop()">⬛ STOP</button>
      </div>
      <div class="speed-info">Speed: <b id="trainSpeed">0.00</b> m/s</div>
      <hr class="divider">
      <div class="card-title" style="margin-top:4px">Direction Control</div>
      <div class="dpad">
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendDir('go')">▲</button>
        </div>
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendTurn('left')"  title="Turn left">◀</button>
          <button class="dpad-btn dpad-stop" onclick="sendStop()">■</button>
          <button class="dpad-btn" onclick="sendTurn('right')" title="Turn right">▶</button>
        </div>
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendDir('back')">▼</button>
        </div>
        <div class="dpad-row" style="margin-top:6px;gap:6px">
          <button class="dpad-btn dpad-spin" onclick="sendSpin('left')"  title="Spin left">↺</button>
          <button class="dpad-btn dpad-spin" onclick="sendSpin('right')" title="Spin right">↻</button>
        </div>
      </div>
    </div>

    <!-- Live Vibration Gauges -->
    <div class="card">
      <div class="card-title">Live Vibration Features</div>
      <div class="gauge-row">
        <div class="gauge-name">STD</div>
        <div class="gauge-track"><div class="gauge-fill" id="gStd" style="width:0%"></div></div>
        <div class="gauge-val" id="vStd">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">RMS</div>
        <div class="gauge-track"><div class="gauge-fill" id="gRms" style="width:0%"></div></div>
        <div class="gauge-val" id="vRms">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">P2P</div>
        <div class="gauge-track"><div class="gauge-fill" id="gP2p" style="width:0%"></div></div>
        <div class="gauge-val" id="vP2p">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">ZCR</div>
        <div class="gauge-track"><div class="gauge-fill" id="gZcr" style="width:0%"></div></div>
        <div class="gauge-val" id="vZcr">0</div>
      </div>
    </div>

    <!-- Data Logging -->
    <div class="card">
      <div class="card-title">Data Logging → train_dataset.csv</div>
      <div class="rec-row">
        <button class="btn-rec" id="btnRec" onclick="toggleRec()">● REC</button>
        <span class="rec-status" id="recStatus">Not recording</span>
        <span class="rec-count" id="recCount"></span>
      </div>
      <button class="btn-dl" onclick="downloadCSV('train')">⬇ Download train_dataset.csv</button>
    </div>

  </div><!-- /trainPanel -->


  <!-- ══════════════════════════════════════════════════════════════════════ -->
  <!-- TESTING MODE PANEL                                                     -->
  <!-- ══════════════════════════════════════════════════════════════════════ -->
  <div id="testPanel" class="hidden">

    <!-- Prediction Display -->
    <div class="card">
      <div class="card-title">Terrain Prediction</div>
      <div class="prediction-box">
        <div class="pred-label-small">Rover thinks it's on:</div>
        <div class="pred-value" id="predValue" data-t="tile">—</div>
        <div class="confidence-bar-wrap">
          <div class="confidence-bar" id="confBar" style="width:0%"></div>
        </div>
        <div class="confidence-label" id="confLabel">Confidence: —</div>
      </div>

      <hr class="divider">

      <!-- Feedback buttons -->
      <div class="feedback-prompt" id="fbPrompt">Was that correct?</div>
      <div class="feedback-btns">
        <button class="fb-btn fb-yes" id="btnYes" onclick="giveFeedback(true)">✓ YES</button>
        <button class="fb-btn fb-no"  id="btnNo"  onclick="giveFeedback(false)">✗ NO</button>
      </div>

      <!-- Feedback result -->
      <div class="feedback-result hidden" id="fbResult"></div>

      <!-- Correction panel (shown after NO) -->
      <div class="correction-panel" id="corrPanel">
        <div class="correction-hint">⚠ What was the actual terrain?</div>
        <div class="terrain-grid">
          <button class="terrain-btn" data-t="tile"   onclick="sendCorrection('tile')">
            <span class="t-icon">🪨</span>TILE
          </button>
          <button class="terrain-btn" data-t="mat"    onclick="sendCorrection('mat')">
            <span class="t-icon">🟫</span>MAT
          </button>
          <button class="terrain-btn" data-t="carpet" onclick="sendCorrection('carpet')">
            <span class="t-icon">🧶</span>CARPET
          </button>
          <button class="terrain-btn" data-t="gravel" onclick="sendCorrection('gravel')">
            <span class="t-icon">⚫</span>GRAVEL
          </button>
        </div>
      </div>
    </div>

    <!-- Motor Control (test) -->
    <div class="card">
      <div class="card-title">Motor Control</div>
      <div class="pwm-row">
        <label>PWM</label>
        <input id="pwmSliderT" type="range" min="0" max="255" value="150"
               oninput="onPwmChange(this.value)">
        <div class="pwm-val" id="pwmDispT">150</div>
      </div>
      <div class="motor-btns">
        <button class="btn-go"   onclick="sendGo()">▶ GO</button>
        <button class="btn-stop" onclick="sendStop()">⬛ STOP</button>
      </div>
      <div class="speed-info">Speed: <b id="testSpeed">0.00</b> m/s</div>
      <hr class="divider">
      <div class="card-title" style="margin-top:4px">Direction Control</div>
      <div class="dpad">
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendDir('go')">▲</button>
        </div>
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendTurn('left')"  title="Turn left">◀</button>
          <button class="dpad-btn dpad-stop" onclick="sendStop()">■</button>
          <button class="dpad-btn" onclick="sendTurn('right')" title="Turn right">▶</button>
        </div>
        <div class="dpad-row">
          <button class="dpad-btn" onclick="sendDir('back')">▼</button>
        </div>
        <div class="dpad-row" style="margin-top:6px;gap:6px">
          <button class="dpad-btn dpad-spin" onclick="sendSpin('left')"  title="Spin left">↺</button>
          <button class="dpad-btn dpad-spin" onclick="sendSpin('right')" title="Spin right">↻</button>
        </div>
      </div>
    </div>

    <!-- Live Gauges (test) -->
    <div class="card">
      <div class="card-title">Live Vibration Features</div>
      <div class="gauge-row">
        <div class="gauge-name">STD</div>
        <div class="gauge-track"><div class="gauge-fill" id="tgStd" style="width:0%"></div></div>
        <div class="gauge-val" id="tvStd">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">RMS</div>
        <div class="gauge-track"><div class="gauge-fill" id="tgRms" style="width:0%"></div></div>
        <div class="gauge-val" id="tvRms">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">P2P</div>
        <div class="gauge-track"><div class="gauge-fill" id="tgP2p" style="width:0%"></div></div>
        <div class="gauge-val" id="tvP2p">0.000</div>
      </div>
      <div class="gauge-row">
        <div class="gauge-name">ZCR</div>
        <div class="gauge-track"><div class="gauge-fill" id="tgZcr" style="width:0%"></div></div>
        <div class="gauge-val" id="tvZcr">0</div>
      </div>
    </div>

    <!-- Session Stats -->
    <div class="card">
      <div class="card-title">Session Statistics</div>
      <div class="stats-grid">
        <div class="stat-box s-total">
          <div class="stat-val" id="sTot">0</div>
          <div class="stat-label">Total</div>
        </div>
        <div class="stat-box s-ok">
          <div class="stat-val" id="sOk">0</div>
          <div class="stat-label">Correct</div>
        </div>
        <div class="stat-box s-err">
          <div class="stat-val" id="sErr">0</div>
          <div class="stat-label">Wrong</div>
        </div>
      </div>
      <div class="gauge-row" style="margin-bottom:12px">
        <div class="gauge-name" style="min-width:44px;font-size:.7rem">Accuracy</div>
        <div class="gauge-track" style="height:10px">
          <div class="gauge-fill" id="accBar"
               style="width:0%;background:var(--green)"></div>
        </div>
        <div class="gauge-val" id="accPct">— %</div>
      </div>
      <button class="btn-rec" id="btnRecT" onclick="toggleRec()" style="margin-bottom:8px">● REC</button>
      <span class="rec-status" id="recStatusT" style="margin-left:8px">Not recording</span>
      <button class="btn-dl" onclick="downloadCSV('test')" style="margin-top:8px">
        ⬇ Download feedback_log.csv
      </button>
    </div>

  </div><!-- /testPanel -->

</div><!-- /container -->

<script>
// ─── State ───────────────────────────────────────────────────────────────────
let ws           = null;
let wsConnected  = false;
let currentMode  = 'train';
let isRecording  = false;
let isRunning    = false;
let currentPwm   = 150;

// In-browser log buffers (for CSV download)
let trainRows    = [];   // Training mode rows
let feedbackRows = [];   // Testing mode rows

// ─── WebSocket ────────────────────────────────────────────────────────────────
function connect() {
  const host = location.hostname || '192.168.4.1';
  ws = new WebSocket('ws://' + host + ':81');

  ws.onopen = () => {
    wsConnected = true;
    document.getElementById('wsDot').classList.add('on');
    document.getElementById('wsLabel').textContent = 'Connected';
  };

  ws.onclose = () => {
    wsConnected = false;
    document.getElementById('wsDot').classList.remove('on');
    document.getElementById('wsLabel').textContent = 'Disconnected — retrying…';
    setTimeout(connect, 3000);
  };

  ws.onmessage = e => {
    try { handleMsg(JSON.parse(e.data)); } catch(_) {}
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify(obj));
}

// ─── Incoming message handler ─────────────────────────────────────────────────
function handleMsg(d) {
  // Uptime
  const s = d.uptime || 0;
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
  document.getElementById('uptime').textContent =
    h > 0 ? `${h}h ${m}m ${sec}s` : m > 0 ? `${m}m ${sec}s` : `${sec}s`;

  // Speed
  const spd = (d.speed || 0).toFixed(2);
  document.getElementById('speedVal').textContent  = spd;
  document.getElementById('trainSpeed').textContent = spd;
  document.getElementById('testSpeed').textContent  = spd;

  // Sync PWM sliders
  if (d.pwm !== undefined) {
    currentPwm = d.pwm;
    document.getElementById('pwmSlider').value  = d.pwm;
    document.getElementById('pwmSliderT').value = d.pwm;
    document.getElementById('pwmDisp').textContent  = d.pwm;
    document.getElementById('pwmDispT').textContent = d.pwm;
  }

  // Motor running state
  if (d.running !== undefined) {
    isRunning = d.running;
    document.getElementById('btnGo').classList.toggle('active', isRunning);
  }

  // Mode from firmware
  if (d.mode && d.mode !== currentMode) {
    setModeUI(d.mode);
  }

  // Gauges
  if (d.mode === 'train' || currentMode === 'train') {
    updateGauges('', d.std, d.rms, d.p2p, d.zcr);
    // Auto-log to trainRows if recording
    if (isRecording && d.actual) {
      trainRows.push([d.std, d.rms, d.p2p, d.zcr, d.speed, d.pwm, d.actual, d.uptime*1000].join(','));
      document.getElementById('recCount').textContent = trainRows.length + ' samples';
    }
  }

  if (d.mode === 'test') {
    updateGauges('t', d.std, d.rms, d.p2p, d.zcr);

    // Prediction display
    const pred = (d.predicted || '').toUpperCase();
    const pEl = document.getElementById('predValue');
    pEl.textContent = pred || '—';
    pEl.setAttribute('data-t', d.predicted || '');

    const conf = Math.round((d.confidence || 0) * 100);
    document.getElementById('confBar').style.width  = conf + '%';
    document.getElementById('confLabel').textContent = 'Confidence: ' + conf + '%';

    // Feedback pending → new window → reset UI
    if (d.feedback_pending) {
      resetFeedbackUI();
    }

    // Stats
    const tot  = d.total_predictions || 0;
    const ok   = d.total_correct     || 0;
    const err  = tot - ok;
    const pct  = tot > 0 ? Math.round(ok/tot*100) : 0;
    document.getElementById('sTot').textContent   = tot;
    document.getElementById('sOk').textContent    = ok;
    document.getElementById('sErr').textContent   = err;
    document.getElementById('accBar').style.width = pct + '%';
    document.getElementById('accPct').textContent = pct + '%';
  }
}

function updateGauges(prefix, std, rms, p2p, zcr) {
  const p = prefix;
  setGauge(p+'gStd', p+'vStd', std,  0.5,  v => v.toFixed(3));
  setGauge(p+'gRms', p+'vRms', rms,  0.5,  v => v.toFixed(3));
  setGauge(p+'gP2p', p+'vP2p', p2p,  2.0,  v => v.toFixed(3));
  setGauge(p+'gZcr', p+'vZcr', zcr,  100,  v => Math.round(v));
}

function setGauge(barId, valId, val, max, fmt) {
  const pct = Math.min(100, Math.round((val / max) * 100));
  document.getElementById(barId).style.width      = pct + '%';
  document.getElementById(valId).textContent = fmt(val || 0);
}

// ─── Mode switching ───────────────────────────────────────────────────────────
function switchMode(m) {
  send({ cmd: 'mode', value: m });
  setModeUI(m);
}

function setModeUI(m) {
  currentMode = m;
  document.getElementById('trainPanel').classList.toggle('hidden', m !== 'train');
  document.getElementById('testPanel') .classList.toggle('hidden', m !== 'test');
  document.getElementById('btnTrain').classList.toggle('active', m === 'train');
  document.getElementById('btnTest') .classList.toggle('active', m === 'test');
}

// ─── Terrain label ────────────────────────────────────────────────────────────
function setLabel(t) {
  document.querySelectorAll('#trainPanel .terrain-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.t === t);
  });
  send({ cmd: 'label', value: t });
}

// ─── Motor control ────────────────────────────────────────────────────────────
function onPwmChange(v) {
  currentPwm = parseInt(v);
  document.getElementById('pwmDisp').textContent  = v;
  document.getElementById('pwmDispT').textContent = v;
  document.getElementById('pwmSlider').value  = v;
  document.getElementById('pwmSliderT').value = v;
  send({ cmd: 'pwm', value: currentPwm });
}

function sendGo() {
  send({ cmd: 'go' });
  document.getElementById('btnGo').classList.add('active');
}

function sendStop() {
  send({ cmd: 'stop' });
  document.getElementById('btnGo').classList.remove('active');
}

function sendDir(dir) {
  // dir: 'go' (forward) or 'back' (backward)
  if (dir === 'go')   send({ cmd: 'go' });
  if (dir === 'back') send({ cmd: 'back' });
  document.getElementById('btnGo').classList.add('active');
}

function sendTurn(dir) {
  // dir: 'left' | 'right'
  send({ cmd: 'turn', dir: dir });
  document.getElementById('btnGo').classList.add('active');
}

function sendSpin(dir) {
  // dir: 'left' | 'right'
  send({ cmd: 'spin', dir: dir });
  document.getElementById('btnGo').classList.add('active');
}

// ─── Feedback (Testing Mode) ──────────────────────────────────────────────────
function resetFeedbackUI() {
  document.getElementById('btnYes').disabled = false;
  document.getElementById('btnNo').disabled  = false;
  document.getElementById('fbResult').classList.add('hidden');
  document.getElementById('fbPrompt').classList.remove('hidden');
  document.getElementById('corrPanel').classList.remove('visible');
}

function giveFeedback(correct) {
  document.getElementById('btnYes').disabled = true;
  document.getElementById('btnNo').disabled  = true;
  document.getElementById('fbPrompt').classList.add('hidden');

  if (correct) {
    send({ cmd: 'feedback', correct: true });
    showFbResult(true, null);
  } else {
    // Show correction panel; feedback sent after terrain selected
    document.getElementById('corrPanel').classList.add('visible');
  }
}

function sendCorrection(terrain) {
  send({ cmd: 'feedback', correct: false, actual: terrain });
  document.querySelectorAll('#corrPanel .terrain-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.t === terrain);
  });
  showFbResult(false, terrain);
  // Log to feedbackRows buffer
  if (isRecording) {
    const pv = document.getElementById('predValue').textContent.toLowerCase();
    feedbackRows.push([
      document.getElementById('tvStd').textContent,
      document.getElementById('tvRms').textContent,
      document.getElementById('tvP2p').textContent,
      document.getElementById('tvZcr').textContent,
      document.getElementById('testSpeed').textContent,
      currentPwm, pv, terrain, 0, Date.now()
    ].join(','));
  }
}

function showFbResult(correct, correctedTerrain) {
  const el = document.getElementById('fbResult');
  el.classList.remove('hidden', 'correct', 'incorrect');
  if (correct) {
    el.classList.add('correct');
    el.textContent = '✓ Correct — logged!';
    if (isRecording) {
      const pv = document.getElementById('predValue').textContent.toLowerCase();
      feedbackRows.push([
        document.getElementById('tvStd').textContent,
        document.getElementById('tvRms').textContent,
        document.getElementById('tvP2p').textContent,
        document.getElementById('tvZcr').textContent,
        document.getElementById('testSpeed').textContent,
        currentPwm, pv, pv, 1, Date.now()
      ].join(','));
    }
  } else {
    el.classList.add('incorrect');
    const t = correctedTerrain ? correctedTerrain.toUpperCase() : '?';
    el.textContent = `✗ Wrong — corrected to ${t}`;
  }
}

// ─── Recording ────────────────────────────────────────────────────────────────
function toggleRec() {
  isRecording = !isRecording;
  send({ cmd: 'rec', value: isRecording });

  ['btnRec','btnRecT'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.classList.toggle('active', isRecording);
  });

  const statusText = isRecording ? 'Recording…' : 'Not recording';
  document.getElementById('recStatus').textContent  = statusText;
  document.getElementById('recStatusT').textContent = statusText;

  if (!isRecording) {
    document.getElementById('recCount').textContent = '';
  }
}

// ─── CSV download ─────────────────────────────────────────────────────────────
function downloadCSV(type) {
  let header, rows, filename;

  if (type === 'train') {
    header   = 'std,rms,p2p,zcr,speed,pwm,label,timestamp_ms';
    rows     = trainRows;
    filename = 'train_dataset.csv';
  } else {
    header   = 'std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms';
    rows     = feedbackRows;
    filename = 'feedback_log.csv';
  }

  if (rows.length === 0) {
    alert('No data recorded yet. Start recording first.');
    return;
  }

  const csv  = header + '\n' + rows.join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
connect();
</script>
</body>
</html>
)rawhtml";
