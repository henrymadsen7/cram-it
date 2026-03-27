/**
 * Interactive Graph Exercises v2
 * Click-based graph questions with progress saving.
 */

const GX = {
  colors: {
    mc:'#dc2626', atc:'#2563eb', avc:'#16a34a', afc:'#9333ea',
    demand:'#2563eb', mr:'#ea580c', supply:'#16a34a', price:'#ca8a04',
    correct:'#16a34a', wrong:'#dc2626', highlight:'#f59e0b',
    text:'#1a1a1a', dim:'#888',
  },
  exercises: [],
  current: 0,
  score: 0,
  total: 0,
  results: [], // Track each answer
  containerId: null,
};

GX.exercises = [
  {
    id:'click_mc', title:'Identify the Marginal Cost curve',
    instruction:'Click on the MC curve. It is the steepest U-shaped curve and crosses ATC at its minimum.',
    type:'click_point', correct_region:{x:[7,10],y:[15,35]},
    setup(board){
      board.create('functiongraph',[q=>0.8*q*q-6*q+20],{strokeColor:GX.colors.mc,strokeWidth:3});
      board.create('functiongraph',[q=>{if(q<0.2)return 100;return 0.5*q*q-5*q+25+20/q}],{strokeColor:GX.colors.atc,strokeWidth:3});
      board.create('functiongraph',[q=>0.5*q*q-5*q+20],{strokeColor:GX.colors.avc,strokeWidth:3});
    }
  },
  {
    id:'shutdown_price', title:'Find the shutdown price',
    instruction:'Click on the MINIMUM of AVC. Below this price, the firm shuts down.',
    type:'click_point', correct_region:{x:[4,6],y:[5.5,9.5]},
    setup(board){
      board.create('functiongraph',[q=>0.8*q*q-6*q+20],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10.2,0.8*100-60+20,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>{if(q<0.2)return 100;return 0.5*q*q-5*q+25+20/q}],{strokeColor:GX.colors.atc,strokeWidth:2.5});
      board.create('text',[10.2,75,'ATC'],{fontSize:12,cssStyle:'color:'+GX.colors.atc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>0.5*q*q-5*q+20],{strokeColor:GX.colors.avc,strokeWidth:2.5});
      board.create('text',[10.2,70,'AVC'],{fontSize:12,cssStyle:'color:'+GX.colors.avc+';font-weight:600',fixed:true});
    }
  },
  {
    id:'monopoly_q', title:'Find the monopoly profit-maximizing quantity',
    instruction:'Click where MR = MC. This is where the orange MR curve crosses the red MC curve.',
    type:'click_point', correct_region:{x:[3.5,4.5],y:[8,12]},
    setup(board){
      board.create('functiongraph',[q=>50-5*q],{strokeColor:GX.colors.demand,strokeWidth:2.5});
      board.create('text',[9.5,50-47,'D'],{fontSize:12,cssStyle:'color:'+GX.colors.demand+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>50-10*q],{strokeColor:GX.colors.mr,strokeWidth:2.5});
      board.create('text',[4.5,50-45+2,'MR'],{fontSize:12,cssStyle:'color:'+GX.colors.mr+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>2+2*q],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10,22,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
    }
  },
  {
    id:'monopoly_p', title:'Find the monopoly price',
    instruction:'Q*=4 where MR=MC (marked). Now click on the DEMAND curve at Q=4 to find the price.',
    type:'click_point', correct_region:{x:[3.5,4.5],y:[28,32]},
    setup(board){
      board.create('functiongraph',[q=>50-5*q],{strokeColor:GX.colors.demand,strokeWidth:3});
      board.create('text',[9.5,5,'D'],{fontSize:12,cssStyle:'color:'+GX.colors.demand+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>50-10*q],{strokeColor:GX.colors.mr,strokeWidth:2,dash:2});
      board.create('functiongraph',[q=>2+2*q],{strokeColor:GX.colors.mc,strokeWidth:2,dash:2});
      board.create('point',[4,10],{size:5,fillColor:GX.colors.highlight,strokeColor:GX.colors.highlight,fixed:true,name:'MR=MC'});
      board.create('segment',[[4,0],[4,10]],{strokeColor:'#999',dash:3,strokeWidth:1,fixed:true});
    }
  },
  {
    id:'profit_or_loss', title:'Is this firm profitable at P=$18?',
    instruction:'The yellow dashed line is P=$18. At the profit-max Q (where P=MC), is P above or below ATC? Click on ATC at that Q to check.',
    type:'click_point', correct_region:{x:[5,8],y:[10,17]}, // ATC at the MC=P intersection is ~12-14, below P=18
    setup(board){
      board.create('functiongraph',[q=>0.8*q*q-6*q+20],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10.2,80,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>{if(q<0.2)return 100;return 0.5*q*q-5*q+25+20/q}],{strokeColor:GX.colors.atc,strokeWidth:2.5});
      board.create('text',[10.2,70,'ATC'],{fontSize:12,cssStyle:'color:'+GX.colors.atc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>0.5*q*q-5*q+20],{strokeColor:GX.colors.avc,strokeWidth:2.5});
      board.create('text',[10.2,65,'AVC'],{fontSize:12,cssStyle:'color:'+GX.colors.avc+';font-weight:600',fixed:true});
      board.create('line',[[0,18],[10,18]],{strokeColor:GX.colors.price,strokeWidth:2,dash:3,fixed:true,point1:{visible:false},point2:{visible:false}});
      board.create('text',[0.3,19.5,'P = $18'],{fontSize:11,cssStyle:'color:'+GX.colors.price+';font-weight:600',fixed:true});
    }
  },
  {
    id:'budget_x', title:'Find the X-intercept',
    instruction:'Income=$200, Px=$10, Py=$20. Click where the budget line hits the X-axis. (X-intercept = I/Px = 200/10 = ?)',
    type:'click_point', correct_region:{x:[18,22],y:[-0.8,1.5]},
    setup(board){
      board.create('functiongraph',[x=>10-0.5*x],{strokeColor:GX.colors.price,strokeWidth:2.5});
    }
  },
  {
    id:'ic_preferred', title:'Which indifference curve is preferred?',
    instruction:'Higher (further from origin) = more preferred. Click anywhere on the OUTER curve.',
    type:'click_point', correct_region:{x:[2,11],y:[2.5,13]},
    setup(board){
      board.create('functiongraph',[x=>{if(x<0.5)return 20;return 9/x}],{strokeColor:GX.colors.demand,strokeWidth:2});
      board.create('text',[8,9/8+0.5,'IC1'],{fontSize:11,cssStyle:'color:'+GX.colors.demand,fixed:true});
      board.create('functiongraph',[x=>{if(x<0.5)return 30;return 25/x}],{strokeColor:GX.colors.supply,strokeWidth:2.5});
      board.create('text',[8,25/8+0.5,'IC2'],{fontSize:11,cssStyle:'color:'+GX.colors.supply+';font-weight:600',fixed:true});
    }
  },
  {
    id:'nash_eq', title:'Find the Nash Equilibrium',
    instruction:'Player A picks rows, B picks columns. (first, second) = (A payoff, B payoff). Click the cell where neither wants to switch.',
    type:'click_cell', correct_cell:'BR',
    setup(board){
      const labels=[{x:4,y:9,t:'Player B'},{x:1,y:6,t:'Player A'},{x:4,y:7.5,t:'Cooperate'},{x:7,y:7.5,t:'Defect'},{x:2,y:6,t:'Cooperate'},{x:2,y:4,t:'Defect'}];
      labels.forEach(l=>board.create('text',[l.x,l.y,l.t],{fontSize:11,cssStyle:'color:#333;font-weight:600',fixed:true,anchorX:'middle'}));
      const cells=[{x:4,y:6,t:'(3, 3)',id:'TL'},{x:7,y:6,t:'(1, 4)',id:'TR'},{x:4,y:4,t:'(4, 1)',id:'BL'},{x:7,y:4,t:'(2, 2)',id:'BR'}];
      board._cells={};
      cells.forEach(c=>{
        board.create('polygon',[[c.x-1.2,c.y+0.8],[c.x+1.2,c.y+0.8],[c.x+1.2,c.y-0.8],[c.x-1.2,c.y-0.8]],{fillColor:'#fff',borders:{strokeColor:'#999',strokeWidth:1},fillOpacity:1,fixed:true,vertices:{visible:false},hasInnerPoints:true});
        board.create('text',[c.x,c.y,c.t],{fontSize:14,cssStyle:'color:#333;font-family:IBM Plex Mono,monospace',fixed:true,anchorX:'middle'});
        board._cells[c.id]={poly:null,x:c.x,y:c.y};
      });
      // Store polygon refs properly
      const polys=board.objectsList.filter(o=>o.elType==='polygon');
      ['TL','TR','BL','BR'].forEach((id,i)=>{if(polys[i])board._cells[id].poly=polys[i]});
    }
  },
  {
    id:'lr_eq', title:'Long-run competitive equilibrium',
    instruction:'In the long run, P = minimum ATC (zero profit). Click where MC crosses the minimum of ATC.',
    type:'click_point', correct_region:{x:[5,6.5],y:[11,15]},
    setup(board){
      board.create('functiongraph',[q=>0.8*q*q-6*q+20],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10.2,80,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>{if(q<0.2)return 100;return 0.5*q*q-5*q+25+20/q}],{strokeColor:GX.colors.atc,strokeWidth:2.5});
      board.create('text',[10.2,70,'ATC'],{fontSize:12,cssStyle:'color:'+GX.colors.atc+';font-weight:600',fixed:true});
    }
  },
  {
    id:'mc_p_gt_mc', title:'Monopolistic competition: find the price',
    instruction:'In long-run mon. comp., P=ATC (zero profit) but P > MC. Click where the firm sets its price (on demand curve at the MR=MC quantity).',
    type:'click_point', correct_region:{x:[3,5],y:[18,28]},
    setup(board){
      board.create('functiongraph',[q=>35-3*q],{strokeColor:GX.colors.demand,strokeWidth:2.5});
      board.create('text',[10.2,5,'D'],{fontSize:12,cssStyle:'color:'+GX.colors.demand+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>35-6*q],{strokeColor:GX.colors.mr,strokeWidth:2,dash:2});
      board.create('text',[5,5,'MR'],{fontSize:12,cssStyle:'color:'+GX.colors.mr,fixed:true});
      board.create('functiongraph',[q=>0.8*q*q-6*q+20],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10.2,80,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>{if(q<0.2)return 100;return 0.5*q*q-4*q+22+10/q}],{strokeColor:GX.colors.atc,strokeWidth:2.5});
      board.create('text',[10.2,70,'ATC'],{fontSize:12,cssStyle:'color:'+GX.colors.atc+';font-weight:600',fixed:true});
    }
  },
  {
    id:'dwl', title:'Identify deadweight loss',
    instruction:'The monopolist produces Q*=4 (where MR=MC). Competitive output is where MC=D. Click in the triangle between Q=4 and the competitive Q.',
    type:'click_point', correct_region:{x:[4.5,7],y:[12,28]},
    setup(board){
      board.create('functiongraph',[q=>50-5*q],{strokeColor:GX.colors.demand,strokeWidth:2.5});
      board.create('text',[9.5,5,'D'],{fontSize:12,cssStyle:'color:'+GX.colors.demand+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>50-10*q],{strokeColor:GX.colors.mr,strokeWidth:2,dash:2});
      board.create('text',[4.5,7,'MR'],{fontSize:12,cssStyle:'color:'+GX.colors.mr,fixed:true});
      board.create('functiongraph',[q=>2+2*q],{strokeColor:GX.colors.mc,strokeWidth:2.5});
      board.create('text',[10,22,'MC'],{fontSize:12,cssStyle:'color:'+GX.colors.mc+';font-weight:600',fixed:true});
      board.create('polygon',[[4,10],[4,30],[6.85,16.3]],{fillColor:'#fecaca',fillOpacity:0.2,fixed:true,vertices:{visible:false},borders:{strokeColor:'#dc2626',strokeWidth:1,dash:3}});
      board.create('segment',[[4,0],[4,30]],{strokeColor:'#999',dash:3,strokeWidth:1,fixed:true});
      board.create('text',[4,-1.5,'Qm'],{fontSize:10,cssStyle:'color:#333',fixed:true,anchorX:'middle'});
    }
  },
  {
    id:'sd_eq', title:'Find market equilibrium',
    instruction:'Click where supply (green) meets demand (blue).',
    type:'click_point', correct_region:{x:[4.5,5.5],y:[23,27]},
    setup(board){
      board.create('functiongraph',[q=>5+4*q],{strokeColor:GX.colors.supply,strokeWidth:2.5});
      board.create('text',[10,45,'S'],{fontSize:12,cssStyle:'color:'+GX.colors.supply+';font-weight:600',fixed:true});
      board.create('functiongraph',[q=>45-4*q],{strokeColor:GX.colors.demand,strokeWidth:2.5});
      board.create('text',[10,5,'D'],{fontSize:12,cssStyle:'color:'+GX.colors.demand+';font-weight:600',fixed:true});
    }
  },
];

