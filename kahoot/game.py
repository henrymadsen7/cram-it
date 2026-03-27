#!/usr/bin/env python3
"""
Cram-It Kahoot-Style Battle Mode
Flask-SocketIO real-time quiz game.
Host on computer screen, players on mobile phones.
"""
import json, time, math, os, re, hashlib
from pathlib import Path
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, join_room
from dotenv import load_dotenv
import anthropic

# Load .env from project root or home .hermes
_project_root = Path(__file__).resolve().parent.parent
_env_paths = [_project_root / ".env", Path.home() / ".hermes/.env"]
for _ep in _env_paths:
    if _ep.exists():
        load_dotenv(_ep)
        break
claude = anthropic.Anthropic()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
socketio = SocketIO(app, cors_allowed_origins="*")

# Game state
game = {
    "phase": "lobby",  # lobby, question, answering, reveal, leaderboard, podium
    "players": {},      # sid -> {name, score, streak, answers: []}
    "questions": [],
    "current_q": -1,
    "q_start_time": 0,
    "answers_received": {},
    "timer": 60,
}

TIMER_SECONDS = 60
MAX_POINTS = 1000

# ============================================================
# QUESTION BANK (pre-generated, cycles through 5 games)
# ============================================================

# Load battle_bank.json from active pack directory (CRAM_IT_PACK env var) or local dir
_pack_dir = Path(os.environ.get('CRAM_IT_PACK', str(Path(__file__).parent)))
BATTLE_BANK_PATH = _pack_dir / "battle_bank.json"
_battle_bank = []
_bank_game_count = 0
_bank_used_ids = set()

def _load_battle_bank():
    global _battle_bank
    if not _battle_bank and BATTLE_BANK_PATH.exists():
        with open(BATTLE_BANK_PATH) as f:
            _battle_bank = json.load(f)
        print(f"  Loaded {len(_battle_bank)} questions from battle bank")
    return _battle_bank

def generate_battle_questions():
    """Pull 10 questions from the pre-generated bank. Cycles every 5 games."""
    global _bank_game_count, _bank_used_ids
    import random
    
    bank = _load_battle_bank()
    if not bank:
        print("  WARNING: No battle bank found, using defaults")
        return default_questions()
    
    _bank_game_count += 1
    
    # Reset used IDs every 5 games (full cycle through bank)
    if _bank_game_count > 5:
        _bank_game_count = 1
        _bank_used_ids = set()
        print("  Bank cycle reset — fresh 50 questions available")
    
    # Pick 10 unused questions (good mix of conceptual + calculation)
    available = [q for q in bank if q.get("battle_id") not in _bank_used_ids]
    if len(available) < 10:
        # Not enough unused — reset early
        _bank_used_ids = set()
        available = bank[:]
        print("  Early bank reset — all questions available again")
    
    # Ensure mix: ~5 conceptual + ~5 calculation
    conceptual = [q for q in available if q.get("question_type") == "conceptual"]
    calculation = [q for q in available if q.get("question_type") == "calculation"]
    
    random.shuffle(conceptual)
    random.shuffle(calculation)
    
    selected = []
    selected.extend(conceptual[:5])
    selected.extend(calculation[:5])
    
    # Backfill if one category is short
    while len(selected) < 10 and (conceptual or calculation):
        pool = conceptual[5:] + calculation[5:]
        if pool:
            selected.append(pool.pop(0))
        else:
            break
    
    random.shuffle(selected)
    
    # Mark as used
    for q in selected:
        bid = q.get("battle_id")
        if bid:
            _bank_used_ids.add(bid)
    
    # Format for battle (ensure consistent fields)
    formatted = []
    for q in selected:
        formatted.append({
            "type": q.get("type", "mc"),
            "question": q["question"],
            "choices": q.get("choices", {}),
            "correct": q["correct"],
            "explanation": q.get("explanation", ""),
            "concept": q.get("concept", "general"),
            "points": 1000,
            "source": q.get("source", "battle_bank"),
        })
    
    print(f"  Game #{_bank_game_count}: {len(formatted)} questions ({len(_bank_used_ids)}/{len(bank)} total used)")
    return formatted

def default_questions():
    return [
        {"type":"mc","question":"Sample question A — replace with your own content.","choices":{"a":"Option 1","b":"Option 2","c":"Option 3","d":"Option 4"},"correct":"B","explanation":"Option 2 is correct because...","concept":"general","points":1000},
        {"type":"tf","question":"Sample true/false question — replace with your own content.","correct":"true","explanation":"This statement is true because...","concept":"general","points":1000},
        {"type":"mc","question":"Sample question B — replace with your own content.","choices":{"a":"Option 1","b":"Option 2","c":"Option 3","d":"Option 4"},"correct":"A","explanation":"Option 1 is correct because...","concept":"general","points":1000},
        {"type":"mc","question":"Sample question C — replace with your own content.","choices":{"a":"Option 1","b":"Option 2","c":"Option 3","d":"Option 4"},"correct":"C","explanation":"Option 3 is correct because...","concept":"general","points":1000},
        {"type":"free","question":"Sample free response — replace with your own content.","correct":"A complete answer covers X, Y, and Z.","explanation":"The key concepts are...","concept":"general","points":1000},
    ]

def grade_free_response(question, correct_answer, player_answer, explanation):
    """Use Claude to grade a free response answer 0-100."""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": f"""Grade this answer 0-100.

Question: {question}
Expected answer: {correct_answer}
Key concepts: {explanation}
Student answer: {player_answer}

Score 0-100 based on accuracy and completeness. 
Return ONLY JSON: {{"score": 85, "feedback": "brief feedback"}}"""}],
        )
        text = response.content[0].text
        result = json.loads(re.search(r'\{[^}]+\}', text).group())
        return result.get("score", 0), result.get("feedback", "")
    except:
        # Fallback: simple keyword match
        keywords = correct_answer.lower().split()
        matches = sum(1 for k in keywords if k in player_answer.lower())
        score = min(100, round(100 * matches / max(len(keywords), 1)))
        return score, "Auto-graded by keyword match"

def calculate_points(response_time_ms, timer_ms, max_points=1000):
    """Kahoot scoring: faster correct answers = more points."""
    if response_time_ms < 500:
        return max_points
    ratio = (response_time_ms / timer_ms) / 2
    score = round((1 - ratio) * max_points)
    return max(0, min(max_points, score))

def generate_reveal_explanation(question, correct_answer, player_results):
    """Generate a concise explanation based on how players answered."""
    all_correct = all(p['correct'] for p in player_results)
    all_wrong = all(not p['correct'] for p in player_results)
    
    wrong_answers = [p for p in player_results if not p['correct']]
    wrong_picks = ", ".join([f"{p['name']} picked {p['answer']}" for p in wrong_answers])
    
    if all_correct:
        mode = "both_right"
        tone = "Both players got this right. Quick validation:"
    elif all_wrong:
        mode = "both_wrong"
        tone = "Both players missed this. Here's why the answer is " + correct_answer + ":"
    else:
        mode = "split"
        tone = f"{wrong_picks}. Here's why {correct_answer} is correct:"
    
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": f"""You are a tutor. {tone}

Question: {question['question']}
Correct answer: {correct_answer}
Concept: {question.get('concept', '')}
Existing explanation: {question.get('explanation', '')}

