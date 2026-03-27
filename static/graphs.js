/**
 * Dynamic Economics Graph Renderer
 * Uses JSXGraph to render interactive economics graphs.
 * Each graph type is a function that takes a container ID and optional params.
 */

// Load JSXGraph CSS
if (!document.getElementById('jsxgraph-css')) {
  const link = document.createElement('link');
  link.id = 'jsxgraph-css';
  link.rel = 'stylesheet';
  link.href = 'https://cdn.jsdelivr.net/npm/jsxgraph/distrib/jsxgraph.css';
  document.head.appendChild(link);
}

// Load JSXGraph JS
function loadJSXGraph() {
  return new Promise((resolve) => {
    if (window.JXG) { resolve(); return; }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/jsxgraph/distrib/jsxgraphcore.js';
    s.onload = resolve;
    document.head.appendChild(s);
  });
}

// === COLOR PALETTE ===
const C = {
  mc: '#ef4444',      // red
  atc: '#3b82f6',     // blue
  avc: '#22c55e',     // green
  afc: '#a855f7',     // purple
  demand: '#3b82f6',  // blue
  mr: '#f97316',      // orange
  supply: '#22c55e',  // green
  price: '#eab308',   // yellow
  profit: 'rgba(34,197,94,0.15)',
  loss: 'rgba(239,68,68,0.15)',
  shutdown: 'rgba(239,68,68,0.08)',
  grid: '#333',
  text: '#e2e0dc',
  dim: '#666',
};

// === COST CURVES ===
window.renderCostCurves = async function(containerId, opts = {}) {
  await loadJSXGraph();
  
  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = '320px';
  el.style.background = '#ffffff';
  el.style.borderRadius = '4px';
  el.style.border = '1px solid #d4d4d4';
  
  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: [-1, opts.maxY || 50, opts.maxQ || 12, -3],
    axis: false,
    showNavigation: false,
    showCopyright: false,
    pan: { enabled: false },
    zoom: { enabled: false },
  });
  
  // Custom axes
  board.create('arrow', [[0,0], [opts.maxQ || 11, 0]], {strokeColor: C.dim, strokeWidth: 1, fixed: true});
  board.create('arrow', [[0,0], [0, opts.maxY || 48]], {strokeColor: C.dim, strokeWidth: 1, fixed: true});
  board.create('text', [(opts.maxQ || 11)/2, -2, 'Quantity'], {fontSize: 12, cssStyle: 'color:' + C.dim, fixed: true});
  board.create('text', [-0.8, (opts.maxY || 48)/2, 'Cost ($)'], {fontSize: 12, cssStyle: 'color:' + C.dim, fixed: true, rotate: 90});
  
  // MC: U-shaped, minimum around Q=4
  const mc = board.create('functiongraph', [function(q) {
    if (q <= 0) return 50;
    return 0.8*q*q - 6*q + 20;  // min at q=3.75, value ~8.75
  }], {strokeColor: C.mc, strokeWidth: 2.5, name: 'MC'});
  board.create('text', [10, 0.8*100 - 60 + 20, 'MC'], {fontSize: 13, cssStyle: 'color:'+C.mc+';font-weight:600', fixed: true});
  
  // ATC: U-shaped, minimum around Q=5.5
  const atc = board.create('functiongraph', [function(q) {
    if (q <= 0.1) return 200;
    return 0.5*q*q - 5*q + 25 + 20/q;  // min around q=5.5
  }], {strokeColor: C.atc, strokeWidth: 2.5, name: 'ATC'});
  board.create('text', [10, 0.5*100 - 50 + 25 + 2, 'ATC'], {fontSize: 13, cssStyle: 'color:'+C.atc+';font-weight:600', fixed: true});
  
  // AVC: U-shaped, minimum around Q=5
  const avc = board.create('functiongraph', [function(q) {
    if (q <= 0) return 50;
    return 0.5*q*q - 5*q + 20;  // min at q=5, value ~7.5
  }], {strokeColor: C.avc, strokeWidth: 2.5, name: 'AVC'});
  board.create('text', [10, 0.5*100 - 50 + 20, 'AVC'], {fontSize: 13, cssStyle: 'color:'+C.avc+';font-weight:600', fixed: true});
  
  // AFC: always declining
  const afc = board.create('functiongraph', [function(q) {
    if (q <= 0.1) return 200;
    return 20/q;
  }], {strokeColor: C.afc, strokeWidth: 1.5, dash: 2, name: 'AFC'});
  board.create('text', [9, 20/9 + 1, 'AFC'], {fontSize: 11, cssStyle: 'color:'+C.afc, fixed: true});
  
  // Interactive price line (draggable)
  if (opts.interactive !== false) {
    const priceLine = board.create('line', [[0, opts.price || 15], [10, opts.price || 15]], {
      strokeColor: C.price, strokeWidth: 2, dash: 3, fixed: false,
      point1: {visible: false}, point2: {visible: false}
    });
    
    // Draggable price point
    const pricePoint = board.create('glider', [0, opts.price || 15, board.create('line', [[0,0],[0,50]], {visible: false})], {
      name: 'P', size: 4, fillColor: C.price, strokeColor: C.price,
      label: {fontSize: 12, cssStyle: 'color:'+C.price}
    });
    
    // Dynamic price line follows the glider
    board.create('line', [function() { return [0, pricePoint.Y()]; }, function() { return [12, pricePoint.Y()]; }], {
      strokeColor: C.price, strokeWidth: 1.5, dash: 3, fixed: true,
      point1: {visible: false}, point2: {visible: false}
    });
    
    // Annotations
    board.create('text', [0.5, -1.5, function() {
      const p = pricePoint.Y();
      // Find AVC at profit-max Q
      // MC = 0.8q^2 - 6q + 20, P = MC -> solve for q
      // Approximate: q where MC(q) ≈ P
      let q_star = 0;
      for (let q = 0.5; q < 10; q += 0.1) {
        if (0.8*q*q - 6*q + 20 <= p) q_star = q;
      }
      const avc_val = 0.5*q_star*q_star - 5*q_star + 20;
      const atc_val = 0.5*q_star*q_star - 5*q_star + 25 + 20/q_star;
      
      if (p < avc_val) return 'SHUTDOWN: P < AVC';
      if (p < atc_val) return 'LOSS but operate: AVC < P < ATC';
      return 'PROFIT: P > ATC';
    }], {fontSize: 11, cssStyle: 'font-weight:600;font-family:IBM Plex Mono,monospace', fixed: true,
      cssClass: function() {
        const p = pricePoint.Y();
        return p < 8 ? 'color:'+C.mc : p < 13 ? 'color:'+C.price : 'color:'+C.avc;
      }
    });
  }
  
  return board;
};