// === SAVE PROGRESS ===
async function saveGraphResult(exerciseId, correct) {
  try {
    const uid = window.U; // Global user ID from main app
    if (!uid) return;
    await fetch('/api/answer', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        user_id: uid,
        question_id: 'gx_' + exerciseId,
        user_answer: correct ? 'correct' : 'wrong',
        seconds: 0
      })
    });
  } catch(e) {}
}

// === RUNNER ===
window.startGraphExercises = async function(containerId) {
  await loadJSXGraph();
  GX.containerId = containerId;
  GX.current = 0;
  GX.score = 0;
  GX.total = GX.exercises.length;
  GX.results = [];
  showExercise();
};

window.resumeGraphExercises = async function(containerId, fromIndex) {
  await loadJSXGraph();
  GX.containerId = containerId;
  GX.current = fromIndex || 0;
  GX.score = 0;
  GX.total = GX.exercises.length;
  GX.results = [];
  showExercise();
};

function showExercise() {
  const container = document.getElementById(GX.containerId);
  if (GX.current >= GX.exercises.length) {
    // Summary
    let rows = GX.results.map((r,i) => 
      `<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:.8rem">
        <span>${i+1}. ${GX.exercises[i].title}</span>
        <span style="color:${r?'#16a34a':'#dc2626'};font-weight:600">${r?'correct':'wrong'}</span>
      </div>`
    ).join('');
    container.innerHTML = `<div style="text-align:center;padding:20px;background:#fafafa;border-radius:4px;border:1px solid #e5e5e5">
      <div style="font-size:1.1rem;font-weight:700;color:#1a1a1a">Graph Exercises Complete</div>
      <div style="font-size:2rem;font-weight:700;color:${GX.score/GX.total>=0.8?'#16a34a':'#ca8a04'};margin:8px 0;font-family:'IBM Plex Mono',monospace">${GX.score}/${GX.total}</div>
      <div style="text-align:left;max-width:400px;margin:12px auto">${rows}</div>
      <div style="display:flex;gap:8px;justify-content:center;margin-top:12px">
        <button onclick="startGraphExercises('${GX.containerId}')" style="background:#2563eb;color:#fff;border:none;padding:8px 20px;border-radius:4px;cursor:pointer;font-family:inherit">restart all</button>
        <button onclick="showDrillStart()" style="background:#e5e5e5;color:#333;border:none;padding:8px 20px;border-radius:4px;cursor:pointer;font-family:inherit">back to drill</button>
      </div>
    </div>`;
    return;
  }
  
  const ex = GX.exercises[GX.current];
  const boardId = 'gx-board-' + Date.now();
  
  container.innerHTML = `
    <div style="background:#fafafa;border-radius:4px;border:1px solid #e5e5e5;padding:12px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="font-size:.75rem;color:#888;font-family:'IBM Plex Mono',monospace">${GX.current+1}/${GX.total} -- ${GX.score} correct</span>
        <button onclick="GX.current++;showExercise()" style="background:none;border:1px solid #ddd;color:#888;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:.7rem">skip</button>
      </div>
      <div style="font-size:.9rem;font-weight:600;color:#1a1a1a;margin-bottom:4px">${ex.title}</div>
      <div style="font-size:.82rem;color:#555;margin-bottom:8px">${ex.instruction}</div>
      <div id="${boardId}" style="width:100%;height:300px;background:#fff;border:1px solid #e5e5e5;border-radius:4px"></div>
      <div id="gx-feedback" style="margin-top:6px;font-size:.85rem;font-weight:600"></div>
    </div>`;
  
  const bb = ex.type === 'click_cell' ? [0, 10, 10, 2] : [-1, 50, 12, -5];
  const board = JXG.JSXGraph.initBoard(boardId, {
    boundingbox: bb, axis:false, showNavigation:false, showCopyright:false,
    pan:{enabled:false}, zoom:{enabled:false},
  });
  
  if (ex.type !== 'click_cell') {
    board.create('arrow', [[0,0],[bb[2]-0.5,0]], {strokeColor:'#444',strokeWidth:1.5,fixed:true});
    board.create('arrow', [[0,0],[0,bb[1]-2]], {strokeColor:'#444',strokeWidth:1.5,fixed:true});
  }
  
  ex.setup(board);
  
  let answered = false;
  board.on('down', function(e) {
    if (answered) return;
    answered = true;
    
    const coords = board.getUsrCoordsOfMouse(e);
    const x = coords[0], y = coords[1];
    let correct = false;
    
    if (ex.type === 'click_point' || ex.type === 'click_region') {
      const r = ex.correct_region;
      correct = x >= r.x[0] && x <= r.x[1] && y >= r.y[0] && y <= r.y[1];
      board.create('point', [x, y], {size:6, fillColor:correct?'#16a34a':'#dc2626', strokeColor:correct?'#16a34a':'#dc2626', fixed:true, name:correct?'':'X', label:{fontSize:12}});
      if (!correct) {
        board.create('point', [(r.x[0]+r.x[1])/2, (r.y[0]+r.y[1])/2], {size:8, fillColor:'#16a34a', strokeColor:'#16a34a', fixed:true, name:'here', label:{fontSize:11,cssStyle:'color:#16a34a'}});
      }
    } else if (ex.type === 'click_cell') {
      for (const [id, cell] of Object.entries(board._cells || {})) {
        if (Math.abs(x - cell.x) < 1.2 && Math.abs(y - cell.y) < 0.8) {
          correct = id === ex.correct_cell;
          if (cell.poly) cell.poly.setAttribute({fillColor: correct ? '#bbf7d0' : '#fecaca'});
          if (!correct && board._cells[ex.correct_cell]?.poly) {
            board._cells[ex.correct_cell].poly.setAttribute({fillColor: '#bbf7d0'});
          }
          break;
        }
      }
    }
    
    if (correct) GX.score++;
    GX.results.push(correct);
    saveGraphResult(ex.id, correct);
    
    const fb = document.getElementById('gx-feedback');
    fb.style.color = correct ? '#16a34a' : '#dc2626';
    fb.textContent = correct ? 'Correct.' : 'Wrong -- correct region highlighted in green.';
    
    setTimeout(() => { GX.current++; showExercise(); }, correct ? 1200 : 2500);
  });
}