{"Give a 1-sentence validation confirming why this is correct." if mode == "both_right" else "Give a 2-3 sentence explanation: why the correct answer is right, and reference the key underlying principle. Be concise and clear."}

Return ONLY the explanation text, no JSON."""}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return question.get('explanation', 'The correct answer is ' + correct_answer)


# ============================================================
# ROUTES
# ============================================================

HOST_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CRAM-IT BATTLE</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1a0a2e;color:#fff;height:100vh;overflow:hidden;display:flex;flex-direction:column}
.lobby{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:20px}
.lobby h1{font-size:3rem;background:linear-gradient(135deg,#818cf8,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800}
.lobby .pin{font-size:1.4rem;color:#a78bfa;letter-spacing:2px}
.lobby .players{display:flex;gap:16px;margin-top:20px}
.lobby .player-card{background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.1);border-radius:12px;padding:20px 32px;text-align:center;font-size:1.2rem;font-weight:600;min-width:140px}
.lobby .player-card.p1{border-color:#818cf8;background:rgba(129,140,248,.12)}
.lobby .player-card.p2{border-color:#f472b6;background:rgba(244,114,182,.12)}
.lobby .start-btn{background:linear-gradient(135deg,#818cf8,#6366f1);border:none;color:#fff;padding:14px 48px;border-radius:12px;font-size:1.2rem;font-weight:700;cursor:pointer;margin-top:20px;transition:.2s}
.lobby .start-btn:hover{transform:scale(1.05)}
.lobby .start-btn:disabled{opacity:.4;cursor:not-allowed;transform:none}

.game-screen{display:none;flex:1;flex-direction:column}
.game-screen.active{display:flex}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:12px 24px;background:rgba(0,0,0,.3)}
.topbar .qnum{font-size:1rem;color:#a78bfa}
.topbar .timer{font-size:2rem;font-weight:800;font-family:monospace}
.topbar .timer.red{color:#f87171;animation:pulse .5s infinite}
@keyframes pulse{50%{opacity:.5}}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes hostTaunt{0%{opacity:0;transform:translateX(0) scale(.5)}15%{opacity:1;transform:translateX(150px) scale(1.3)}30%{transform:translateX(140px) scale(1.1)}70%{transform:translateX(140px) scale(1.1);opacity:1}100%{transform:translateX(150px) scale(.5);opacity:0}}

.question-area{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:20px}
.q-text{font-size:1.8rem;font-weight:600;text-align:center;max-width:900px;line-height:1.5}
.answers-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;width:100%;max-width:800px;margin-top:20px}
.ans-block{border-radius:12px;padding:20px;font-size:1.2rem;font-weight:600;display:flex;align-items:center;gap:12px;min-height:80px}
.ans-block .icon{font-size:1.5rem}
.ans-block.a{background:#e21b3c}.ans-block.b{background:#1368ce}
.ans-block.c{background:#d89e00}.ans-block.d{background:#26890c}
.ans-block.tf-true{background:#26890c}.ans-block.tf-false{background:#e21b3c}
.ans-block.correct{box-shadow:0 0 0 4px #fff;transform:scale(1.05)}
.ans-block.wrong{opacity:.3}
.ans-block .count{margin-left:auto;background:rgba(0,0,0,.3);padding:4px 12px;border-radius:20px;font-size:.9rem}

.answered-bar{font-size:1.2rem;color:#a78bfa;margin-top:12px}

/* Leaderboard */
.leaderboard{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:20px}
.lb-title{font-size:2rem;font-weight:800;color:#a78bfa}
.lb-row{display:flex;align-items:center;gap:16px;background:rgba(255,255,255,.06);border-radius:12px;padding:16px 32px;min-width:400px}
.lb-row .rank{font-size:2rem;font-weight:800;min-width:50px}
.lb-row .name{font-size:1.3rem;font-weight:600;flex:1}
.lb-row .pts{font-size:1.3rem;font-weight:700;font-family:monospace;color:#fbbf24}
.lb-row.first{border:2px solid #fbbf24;background:rgba(251,191,36,.1)}

/* Podium */
.podium{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:24px}
.podium h1{font-size:2.5rem;font-weight:800;background:linear-gradient(135deg,#fbbf24,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.podium-row{display:flex;gap:40px;align-items:flex-end}
.podium-place{text-align:center;display:flex;flex-direction:column;align-items:center}
.podium-avatar{width:80px;height:80px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2.5rem;margin-bottom:8px}
.podium-avatar.p1-av{background:linear-gradient(135deg,#818cf8,#6366f1)}
.podium-avatar.p2-av{background:linear-gradient(135deg,#f472b6,#ec4899)}
.podium-name{font-size:1.3rem;font-weight:700;margin-bottom:4px}
.podium-score{font-size:1.1rem;color:#fbbf24;font-family:monospace;font-weight:700}
.podium-bar{border-radius:8px 8px 0 0;min-width:120px;display:flex;align-items:flex-start;justify-content:center;padding-top:12px;font-size:2rem;font-weight:800}
.podium-bar.first{background:linear-gradient(180deg,#fbbf24,#f59e0b);height:180px;color:#000}
.podium-bar.second{background:linear-gradient(180deg,#94a3b8,#64748b);height:120px;color:#fff}

.free-answers{margin-top:12px;display:flex;gap:20px}
.free-card{background:rgba(255,255,255,.06);border-radius:12px;padding:16px;min-width:300px;text-align:center}
.free-card .fname{font-weight:700;font-size:1.1rem;margin-bottom:6px}
.free-card .ftext{font-size:1rem;color:#d4d4d4;margin-bottom:8px;font-style:italic}
.free-card .fscore{font-size:1.5rem;font-weight:800;color:#fbbf24;font-family:monospace}
.free-card .ffeedback{font-size:.8rem;color:#a78bfa;margin-top:4px}
</style>
</head><body>

<div class="lobby" id="lobby">
  <h1>⚡ CRAM-IT BATTLE</h1>
  <div class="pin">Kahoot-Style • 10 Questions</div>
  <div class="players" id="player-list"></div>
  <button class="start-btn" id="start-btn" disabled onclick="startGame()">WAITING FOR PLAYERS...</button>
</div>

<div class="game-screen" id="game-screen">
  <div class="topbar">
    <span class="qnum" id="qnum">Q1/10</span>
    <span class="timer" id="timer">60</span>
    <span id="concept-tag" style="color:#a78bfa;font-size:.9rem"></span>
  </div>
  <div class="question-area" id="q-area"></div>
</div>

<div class="leaderboard" id="leaderboard" style="display:none">
  <div class="lb-title" id="lb-title">LEADERBOARD</div>
  <div id="lb-rows"></div>
  <button class="start-btn" style="margin-top:20px" onclick="nextQuestion()">NEXT →</button>
</div>

<div class="podium" id="podium" style="display:none">
  <h1>🏆 FINAL RESULTS 🏆</h1>
  <div class="podium-row" id="podium-row"></div>
  <button class="start-btn" style="margin-top:24px" onclick="resetGame()">PLAY AGAIN</button>
</div>

<script>
const socket=io({reconnection:true,reconnectionAttempts:20,reconnectionDelay:1000});
let timerInterval=null;

// Host audio engine
const SFX={};
['game_start','leaderboard','victory','correct','wrong','tick',
 'taunt_p1','taunt_p2',
 'music_thinking_1','music_thinking_2','music_thinking_3',
 'music_thinking_4','music_thinking_5','music_thinking_6','music_thinking_7'].forEach(name=>{
  const a=new Audio('/audio/'+name+'.m4a');
  a.preload='auto';a.volume=name.startsWith('music')?0.3:name.startsWith('taunt')?1.0:0.6;SFX[name]=a;
});
let musicTrack=null;
function hplay(name){
  const s=SFX[name];if(!s)return;
  if(name.startsWith('music')){
    if(musicTrack){musicTrack.pause();musicTrack.currentTime=0}
    s.loop=true;s.volume=0.3;s.play().catch(()=>{});musicTrack=s;
  }else{const c=s.cloneNode();c.volume=s.volume;c.play().catch(()=>{});}
}
function hstopMusic(){if(musicTrack){musicTrack.pause();musicTrack.currentTime=0;musicTrack=null}}

socket.emit('host_join');
socket.on('connect',()=>{socket.emit('host_join');});

socket.on('lobby_update',(data)=>{
  const el=document.getElementById('player-list');
  el.innerHTML='';
  for(const p of data.players){
    const pIdx=data.players.indexOf(p);
    const cls=pIdx===0?'p1':'p2';
    const avImg=p.avatar?`<img src="${p.avatar}" style="width:80px;height:80px;border-radius:50%;border:3px solid rgba(255,255,255,.2);margin-bottom:8px">`:'';
    el.innerHTML+=`<div class="player-card ${cls}" style="display:flex;flex-direction:column;align-items:center">${avImg}<span>${p.name}</span></div>`;
  }
  // Store player data for podium and taunt color mapping
  window._players=data.players;
  window._playerMap={};data.players.forEach(p=>{window._playerMap[p.name]=p.avatar||''});
  const btn=document.getElementById('start-btn');
  if(data.players.length>=2){btn.disabled=false;btn.textContent='START GAME'}
  else{btn.disabled=true;btn.textContent=`WAITING... (${data.players.length}/2)`}
});

socket.on('show_question',(data)=>{
  document.getElementById('lobby').style.display='none';
  document.getElementById('leaderboard').style.display='none';
  document.getElementById('podium').style.display='none';
  const gs=document.getElementById('game-screen');
  gs.classList.add('active');
  // Play thinking music (cycles through 7 tracks)
  const trackNum=((data.index||0)%7)+1;
  hplay('music_thinking_'+trackNum);
  
  document.getElementById('qnum').textContent=`Q${data.index+1}/${data.total}`;
  document.getElementById('concept-tag').textContent=data.concept||'';
  
  const area=document.getElementById('q-area');
  let html=`<div class="q-text">${data.question}</div>`;
  
  if(data.type==='mc'){
    html+=`<div class="answers-grid">`;
    const labels=['a','b','c','d'];
    const icons=['▲','◆','●','■'];
    for(const[k,v]of Object.entries(data.choices)){
      const i=labels.indexOf(k);
      html+=`<div class="ans-block ${k}" id="ans-${k}"><span class="icon">${icons[i]}</span>${v}<span class="count" id="cnt-${k}">0</span></div>`;
    }
    html+=`</div>`;
  } else if(data.type==='tf'){
    html+=`<div class="answers-grid" style="max-width:500px">
      <div class="ans-block tf-true" id="ans-true"><span class="icon">✓</span>TRUE<span class="count" id="cnt-true">0</span></div>
      <div class="ans-block tf-false" id="ans-false"><span class="icon">✗</span>FALSE<span class="count" id="cnt-false">0</span></div>
    </div>`;
  } else if(data.type==='free'){
    html+=`<div style="font-size:1.1rem;color:#a78bfa;margin-top:12px">✏️ Players are typing their answers...</div>`;
  }
  
  html+=`<div class="answered-bar" id="answered-bar" style="display:none"></div>`;
  area.innerHTML=html;
  
  // Start timer
  let timeLeft=data.timer;
  const timerEl=document.getElementById('timer');
  timerEl.textContent=timeLeft;timerEl.classList.remove('red');
  if(timerInterval)clearInterval(timerInterval);
  timerInterval=setInterval(()=>{
    timeLeft--;
    timerEl.textContent=timeLeft;
    if(timeLeft<=10){timerEl.classList.add('red');hplay('tick')}
    if(timeLeft<=0){clearInterval(timerInterval);socket.emit('host_time_up')}
  },1000);
});

socket.on('answer_update',(data)=>{
  document.getElementById('answered-bar').textContent=`${data.answered}/${data.total} answered`;
  // Update answer counts for MC/TF
  if(data.distribution){
    for(const[k,v]of Object.entries(data.distribution)){
      const el=document.getElementById('cnt-'+k);
      if(el)el.textContent=v;
    }
  }
});

socket.on('question_result',(data)=>{
  if(timerInterval)clearInterval(timerInterval);
  
  if(data.type==='mc'){
    // Highlight correct, dim wrong
    ['a','b','c','d'].forEach(k=>{
      const el=document.getElementById('ans-'+k);
      if(el){
        if(k===data.correct.toLowerCase())el.classList.add('correct');
        else el.classList.add('wrong');
      }
    });
  } else if(data.type==='tf'){
    ['true','false'].forEach(k=>{
      const el=document.getElementById('ans-'+k);
      if(el){
        if(k===data.correct.toLowerCase())el.classList.add('correct');
        else el.classList.add('wrong');
      }
    });
  } else if(data.type==='free'){
    // Show both answers with grades
    const area=document.getElementById('q-area');
    let html=area.innerHTML;
    html+=`<div class="free-answers">`;
    for(const p of data.free_results||[]){
      html+=`<div class="free-card">
        <div class="fname">${p.name}</div>
        <div class="ftext">"${p.answer||'(no answer)'}"</div>
        <div class="fscore">+${p.points}</div>
        <div class="ffeedback">${p.feedback||''}</div>
      </div>`;
    }
    html+=`</div>`;
    area.innerHTML=html;
  }
});

socket.on('show_countdown',(data)=>{
  // Show a countdown overlay before explanation
  const area=document.getElementById('q-area');
  const existing=document.getElementById('countdown-overlay');
  if(existing)existing.remove();
  const overlay=document.createElement('div');
  overlay.id='countdown-overlay';
  overlay.style.cssText='position:fixed;bottom:24px;right:24px;background:rgba(0,0,0,.7);border-radius:12px;padding:12px 20px;font-size:1rem;color:#a78bfa;backdrop-filter:blur(4px);z-index:10';
  overlay.textContent='Generating explanation...';
  document.body.appendChild(overlay);
});

socket.on('show_explanation',(data)=>{
  hstopMusic();
  // Remove countdown overlay
  const overlay=document.getElementById('countdown-overlay');
  if(overlay)overlay.remove();
  
  const area=document.getElementById('q-area');
  const allCorrect=data.all_correct;
  const borderColor=allCorrect?'#34d399':'#818cf8';
  const icon=allCorrect?'✓':'📖';
  
  // Build player result badges
  let badges='';
  for(const p of data.player_results||[]){
    const col=p.correct?'#34d399':'#f87171';
    const mark=p.correct?'✓':'✗';
    badges+=`<span style="display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,.06);padding:4px 10px;border-radius:8px;font-size:.85rem;border:1px solid ${col}"><span style="color:${col};font-weight:700">${mark}</span> ${p.name}</span> `;
  }
  
  // Insert explanation panel below the question
  const explDiv=document.createElement('div');
  explDiv.style.cssText=`margin-top:16px;max-width:800px;width:100%;padding:20px 24px;background:rgba(255,255,255,.04);border-left:3px solid ${borderColor};border-radius:0 12px 12px 0;animation:fadeIn .4s ease`;
  explDiv.innerHTML=`
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:1.3rem">${icon}</span>
      <span style="font-size:.8rem;color:${borderColor};font-weight:600;text-transform:uppercase;letter-spacing:1px">${allCorrect?'Both Correct!':'Explanation'}</span>
      ${data.concept?`<span style="font-size:.75rem;color:#64748b;margin-left:auto">${data.concept.replace(/_/g,' ')}</span>`:''}
    </div>
    <div style="font-size:1.1rem;line-height:1.6;color:#e2e0dc">${data.text}</div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">${badges}</div>
  `;
  area.appendChild(explDiv);
});

socket.on('show_leaderboard',(data)=>{
  hplay('leaderboard');
  document.getElementById('game-screen').classList.remove('active');
  document.getElementById('leaderboard').style.display='flex';
  
  const el=document.getElementById('lb-rows');
  el.innerHTML='';
  data.rankings.forEach((p,i)=>{
    const cls=i===0?'first':'';
    const avImg=p.avatar?`<img src="${p.avatar}" style="width:44px;height:44px;border-radius:50%;border:2px solid rgba(255,255,255,.15)">`:'';
    el.innerHTML+=`<div class="lb-row ${cls}">
      <span class="rank">${i+1}</span>
      ${avImg}
      <span class="name">${p.name}</span>
      <span class="pts">${p.score} pts</span>
    </div>`;
  });
});

socket.on('show_podium',(data)=>{
  hplay('victory');
  document.getElementById('leaderboard').style.display='none';
  document.getElementById('game-screen').classList.remove('active');
  document.getElementById('podium').style.display='flex';
  
  const row=document.getElementById('podium-row');
  const sorted=data.rankings;
  
  // Match avatars from stored player data
  const playerMap={};
  (window._players||[]).forEach(p=>{playerMap[p.name]=p.avatar||''});
  
  let html='';
  sorted.forEach((p,i)=>{
    const av=p.avatar||playerMap[p.name]||'';
    const barClass=i===0?'first':'second';
    const medal=i===0?'🥇':'🥈';
    const crown=i===0?'<div style="font-size:2.5rem;margin-bottom:-8px">👑</div>':'';
    html+=`<div class="podium-place">
      ${crown}
      ${av?`<img src="${av}" style="width:100px;height:100px;border-radius:50%;border:4px solid ${i===0?'#fbbf24':'#94a3b8'};margin-bottom:8px">`:`<div class="podium-avatar" style="background:#333;font-size:2rem">${p.name[0]}</div>`}
      <div class="podium-name">${p.name}</div>
      <div class="podium-score">${p.score} pts</div>
      <div class="podium-bar ${barClass}">${medal}</div>
    </div>`;
  });
  row.innerHTML=html;
});

function startGame(){hplay('game_start');socket.emit('host_start_game')}
function nextQuestion(){socket.emit('host_next_question')}
function resetGame(){socket.emit('host_reset_game');location.reload()}

// Taunt display on host screen
socket.on('taunt_received',(data)=>{
  const side=Math.random()>.5?'left':'right';
  const div=document.createElement('div');
  div.style.cssText=`position:fixed;z-index:999;${side}:-140px;top:30%;pointer-events:none;animation:hostTaunt .6s ease-out forwards`;
  const pNames=Object.keys(window._playerMap||{});
  const isP1=pNames.indexOf(data.name)===0;
  const tColor=isP1?'#818cf8':'#f472b6';
  div.innerHTML=data.avatar?
    `<img src="${data.avatar}" style="width:120px;height:120px;border-radius:50%;border:5px solid ${tColor}">`:
    `<div style="width:120px;height:120px;border-radius:50%;background:${tColor};display:flex;align-items:center;justify-content:center;font-size:3rem;font-weight:800;color:#fff">${data.name[0]}</div>`;
  document.body.appendChild(div);
  hplay(isP1?'taunt_p1':'taunt_p2');
  setTimeout(()=>div.remove(),700);
});
</script>
</body></html>"""