// === MONOPOLY ===
window.renderMonopoly = async function(containerId, opts = {}) {
  await loadJSXGraph();
  
  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = '320px';
  el.style.background = '#ffffff';
  el.style.borderRadius = '4px';
  el.style.border = '1px solid #d4d4d4';
  
  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: [-1, 55, 12, -5],
    axis: false, showNavigation: false, showCopyright: false,
    pan: {enabled:false}, zoom: {enabled:false},
  });
  
  board.create('arrow', [[0,0],[11,0]], {strokeColor:'#444', strokeWidth:1, fixed:true});
  board.create('arrow', [[0,0],[0,53]], {strokeColor:'#444', strokeWidth:1, fixed:true});
  board.create('text', [5.5, -2.5, 'Quantity'], {fontSize:12, cssStyle:'color:#444', fixed:true});
  board.create('text', [-0.8, 27, 'Price ($)'], {fontSize:12, cssStyle:'color:#444', fixed:true});
  
  // Demand: P = 50 - 5Q
  board.create('functiongraph', [function(q){return 50-5*q}], {strokeColor:C.demand, strokeWidth:2.5});
  board.create('text', [9.5, 50-5*9.5+2, 'D'], {fontSize:13, cssStyle:'color:'+C.demand+';font-weight:600', fixed:true});
  
  // MR: P = 50 - 10Q (twice the slope)
  board.create('functiongraph', [function(q){return 50-10*q}], {strokeColor:C.mr, strokeWidth:2.5});
  board.create('text', [4.5, 50-10*4.5+2, 'MR'], {fontSize:13, cssStyle:'color:'+C.mr+';font-weight:600', fixed:true});
  
  // MC: rising
  board.create('functiongraph', [function(q){return 2+2*q}], {strokeColor:C.mc, strokeWidth:2.5});
  board.create('text', [10, 2+2*10+1, 'MC'], {fontSize:13, cssStyle:'color:'+C.mc+';font-weight:600', fixed:true});
  
  // ATC
  board.create('functiongraph', [function(q){if(q<0.2)return 100;return q+10/q+5}], {strokeColor:C.atc, strokeWidth:1.5, dash:2});
  board.create('text', [10, 10+10/10+5+1, 'ATC'], {fontSize:11, cssStyle:'color:'+C.atc, fixed:true});
  
  // Profit-max point: MR = MC -> 50-10Q = 2+2Q -> Q* = 4, P* = 50-20 = 30
  board.create('point', [4, 30], {name:'', size:4, fillColor:C.price, strokeColor:C.price, fixed:true});
  board.create('point', [4, 10], {name:'', size:3, fillColor:C.mr, strokeColor:C.mr, fixed:true}); // MR=MC point
  
  // Dashed lines to axes
  board.create('segment', [[4,0],[4,30]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  board.create('segment', [[0,30],[4,30]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  
  // Labels
  board.create('text', [4, -1.5, 'Q*=4'], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'middle'});
  board.create('text', [-0.5, 30, 'P*=30'], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'right'});
  
  // Profit rectangle
  const atc_at_4 = 4 + 10/4 + 5; // ~11.5
  board.create('polygon', [[0,30],[4,30],[4,atc_at_4],[0,atc_at_4]], {
    fillColor: C.profit, borders: {strokeWidth:0}, fillOpacity: 0.3, fixed: true, vertices: {visible:false}
  });
  board.create('text', [2, (30+atc_at_4)/2, 'Profit'], {fontSize:11, cssStyle:'color:'+C.avc+';font-weight:600', fixed:true, anchorX:'middle'});
  
  // Annotation
  board.create('text', [0.5, -3.5, 'Step 1: Q where MR=MC=4. Step 2: P from demand=30. Profit=(30-11.5)*4=$74'], 
    {fontSize:10, cssStyle:'color:'+C.dim+';font-family:IBM Plex Mono,monospace', fixed:true});
  
  return board;
};

// === SUPPLY AND DEMAND ===
window.renderSupplyDemand = async function(containerId, opts = {}) {
  await loadJSXGraph();
  
  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = '320px';
  el.style.background = '#ffffff';
  el.style.borderRadius = '4px';
  el.style.border = '1px solid #d4d4d4';
  
  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: [-1, 55, 12, -5],
    axis: false, showNavigation: false, showCopyright: false,
    pan: {enabled:false}, zoom: {enabled:false},
  });
  
  board.create('arrow', [[0,0],[11,0]], {strokeColor:C.dim, strokeWidth:1, fixed:true});
  board.create('arrow', [[0,0],[0,53]], {strokeColor:C.dim, strokeWidth:1, fixed:true});
  board.create('text', [5.5, -2.5, 'Quantity'], {fontSize:12, cssStyle:'color:'+C.dim, fixed:true});
  board.create('text', [-0.8, 27, 'Price ($)'], {fontSize:12, cssStyle:'color:'+C.dim, fixed:true});
  
  // Supply: P = 5 + 4Q
  board.create('functiongraph', [function(q){return 5+4*q}], {strokeColor:C.supply, strokeWidth:2.5});
  board.create('text', [10, 5+4*10+1, 'S'], {fontSize:13, cssStyle:'color:'+C.supply+';font-weight:600', fixed:true});
  
  // Demand: P = 45 - 4Q
  board.create('functiongraph', [function(q){return 45-4*q}], {strokeColor:C.demand, strokeWidth:2.5});
  board.create('text', [10, 45-4*10+1, 'D'], {fontSize:13, cssStyle:'color:'+C.demand+';font-weight:600', fixed:true});
  
  // Equilibrium: 5+4Q = 45-4Q -> 8Q = 40 -> Q=5, P=25
  board.create('point', [5, 25], {name:'E', size:5, fillColor:C.price, strokeColor:C.price, fixed:true,
    label:{fontSize:12, cssStyle:'color:'+C.price+';font-weight:600'}});
  board.create('segment', [[5,0],[5,25]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  board.create('segment', [[0,25],[5,25]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  board.create('text', [5, -1.5, 'Q*=5'], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'middle'});
  board.create('text', [-0.5, 25, 'P*=25'], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'right'});
  
  return board;
};

// === BUDGET CONSTRAINT + INDIFFERENCE CURVES ===
window.renderConsumerChoice = async function(containerId, opts = {}) {
  await loadJSXGraph();
  
  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = '320px';
  el.style.background = '#ffffff';
  el.style.borderRadius = '4px';
  el.style.border = '1px solid #d4d4d4';
  
  const I = opts.income || 100;
  const Px = opts.px || 10;
  const Py = opts.py || 20;
  const maxX = I/Px + 2;
  const maxY = I/Py + 2;
  
  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: [-1, maxY+1, maxX+1, -2],
    axis: false, showNavigation: false, showCopyright: false,
    pan: {enabled:false}, zoom: {enabled:false},
  });
  
  board.create('arrow', [[0,0],[maxX,0]], {strokeColor:C.dim, strokeWidth:1, fixed:true});
  board.create('arrow', [[0,0],[0,maxY]], {strokeColor:C.dim, strokeWidth:1, fixed:true});
  board.create('text', [maxX/2, -1.2, 'Good X'], {fontSize:12, cssStyle:'color:'+C.dim, fixed:true});
  board.create('text', [-0.8, maxY/2, 'Good Y'], {fontSize:12, cssStyle:'color:'+C.dim, fixed:true});
  
  // Budget constraint: Y = I/Py - (Px/Py)*X
  board.create('functiongraph', [function(x){return I/Py - (Px/Py)*x}], {strokeColor:C.price, strokeWidth:2.5});
  board.create('text', [I/Px, -0.8, `${I/Px}`], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'middle'});
  board.create('text', [-0.5, I/Py, `${I/Py}`], {fontSize:10, cssStyle:'color:'+C.price+';font-family:IBM Plex Mono,monospace', fixed:true, anchorX:'right'});
  
  // Indifference curves (Cobb-Douglas: U = X^0.5 * Y^0.5)
  const optX = I/(2*Px);
  const optY = I/(2*Py);
  const U_opt = Math.sqrt(optX * optY);
  
  // Optimal IC
  board.create('functiongraph', [function(x){if(x<0.3)return maxY;return (U_opt*U_opt)/x}], {strokeColor:C.avc, strokeWidth:2, dash:0});
  
  // Lower IC
  board.create('functiongraph', [function(x){if(x<0.3)return maxY;return (U_opt*0.7)*(U_opt*0.7)/x}], {strokeColor:C.dim, strokeWidth:1, dash:2});
  
  // Optimal point
  board.create('point', [optX, optY], {name:'Optimal', size:5, fillColor:C.avc, strokeColor:C.avc, fixed:true,
    label:{fontSize:11, cssStyle:'color:'+C.avc+';font-weight:600', offset:[10,5]}});
  
  board.create('segment', [[optX,0],[optX,optY]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  board.create('segment', [[0,optY],[optX,optY]], {strokeColor:C.dim, strokeWidth:1, dash:3, fixed:true});
  
  board.create('text', [0.5, -1.5, `Budget: ${I} = ${Px}X + ${Py}Y. Optimal: X=${optX}, Y=${optY}. MRS = Px/Py = ${Px}/${Py}`], 
    {fontSize:10, cssStyle:'color:'+C.dim+';font-family:IBM Plex Mono,monospace', fixed:true});
  
  return board;
};

// === DYNAMIC GRAPH FROM JSON SPEC ===
window.renderDynamic = async function(containerId, spec) {
  await loadJSXGraph();
  
  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = spec.height || '320px';
  el.style.background = spec.bg || '#ffffff';
  el.style.borderRadius = '4px';
  el.style.border = '1px solid #d4d4d4';
  
  const bb = spec.boundingbox || [-1, 55, 12, -5];
  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: bb, axis: false, showNavigation: false, showCopyright: false,
    pan: {enabled:false}, zoom: {enabled:false},
  });
  
  // Axes
  if (spec.axes !== false) {
    board.create('arrow', [[0,0],[bb[2]-0.5,0]], {strokeColor:'#333', strokeWidth:1.5, fixed:true});
    board.create('arrow', [[0,0],[0,bb[1]-2]], {strokeColor:'#333', strokeWidth:1.5, fixed:true});
    if (spec.xLabel) board.create('text', [(bb[2]-1)/2, bb[3]+1.5, spec.xLabel], {fontSize:12, cssStyle:'color:#333;font-weight:500', fixed:true});
    if (spec.yLabel) board.create('text', [-0.8, (bb[1]-2)/2, spec.yLabel], {fontSize:12, cssStyle:'color:#333;font-weight:500', fixed:true});
  }
  
  // Render each element
  for (const item of (spec.elements || [])) {
    switch(item.type) {
      case 'curve': {
        // Parse function string: "50-5*x" becomes a JS function
        const fn = new Function('x', 'return ' + item.fn);
        const color = item.color || C[item.name?.toLowerCase()] || C.demand;
        board.create('functiongraph', [fn], {
          strokeColor: color, strokeWidth: item.width || 2.5,
          dash: item.dash || 0
        });
        if (item.label) {
          const lx = item.labelX || bb[2]-1.5;
          const ly = item.labelY || fn(lx);
          board.create('text', [lx, ly, item.label], {
            fontSize: 12, cssStyle: 'color:'+color+';font-weight:600', fixed: true
          });
        }
        break;
      }
      case 'point': {
        board.create('point', [item.x, item.y], {
          size: item.size || 4,
          fillColor: item.color || C.price,
          strokeColor: item.color || C.price,
          fixed: true,
          name: item.label || '',
          label: {fontSize: 11, cssStyle: 'color:'+(item.color||C.price)+';font-weight:600', offset: item.labelOffset || [8,8]}
        });
        break;
      }
      case 'line': {
        const lx1=item.x1||0, lx2=item.x2||(bb[2]-0.5);
        const ly1=item.y1, ly2=item.y2||item.y1;
        board.create('line', [[lx1,ly1],[lx2,ly2]], {
          strokeColor: item.color || C.price, strokeWidth: item.width || 2,
          dash: item.dash===undefined?3:item.dash, fixed: true,
          point1: {visible:false}, point2: {visible:false}
        });
        if(item.label){
          board.create('text', [lx2-1, ly1+1.2, item.label], {
            fontSize: 11, cssStyle: 'color:'+(item.color||C.price)+';font-weight:600', fixed: true
          });
        }
        break;
      }
      case 'segment': {
        board.create('segment', [[item.x1,item.y1],[item.x2,item.y2]], {
          strokeColor: item.color || C.dim, strokeWidth: item.width || 1.5,
          dash: item.dash===undefined?3:item.dash, fixed: true
        });
        if(item.label){
          board.create('text', [(item.x1+item.x2)/2, (item.y1+item.y2)/2-1, item.label], {
            fontSize: 10, cssStyle: 'color:'+(item.color||C.dim)+';font-weight:500', fixed: true, anchorX:'middle'
          });
        }
        break;
      }
      case 'polygon': {
        const pts = item.points.map(p => [p[0], p[1]]);
        board.create('polygon', pts, {
          fillColor: item.color || C.profit, fillOpacity: item.opacity || 0.3,
          fixed: true, vertices: {visible: false},
          borders: {strokeWidth: item.borderWidth || 0}
        });
        break;
      }
      case 'text': {
        board.create('text', [item.x, item.y, item.text], {
          fontSize: item.size || 11,
          cssStyle: 'color:'+(item.color||'#333')+';'+(item.style||''),
          fixed: true, anchorX: item.anchor || 'left'
        });
        break;
      }
      case 'table': {
        // Render an HTML table overlay
        const tbl = document.createElement('div');
        tbl.style.cssText = 'margin-top:8px;font-size:.8rem;font-family:IBM Plex Mono,monospace;overflow-x:auto';
        let html = '<table style="border-collapse:collapse;width:100%">';
        for (let i = 0; i < item.rows.length; i++) {
          html += '<tr>';
          for (const cell of item.rows[i]) {
            const tag = i === 0 ? 'th' : 'td';
            const style = i === 0 
              ? 'background:#f1f5f9;color:#2563eb;padding:5px 10px;border:1px solid #cbd5e1;font-weight:600' 
              : 'background:#ffffff;color:#1a1a1a;padding:5px 10px;border:1px solid #e2e8f0';
            html += `<${tag} style="${style}">${cell}</${tag}>`;
          }
          html += '</tr>';
        }
        html += '</table>';
        tbl.innerHTML = html;
        el.parentNode.insertBefore(tbl, el.nextSibling);
        break;
      }
    }
  }
  
  // Annotation text — render as HTML below graph for readability
  if (spec.annotation) {
    const ann=document.createElement('div');
    ann.style.cssText='font-size:0.78rem;color:#888;font-family:"IBM Plex Mono",monospace;padding:6px 8px;line-height:1.5;border-left:2px solid #818cf8;margin-top:4px;background:rgba(24,24,31,0.5);border-radius:0 4px 4px 0';
    ann.textContent=spec.annotation;
    el.parentNode.insertBefore(ann,el.nextSibling);
  }
  
  return board;
};

// === RENDER BY TYPE (called from chat/quiz) ===
window.renderGraph = async function(containerId, type, opts) {
  // Check if opts is a full dynamic spec
  if (opts && opts.elements) {
    return renderDynamic(containerId, opts);
  }
  switch(type) {
    case 'cost_curves': return renderCostCurves(containerId, opts);
    case 'monopoly': return renderMonopoly(containerId, opts);
    case 'supply_demand': return renderSupplyDemand(containerId, opts);
    case 'consumer_choice': return renderConsumerChoice(containerId, opts);
    default: console.log('Unknown graph type:', type);
  }
};