PLAYER_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>CRAM-IT BATTLE</title>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1a0a2e;color:#fff;height:100dvh;overflow:hidden;display:flex;flex-direction:column}
.join{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100dvh;gap:16px;padding:20px}
.join h2{font-size:1.5rem;color:#a78bfa}
.join .name-btns{display:flex;gap:12px}
.join .nbtn{background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.15);border-radius:12px;padding:20px 32px;font-size:1.2rem;font-weight:700;color:#fff;cursor:pointer;-webkit-tap-highlight-color:transparent}
.join .nbtn.p1{border-color:#818cf8}.join .nbtn.p2{border-color:#f472b6}
.join .nbtn:active{transform:scale(.95)}

.waiting{display:none;flex-direction:column;align-items:center;justify-content:center;height:100dvh;gap:12px}
.waiting h2{font-size:1.4rem;color:#a78bfa}
.waiting .checkmark{font-size:3rem}

.play{display:none;flex:1;flex-direction:column}
.play.active{display:flex}
.play .status{padding:12px;text-align:center;font-size:.9rem;color:#a78bfa;background:rgba(0,0,0,.3);position:relative}
/* Taunt popup */
.taunt-popup{position:fixed;z-index:999;pointer-events:none;animation:tauntAnim .6s ease-out forwards}
.taunt-popup.left{left:-120px;top:30%}
.taunt-popup.right{right:-120px;top:30%}
@keyframes tauntAnim{0%{opacity:0;transform:translateX(0) scale(.5)}15%{opacity:1;transform:translateX(120px) scale(1.2)}30%{transform:translateX(110px) scale(1)}70%{transform:translateX(110px) scale(1);opacity:1}100%{transform:translateX(120px) scale(.5);opacity:0}}
@keyframes tauntAnimR{0%{opacity:0;transform:translateX(0) scale(.5)}15%{opacity:1;transform:translateX(-120px) scale(1.2)}30%{transform:translateX(-110px) scale(1)}70%{transform:translateX(-110px) scale(1);opacity:1}100%{transform:translateX(-120px) scale(.5);opacity:0}}
.taunt-popup.right{animation-name:tauntAnimR}
.play .btns{flex:1;display:grid;gap:8px;padding:8px}
.play .btns.mc{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr}
.play .btns.tf{grid-template-columns:1fr 1fr;grid-template-rows:1fr}
.play .abtn{border:none;border-radius:16px;font-size:1.3rem;font-weight:700;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;-webkit-tap-highlight-color:transparent;transition:.15s}
.play .abtn:active{transform:scale(.95)}
.play .abtn.a{background:#e21b3c}.play .abtn.b{background:#1368ce}
.play .abtn.c{background:#d89e00}.play .abtn.d{background:#26890c}
.play .abtn.tf-true{background:#26890c}.play .abtn.tf-false{background:#e21b3c}
.play .abtn.selected{box-shadow:inset 0 0 0 4px rgba(255,255,255,.5);transform:scale(.97)}
.play .abtn.locked{opacity:.5;pointer-events:none}

.free-input{flex:1;display:none;flex-direction:column;padding:16px;gap:12px}
.free-input.active{display:flex}
.free-input textarea{flex:1;background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.15);border-radius:12px;color:#fff;padding:16px;font-size:1.1rem;font-family:inherit;resize:none}
.free-input textarea:focus{outline:none;border-color:#818cf8}
.free-input button{background:linear-gradient(135deg,#818cf8,#6366f1);border:none;color:#fff;padding:16px;border-radius:12px;font-size:1.2rem;font-weight:700;cursor:pointer}

.result{display:none;flex-direction:column;align-items:center;justify-content:center;height:100dvh;gap:12px}
.result.active{display:flex}
.result .emoji{font-size:4rem}
.result .msg{font-size:1.5rem;font-weight:700}
.result .pts{font-size:1.2rem;color:#fbbf24;font-family:monospace;font-weight:700}
.result .total{font-size:.9rem;color:#a78bfa}
</style>
</head><body>

<div class="join" id="join">
  <h2>CRAM-IT BATTLE</h2>
  
  <!-- Step 1: Name -->
  <div id="step-name">
    <div style="color:#64748b;font-size:.9rem;margin-bottom:8px">Enter your name:</div>
    <div style="display:flex;gap:12px;align-items:center;flex-direction:column">
      <input id="name-input" type="text" maxlength="20" placeholder="Your name..." style="background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.15);border-radius:12px;padding:14px 20px;font-size:1.2rem;font-weight:700;color:#fff;text-align:center;width:240px;font-family:inherit" autocomplete="off">
      <button class="nbtn p1" onclick="pickName(document.getElementById('name-input').value.trim())" style="cursor:pointer">JOIN →</button>
    </div>
  </div>
  
  <!-- Step 2: Avatar (hidden until name picked) -->
  <div id="step-avatar" style="display:none;text-align:center">
    <div style="color:#a78bfa;font-size:1rem;font-weight:600;margin-bottom:12px">Pick your avatar:</div>
    <div id="avatar-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;max-width:340px;margin:0 auto"></div>
    <button id="go-btn" disabled onclick="confirmJoin()" style="margin-top:16px;background:linear-gradient(135deg,#818cf8,#6366f1);border:none;color:#fff;padding:14px 40px;border-radius:12px;font-size:1.1rem;font-weight:700;cursor:pointer;opacity:.4;transition:.2s">JOIN GAME</button>
  </div>
</div>

<div class="waiting" id="waiting">
  <img id="wait-avatar" src="" style="width:100px;height:100px;border-radius:50%;border:3px solid #818cf8;background:rgba(129,140,248,.1)">
  <h2 id="wait-name">You're in!</h2>
  <div style="color:#64748b">Watch the host screen...</div>
</div>

  <div class="play" id="play">
  <div class="status" id="play-status">Look at the host screen!
    <button id="taunt-btn" onclick="sendTaunt()" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:2px solid rgba(255,255,255,.2);border-radius:10px;padding:4px 10px;font-size:1.1rem;cursor:pointer;-webkit-tap-highlight-color:transparent">😈</button>
  </div>
  <div class="btns mc" id="btn-grid"></div>
  <div class="free-input" id="free-input">
    <div style="text-align:center;color:#a78bfa;font-size:.9rem">Type your answer:</div>
    <textarea id="free-text" placeholder="Your answer..."></textarea>
    <button onclick="submitFree()">SUBMIT</button>
  </div>
</div>

<div class="result" id="result">
  <div class="emoji" id="res-emoji"></div>
  <div class="msg" id="res-msg"></div>
  <div class="pts" id="res-pts"></div>
  <div class="total" id="res-total"></div>
</div>

<script>
const socket=io({reconnection:true,reconnectionAttempts:20,reconnectionDelay:1000});
let myName='';
let myAvatar='';
let answered=false;

// Audio engine
const SFX={};
const AUDIO_FILES=['click','correct','wrong','tick','game_start','leaderboard','victory',
  'taunt_p1','taunt_p2',
  'music_thinking_1','music_thinking_2','music_thinking_3',
  'music_thinking_4','music_thinking_5','music_thinking_6','music_thinking_7'];
let musicTrack=null;
let audioReady=false;

function preloadAudio(){
  AUDIO_FILES.forEach(name=>{
    const a=new Audio('/audio/'+name+'.m4a');
    a.preload='auto';
    a.volume=name.startsWith('music')?0.25:0.7;
    SFX[name]=a;
  });
  audioReady=true;
}
function play(name){
  if(!audioReady)return;
  const s=SFX[name];
  if(!s)return;
  if(name.startsWith('music')){
    if(musicTrack){musicTrack.pause();musicTrack.currentTime=0}
    s.loop=true;s.volume=0.25;s.play().catch(()=>{});musicTrack=s;
  }else{
    const c=s.cloneNode();c.volume=s.volume;c.play().catch(()=>{});
  }
}
function stopMusic(){if(musicTrack){musicTrack.pause();musicTrack.currentTime=0;musicTrack=null}}
function charSelect(){play('click')}
function charConfirm(){play('click')}

// Taunt system
let tauntCooldown=false;
function sendTaunt(){
  if(tauntCooldown||!myName)return;
  tauntCooldown=true;
  socket.emit('player_taunt',{name:myName,avatar:myAvatar});
  document.getElementById('taunt-btn').style.opacity='.3';
  setTimeout(()=>{tauntCooldown=false;document.getElementById('taunt-btn').style.opacity='1'},3000);
}
function showTaunt(data){
  const side=data.name===myName?'right':'left';
  const div=document.createElement('div');
  div.className='taunt-popup '+side;
  const tCol=data.name===myName?'#818cf8':'#f472b6';
  div.innerHTML=data.avatar?
    `<img src="${data.avatar}" style="width:100px;height:100px;border-radius:50%;border:4px solid ${tCol}">`:
    `<div style="width:100px;height:100px;border-radius:50%;background:${tCol};display:flex;align-items:center;justify-content:center;font-size:2.5rem;font-weight:800;color:#fff">${data.name[0]}</div>`;
  document.body.appendChild(div);
  play('taunt_p1');
  setTimeout(()=>div.remove(),700);
}
socket.on('taunt_received',showTaunt);

// Reconnection
socket.on('connect',()=>{
  if(myName&&myAvatar){
    socket.emit('player_join',{name:myName,avatar:myAvatar});
  }
});
socket.on('reconnect_sync',(data)=>{
  // Rejoin mid-game
  document.getElementById('join').style.display='none';
  document.getElementById('waiting').style.display='none';
  document.getElementById('result').classList.remove('active');
  if(data.phase==='playing'&&!data.already_answered&&data.question_type){
    answered=false;
    const playEl=document.getElementById('play');
    playEl.classList.add('active');
    document.getElementById('play-status').textContent=`Reconnected! Q${data.current_q+1}/${data.total}`;
    // Render answer buttons based on question type
    const grid=document.getElementById('btn-grid');
    const freeIn=document.getElementById('free-input');
    if(data.question_type==='mc'){
      grid.className='btns mc';
      grid.innerHTML=['a','b','c','d'].map((k,i)=>{
        const icons=['▲','◆','●','■'];
        return `<button class="abtn ${k}" onclick="pickAnswer('${k}')">${icons[i]}</button>`;
      }).join('');
      grid.style.display='';
      freeIn.classList.remove('active');
    }else if(data.question_type==='tf'){
      grid.className='btns tf';
      grid.innerHTML=`<button class="abtn tf-true" onclick="pickAnswer('true')">✓ TRUE</button>
        <button class="abtn tf-false" onclick="pickAnswer('false')">✗ FALSE</button>`;
      grid.style.display='';
      freeIn.classList.remove('active');
    }else if(data.question_type==='free'){
      grid.style.display='none';
      freeIn.classList.add('active');
    }
    const trackNum=((data.current_q||0)%7)+1;
    play('music_thinking_'+trackNum);
  }else{
    document.getElementById('play').classList.remove('active');
    document.getElementById('waiting').style.display='flex';
    document.getElementById('wait-name').textContent=`Reconnected as ${myName}! (${data.score} pts)`;
  }
});

const AVATARS=[
  {style:'fun-emoji',seed:'happy1',label:'😄'},
  {style:'fun-emoji',seed:'cool2',label:'😎'},
  {style:'fun-emoji',seed:'star3',label:'🌟'},
  {style:'fun-emoji',seed:'fire4',label:'🔥'},
  {style:'bottts',seed:'bot1',label:'🤖'},
  {style:'bottts',seed:'bot2',label:'⚡'},
  {style:'bottts',seed:'bot3',label:'💎'},
  {style:'bottts',seed:'bot4',label:'🎯'},
  {style:'pixel-art',seed:'pix1',label:'👾'},
  {style:'pixel-art',seed:'pix2',label:'🎮'},
  {style:'adventurer',seed:'adv1',label:'⚔️'},
  {style:'adventurer',seed:'adv2',label:'🛡️'},
];

function pickName(name){
  if(!name||name.length<1){alert('Please enter a name');return;}
  myName=name;
  document.getElementById('step-name').style.display='none';
  document.getElementById('step-avatar').style.display='block';
  
  // Build avatar grid
  const grid=document.getElementById('avatar-grid');
  grid.innerHTML='';
  AVATARS.forEach((av,i)=>{
    const url=`https://api.dicebear.com/9.x/${av.style}/svg?seed=${av.seed}&backgroundColor=transparent`;
    const div=document.createElement('div');
    div.style.cssText='cursor:pointer;border:3px solid transparent;border-radius:16px;padding:6px;background:rgba(255,255,255,.04);transition:.15s;-webkit-tap-highlight-color:transparent';
    div.innerHTML=`<img src="${url}" style="width:100%;aspect-ratio:1;border-radius:12px" alt="${av.label}">`;
    div.onclick=()=>{
      document.querySelectorAll('#avatar-grid > div').forEach(d=>d.style.borderColor='transparent');
      div.style.borderColor='#818cf8';
      myAvatar=url;
      const btn=document.getElementById('go-btn');
      btn.disabled=false;btn.style.opacity='1';
    };
    grid.appendChild(div);
  });
}

function confirmJoin(){
  if(!myName||!myAvatar)return;
  preloadAudio();
  play('click');
  socket.emit('player_join',{name:myName,avatar:myAvatar});
  document.getElementById('join').style.display='none';
  document.getElementById('waiting').style.display='flex';
  document.getElementById('wait-name').textContent=`You're in as ${myName}!`;
  document.getElementById('wait-avatar').src=myAvatar;
}

socket.on('question_start',(data)=>{
  answered=false;
  document.getElementById('waiting').style.display='none';
  document.getElementById('result').classList.remove('active');
  const playEl=document.getElementById('play');
  playEl.classList.add('active');
  // Play thinking music (cycles through 7 tracks)
  const trackNum=((data.index||0)%7)+1;
  play('music_thinking_'+trackNum);
  document.getElementById('play-status').textContent=`Q${data.index+1}/${data.total} • ${data.timer}s • Look at host screen!`;
  
  const grid=document.getElementById('btn-grid');
  const freeInput=document.getElementById('free-input');
  
  if(data.type==='mc'){
    grid.style.display='grid';
    grid.className='btns mc';
    freeInput.classList.remove('active');
    const icons=['▲','◆','●','■'];
    grid.innerHTML=['a','b','c','d'].map((k,i)=>
      `<button class="abtn ${k}" onclick="pickAnswer('${k}')">${icons[i]}</button>`
    ).join('');
  } else if(data.type==='tf'){
    grid.style.display='grid';
    grid.className='btns tf';
    freeInput.classList.remove('active');
    grid.innerHTML=`
      <button class="abtn tf-true" onclick="pickAnswer('true')">✓ TRUE</button>
      <button class="abtn tf-false" onclick="pickAnswer('false')">✗ FALSE</button>`;
  } else if(data.type==='free'){
    grid.style.display='none';
    freeInput.classList.add('active');
    document.getElementById('free-text').value='';
    document.getElementById('free-text').focus();
  }
});

function pickAnswer(answer){
  if(answered)return;
  answered=true;
  charSelect();
  stopMusic();
  socket.emit('player_answer',{answer,timestamp:Date.now()});
  document.querySelectorAll('.abtn').forEach(b=>{
    if(b.classList.contains(answer))b.classList.add('selected');
    else b.classList.add('locked');
  });
  document.getElementById('play-status').textContent='Answer locked! ✓';
  setTimeout(()=>charConfirm(),200);
}

function submitFree(){
  if(answered)return;
  answered=true;
  charSelect();
  stopMusic();
  const text=document.getElementById('free-text').value.trim();
  socket.emit('player_answer',{answer:text,timestamp:Date.now()});
  document.getElementById('free-input').innerHTML='<div style="text-align:center;padding:40px;font-size:1.2rem;color:#a78bfa">Answer submitted! ✓</div>';
}

socket.on('answer_result',(data)=>{
  document.getElementById('play').classList.remove('active');
  const res=document.getElementById('result');
  res.classList.add('active');
  if(data.correct){play('correct')}else{play('wrong')}
  document.getElementById('res-emoji').textContent=data.correct?'🎉':'😬';
  document.getElementById('res-msg').textContent=data.correct?'Correct!':'Wrong!';
  document.getElementById('res-pts').textContent=`+${data.points} pts`;
  document.getElementById('res-total').textContent=`Total: ${data.total_score}`;
});

socket.on('free_result',(data)=>{
  document.getElementById('play').classList.remove('active');
  const res=document.getElementById('result');
  res.classList.add('active');
  document.getElementById('res-emoji').textContent=data.score>=70?'🎉':'🤔';
  document.getElementById('res-msg').textContent=`Scored ${data.score}/100`;
  document.getElementById('res-pts').textContent=`+${data.points} pts`;
  document.getElementById('res-total').textContent=`Total: ${data.total_score}`;
});

socket.on('show_explanation_player',(data)=>{
  // Show explanation on player device too
  const res=document.getElementById('result');
  if(res.classList.contains('active')){
    const explDiv=document.createElement('div');
    explDiv.style.cssText='margin-top:12px;padding:12px 14px;background:rgba(255,255,255,.04);border-left:2px solid '+(data.all_correct?'#34d399':'#818cf8')+';border-radius:0 8px 8px 0;font-size:.85rem;line-height:1.5;color:#d4d4d4;max-width:400px;text-align:left';
    explDiv.innerHTML='<div style="font-size:.7rem;color:#a78bfa;font-weight:600;margin-bottom:4px;text-transform:uppercase">'+(data.all_correct?'✓ Both correct':'📖 Explanation')+'</div>'+data.text;
    res.appendChild(explDiv);
  }
});
</script>
</body></html>"""


LANDING_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#1a0a2e">
<title>CRAM-IT BATTLE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#1a0a2e;color:#fff;height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;padding:24px;padding-top:calc(24px + env(safe-area-inset-top,0px));-webkit-tap-highlight-color:transparent}
h1{font-size:2.2rem;background:linear-gradient(135deg,#818cf8,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800;text-align:center}
.sub{color:#a78bfa;font-size:.95rem;text-align:center;letter-spacing:1px}
.cards{display:flex;flex-direction:column;gap:16px;width:100%;max-width:340px;margin-top:12px}
.card{background:rgba(255,255,255,.06);border:2px solid rgba(255,255,255,.1);border-radius:16px;padding:24px;cursor:pointer;transition:all .15s;display:flex;align-items:center;gap:16px}
.card:active{transform:scale(.97)}
.card .icon{width:56px;height:56px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:1.8rem;flex-shrink:0}
.card .info{text-align:left}
.card .title{font-size:1.15rem;font-weight:700;margin-bottom:4px}
.card .desc{font-size:.8rem;color:#94a3b8;line-height:1.4}
.card.host-card{border-color:#818cf8}
.card.host-card .icon{background:linear-gradient(135deg,#818cf8,#6366f1)}
.card.host-card:active{border-color:#a5b4fc;background:rgba(129,140,248,.1)}
.card.play-card{border-color:#f472b6}
.card.play-card .icon{background:linear-gradient(135deg,#f472b6,#ec4899)}
.card.play-card:active{border-color:#f9a8d4;background:rgba(244,114,182,.1)}
.info-text{color:#475569;font-size:.72rem;text-align:center;margin-top:8px;line-height:1.5}
</style>
</head><body>
<h1>⚡ CRAM-IT BATTLE</h1>
<div class="sub">Kahoot-Style Quiz Game</div>
<div class="cards">
  <div class="card host-card" onclick="location.href='/host'">
    <div class="icon">🖥️</div>
    <div class="info">
      <div class="title">Host Game</div>
      <div class="desc">Control the game from this screen. Show questions, manage timer, see scores.</div>
    </div>
  </div>
  <div class="card play-card" onclick="location.href='/play'">
    <div class="icon">📱</div>
    <div class="info">
      <div class="title">Join as Player</div>
      <div class="desc">Pick your name & avatar, answer questions, compete for points!</div>
    </div>
  </div>
</div>
<div class="info-text">Host shows questions on a shared screen.<br>Players answer from their own devices.</div>
</body></html>"""

@app.route('/')
def landing():
    return render_template_string(LANDING_HTML)

@app.route('/host')
def host_page():
    return render_template_string(HOST_HTML)

@app.route('/play')
def player_page():
    return render_template_string(PLAYER_HTML)

@app.route('/audio/<path:fn>')
def serve_audio(fn):
    from flask import send_from_directory
    return send_from_directory(str(Path(__file__).parent / 'audio'), fn)


# ============================================================
# PERSISTENT PLAYER REGISTRY (survives reconnects)
# name -> {name, avatar, score, streak, sid, connected}
# ============================================================
player_registry = {}  # name -> player data (persistent across reconnects)
host_sid = None

def _get_player_by_sid(sid):
    """Find player by current socket ID."""
    for p in player_registry.values():
        if p.get('sid') == sid:
            return p
    return None

def _broadcast_lobby():
    """Send current player list to host + all players."""
    players = [{'name': p['name'], 'avatar': p.get('avatar', ''), 'connected': p.get('connected', False)} for p in player_registry.values()]
    emit('lobby_update', {'players': players}, to='host')
    emit('lobby_update', {'players': players}, to='game')

def _active_players():
    """Players who are connected."""
    return {name: p for name, p in player_registry.items() if p.get('connected')}

# ============================================================
# SOCKET EVENTS
# ============================================================

@socketio.on('host_join')
def handle_host_join():
    global host_sid
    join_room('host')
    host_sid = request.sid
    print("Host connected")
    # Send current state if game in progress
    if game['phase'] != 'lobby':
        emit('game_state_sync', {
            'phase': game['phase'],
            'current_q': game['current_q'],
            'total': len(game.get('questions', [])),
        }, to=request.sid)
    _broadcast_lobby()

@socketio.on('player_join')
def handle_player_join(data):
    name = data['name']
    avatar = data.get('avatar', '')
    sid = request.sid
    
    if name in player_registry:
        # RECONNECT: same player rejoining
        old = player_registry[name]
        old['sid'] = sid
        old['connected'] = True
        if avatar:
            old['avatar'] = avatar
        # Update SID in game players dict too
        old_sids = [s for s, p in game['players'].items() if p.get('name') == name]
        for old_sid in old_sids:
            del game['players'][old_sid]
        game['players'][sid] = old
        join_room('game')
        print(f"Player RECONNECTED: {name} (score: {old['score']})")
        
        # If game is in progress, sync them to current state
        if game['phase'] != 'lobby':
            q_type = None
            q_idx = game['current_q']
            if 0 <= q_idx < len(game.get('questions', [])):
                q_type = game['questions'][q_idx].get('type', 'mc')
            emit('reconnect_sync', {
                'phase': game['phase'],
                'current_q': q_idx,
                'total': len(game.get('questions', [])),
                'score': old['score'],
                'already_answered': sid in game.get('answers_received', {}),
                'question_type': q_type,
            }, to=sid)
    else:
        # NEW player
        player_data = {
            'name': name,
            'avatar': avatar,
            'score': 0,
            'streak': 0,
            'sid': sid,
            'connected': True,
        }
        player_registry[name] = player_data
        game['players'][sid] = player_data
        join_room('game')
        print(f"Player joined: {name} (avatar: {'yes' if avatar else 'no'})")
    
    _broadcast_lobby()

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    player = _get_player_by_sid(sid)
    if player:
        player['connected'] = False
        print(f"Player disconnected: {player['name']} (keeping score: {player['score']})")
        _broadcast_lobby()
    elif sid == host_sid:
        print("Host disconnected (waiting for reconnect)")

@socketio.on('host_start_game')
def handle_start():
    print("Generating questions...")
    game['questions'] = generate_battle_questions()
    game['current_q'] = -1
    game['phase'] = 'playing'
    print(f"Generated {len(game['questions'])} questions")
    send_next_question()

@socketio.on('host_next_question')
def handle_next():
    send_next_question()

@socketio.on('host_time_up')
def handle_time_up():
    process_answers()

@socketio.on('player_taunt')
def handle_taunt(data):
    """Broadcast taunt to host + all players."""
    emit('taunt_received', data, to='host')
    emit('taunt_received', data, to='game')

@socketio.on('host_reset_game')
def handle_reset():
    """Reset game state for a new round."""
    game['phase'] = 'lobby'
    game['questions'] = []
    game['current_q'] = -1
    game['answers_received'] = {}
    # Keep players but reset scores
    for p in player_registry.values():
        p['score'] = 0
        p['streak'] = 0
    for p in game['players'].values():
        p['score'] = 0
        p['streak'] = 0
    print("Game reset for new round")
    _broadcast_lobby()

def send_next_question():
    game['current_q'] += 1
    idx = game['current_q']
    
    if idx >= len(game['questions']):
        # Game over - show podium
        rankings = sorted(game['players'].values(), key=lambda p: p['score'], reverse=True)
        rank_data = [{'name': p['name'], 'score': p['score'], 'avatar': p.get('avatar', '')} for p in rankings]
        emit('show_podium', {'rankings': rank_data}, to='host')
        emit('show_podium', {'rankings': rank_data}, to='game')
        return
    
    q = game['questions'][idx]
    game['answers_received'] = {}
    game['q_start_time'] = time.time() * 1000  # ms
    
    # Send to host (full question)
    host_data = {
        'index': idx,
        'total': len(game['questions']),
        'question': q['question'],
        'type': q['type'],
        'timer': TIMER_SECONDS,
        'player_count': len(game['players']),
        'concept': q.get('concept', ''),
    }
    if q['type'] == 'mc':
        host_data['choices'] = q['choices']
    
    emit('show_question', host_data, to='host')
    
    # Send to players (no question text!)
    player_data = {
        'index': idx,
        'total': len(game['questions']),
        'type': q['type'],
        'timer': TIMER_SECONDS,
    }
    emit('question_start', player_data, to='game')

@socketio.on('player_answer')
def handle_answer(data):
    sid = request.sid
    player = _get_player_by_sid(sid)
    if not player:
        return  # Unknown player
    if sid in game['answers_received']:
        return  # Already answered
    
    game['answers_received'][sid] = {
        'answer': data['answer'],
        'timestamp': data.get('timestamp', time.time() * 1000),
    }
    
    # Update answer count
    q = game['questions'][game['current_q']]
    distribution = {}
    if q['type'] == 'mc':
        for k in ['a','b','c','d']:
            distribution[k] = sum(1 for a in game['answers_received'].values() if a['answer'] == k)
    elif q['type'] == 'tf':
        distribution['true'] = sum(1 for a in game['answers_received'].values() if a['answer'] == 'true')
        distribution['false'] = sum(1 for a in game['answers_received'].values() if a['answer'] == 'false')
    
    emit('answer_update', {
        'answered': len(game['answers_received']),
        'total': len(game['players']),
        'distribution': distribution,
    }, to='host')
    
    # If all players answered, auto-process
    if len(game['answers_received']) >= len(game['players']):
        socketio.sleep(0.5)
        process_answers()

def process_answers():
    q = game['questions'][game['current_q']]
    correct_answer = q['correct']
    
    if q['type'] == 'free':
        process_free_response(q)
        return
    
    # Grade MC and T/F, collect results for explanation
    player_results = []
    for sid, ans_data in game['answers_received'].items():
        player = game['players'].get(sid)
        if not player:
            continue
        
        is_correct = ans_data['answer'].upper() == correct_answer.upper()
        response_time = ans_data['timestamp'] - game['q_start_time']
        
        if is_correct:
            points = calculate_points(response_time, TIMER_SECONDS * 1000)
            player['score'] += points
            player['streak'] += 1
        else:
            points = 0
            player['streak'] = 0
        
        player_results.append({
            'name': player['name'],
            'correct': is_correct,
            'answer': ans_data['answer'].upper(),
            'points': points,
        })
        
        emit('answer_result', {
            'correct': is_correct,
            'points': points,
            'total_score': player['score'],
        }, to=sid)
    
    # Also count players who didn't answer
    for sid, player in game['players'].items():
        if sid not in game['answers_received']:
            player_results.append({
                'name': player['name'],
                'correct': False,
                'answer': '(no answer)',
                'points': 0,
            })
    
    # Send result to host (highlight correct/wrong)
    emit('question_result', {
        'type': q['type'],
        'correct': correct_answer,
    }, to='host')
    
    # 3-second countdown before explanation
    emit('show_countdown', {'seconds': 3}, to='host')
    socketio.sleep(3)
    
    # Generate contextual explanation
    explanation = generate_reveal_explanation(q, correct_answer, player_results)
    all_correct = all(p['correct'] for p in player_results)
    
    emit('show_explanation', {
        'text': explanation,
        'all_correct': all_correct,
        'concept': q.get('concept', ''),
        'player_results': player_results,
    }, to='host')
    
    # Also send explanation to players
    emit('show_explanation_player', {
        'text': explanation,
        'all_correct': all_correct,
    }, to='game')
    
    # Hold for reading time (shorter if both right)
    socketio.sleep(5 if all_correct else 8)
    show_leaderboard()

def process_free_response(q):
    """Grade free response answers using Claude."""
    free_results = []
    
    for sid, ans_data in game['answers_received'].items():
        player = game['players'].get(sid)
        if not player:
            continue
        
        score, feedback = grade_free_response(
            q['question'], q['correct'], ans_data['answer'], q.get('explanation', '')
        )
        points = round(score * MAX_POINTS / 100)
        player['score'] += points
        
        free_results.append({
            'name': player['name'],
            'answer': ans_data['answer'],
            'score': score,
            'points': points,
            'feedback': feedback,
        })
        
        emit('free_result', {
            'score': score,
            'points': points,
            'total_score': player['score'],
        }, to=sid)
    
    emit('question_result', {
        'type': 'free',
        'correct': q['correct'],
        'free_results': free_results,
    }, to='host')
    
    # Generate explanation for free response too
    socketio.sleep(2)
    player_results = [{'name': r['name'], 'correct': r['score'] >= 60, 'answer': r['answer'], 'points': r['points']} for r in free_results]
    explanation = generate_reveal_explanation(q, q['correct'], player_results)
    
    emit('show_explanation', {
        'text': explanation,
        'all_correct': all(p['correct'] for p in player_results),
        'concept': q.get('concept', ''),
        'player_results': player_results,
    }, to='host')
    
    emit('show_explanation_player', {
        'text': explanation,
        'all_correct': all(p['correct'] for p in player_results),
    }, to='game')
    
    socketio.sleep(8)
    show_leaderboard()

def show_leaderboard():
    rankings = sorted(game['players'].values(), key=lambda p: p['score'], reverse=True)
    emit('show_leaderboard', {
        'rankings': [{'name': p['name'], 'score': p['score'], 'avatar': p.get('avatar', '')} for p in rankings]
    }, to='host')


if __name__ == '__main__':
    # Get local IP for mobile connections
    import socket as sock
    hostname = sock.gethostname()
    local_ip = sock.gethostbyname(hostname)
    
    print(f"\n{'='*50}")
    print(f"  CRAM-IT BATTLE MODE")
    print(f"  Host: http://localhost:4000")
    print(f"  Players: http://{local_ip}:4000/play")
    print(f"{'='*50}\n")
    
    socketio.run(app, host='0.0.0.0', port=4000, debug=False, allow_unsafe_werkzeug=True)
