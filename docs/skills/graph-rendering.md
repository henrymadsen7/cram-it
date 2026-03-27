# Skill: Graph Rendering

## Overview

Cram-It uses JSXGraph to render interactive economics-style graphs (cost curves, supply/demand, monopoly, consumer choice). Graphs can be static presets, dynamic from JSON specs, or interactive exercises.

---

## JSXGraph Integration

### Loading

JSXGraph is loaded from CDN on demand:

```javascript
// graphs.js
function loadJSXGraph() {
  return new Promise((resolve) => {
    if (window.JXG) { resolve(); return; }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/jsxgraph/distrib/jsxgraphcore.js';
    s.onload = resolve;
    document.head.appendChild(s);
  });
}
```

### Key Files

| File | Purpose |
|------|---------|
| `static/graphs.js` | Preset graph renderers + dynamic graph engine |
| `static/graph_exercises.js` | Interactive graph exercises (drag points, identify curves) |
| `templates/index.html` | Graph container divs and UI integration |

### Color Palette

```javascript
const C = {
  mc: '#ef4444',      // red — Marginal Cost
  atc: '#3b82f6',     // blue — Average Total Cost
  avc: '#22c55e',     // green — Average Variable Cost
  afc: '#a855f7',     // purple — Average Fixed Cost
  demand: '#3b82f6',  // blue — Demand curve
  mr: '#f97316',      // orange — Marginal Revenue
  supply: '#22c55e',  // green — Supply curve
  price: '#eab308',   // yellow — Price line
  profit: 'rgba(34,197,94,0.15)',   // green fill
  loss: 'rgba(239,68,68,0.15)',     // red fill
  shutdown: 'rgba(239,68,68,0.08)', // faint red fill
};
```

---

## Preset Graph Types

The AI tutor can trigger these with `[GRAPH: type]` in its response:

### cost_curves

Interactive cost curves with draggable price line:
- MC (U-shaped), ATC (U-shaped), AVC (U-shaped), AFC (declining)
- Price line that the user can drag
- Profit/loss shading updates dynamically
- Shutdown zone highlighted when price < AVC

### supply_demand

Basic supply and demand with equilibrium:
- Downward-sloping demand, upward-sloping supply
- Equilibrium point marked
- Consumer/producer surplus shading

### monopoly

Monopoly pricing diagram:
- Demand curve, MR curve (steeper), MC line
- Profit-maximizing quantity (MR = MC intersection)
- Price from demand curve at optimal Q
- Profit rectangle (P - ATC) * Q
- Deadweight loss triangle

### consumer_choice

Budget constraint and indifference curves:
- Budget line with intercepts
- Multiple indifference curves
- Optimal point at tangency

---

## Dynamic Graph Spec Format

The AI tutor can create custom graphs with specific numbers using `[DYNAMIC_GRAPH: JSON]`.

### JSON Schema

```json
{
  "boundingbox": [xmin, ymax, xmax, ymin],
  "xLabel": "Quantity",
  "yLabel": "Price ($)",
  "elements": [
    // Array of graph elements (see types below)
  ],
  "annotation": "Brief explanation text shown below graph"
}
```

### Element Types

#### Curve

A function graph rendered as a smooth curve:

```json
{
  "type": "curve",
  "fn": "51-4*x",          // JavaScript expression with x
  "color": "#2563eb",
  "label": "D",
  "dash": false            // Optional: dashed line
}
```

Function expression examples:
- Linear: `"51-4*x"`
- Quadratic (U-shape): `"0.8*x*x-6*x+20"`
- Constant: `"15"`
- Hyperbola: `"20/x"`

#### Point

A labeled point on the graph:

```json
{
  "type": "point",
  "x": 4.5,
  "y": 33,
  "label": "P*",
  "color": "#ca8a04"        // Optional
}
```

#### Segment

A line segment between two points:

```json
{
  "type": "segment",
  "x1": 4.5,
  "y1": 0,
  "x2": 4.5,
  "y2": 33,
  "color": "#999",          // Optional
  "dash": true              // Optional
}
```

#### Horizontal Line

```json
{
  "type": "line",
  "y1": 15,                 // y-value for horizontal line
  "color": "#dc2626",
  "label": "MC"
}
```

#### Polygon (Shaded Region)

```json
{
  "type": "polygon",
  "points": [[2, 10], [2, 25], [6, 25], [6, 10]],
  "color": "rgba(34,197,94,0.2)",
  "label": "Profit"
}
```

#### Text

```json
{
  "type": "text",
  "x": 3,
  "y": 40,
  "text": "DWL"
}
```

#### Table

Data table rendered alongside the graph:

```json
{
  "type": "table",
  "rows": [
    ["Q", "P", "TR", "MR", "MC"],
    ["1", "47", "47", "47", "15"],
    ["2", "43", "86", "39", "15"],
    ["3", "39", "117", "31", "15"]
  ]
}
```

### Complete Example: Monopoly Pricing

```json
[DYNAMIC_GRAPH: {
  "boundingbox": [-1, 60, 15, -5],
  "xLabel": "Quantity",
  "yLabel": "Price",
  "elements": [
    {"type": "curve", "fn": "51-4*x", "color": "#2563eb", "label": "D"},
    {"type": "curve", "fn": "51-8*x", "color": "#ea580c", "label": "MR"},
    {"type": "curve", "fn": "15", "color": "#dc2626", "label": "MC"},
    {"type": "point", "x": 4.5, "y": 33, "label": "P*"},
    {"type": "point", "x": 4.5, "y": 15, "label": "MC=MR"},
    {"type": "segment", "x1": 4.5, "y1": 0, "x2": 4.5, "y2": 33, "dash": true},
    {"type": "segment", "x1": 0, "y1": 33, "x2": 4.5, "y2": 33, "dash": true},
    {"type": "polygon", "points": [[0,33],[4.5,33],[4.5,15],[0,15]], "color": "rgba(34,197,94,0.15)", "label": "Profit"}
  ],
  "annotation": "MR=MC at Q=4.5, Price from demand: P=51-4(4.5)=33, Profit=(33-15)*4.5=81"
}]
```

---

## Adding New Graph Types

### Step 1: Define the Renderer

Add a new function to `static/graphs.js`:

```javascript
window.renderNewGraphType = async function(containerId, opts = {}) {
  await loadJSXGraph();

  const el = document.getElementById(containerId);
  if (!el) return;
  el.style.width = '100%';
  el.style.height = '320px';
  el.style.background = '#ffffff';
  el.style.borderRadius = '4px';

  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: [-1, opts.maxY || 50, opts.maxQ || 12, -3],
    axis: false,
    showNavigation: false,
    showCopyright: false,
  });

  // Add your curves, points, etc.
  board.create('functiongraph', [function(x) {
    return yourFunction(x);
  }], {strokeColor: '#3b82f6', strokeWidth: 2.5});

  // Add labels, points, interactive elements...
};
```

### Step 2: Register with the AI Tutor

In `server.py`, update the GRAPH_SPEC_FORMAT section of the system prompt to include your new type:

```python
system += """
- To render an INTERACTIVE graph, add [GRAPH: type] where type is one of:
  cost_curves, monopoly, supply_demand, consumer_choice, YOUR_NEW_TYPE
"""
```

### Step 3: Handle in Frontend

In `templates/index.html`, add detection for the new graph type in the message renderer:

```javascript
if (text.includes('[GRAPH: your_new_type]')) {
  const graphId = 'graph-' + Date.now();
  text = text.replace('[GRAPH: your_new_type]',
    `<div id="${graphId}" class="graph-container"></div>`);
  setTimeout(() => renderNewGraphType(graphId), 100);
}
```

---

## Dynamic Graph Rendering Engine

The dynamic graph renderer (`renderDynamicGraph()` in `graphs.js`) processes the JSON spec:

```javascript
window.renderDynamicGraph = async function(containerId, spec) {
  await loadJSXGraph();

  const board = JXG.JSXGraph.initBoard(containerId, {
    boundingbox: spec.boundingbox || [-1, 50, 12, -3],
    axis: false,
    showNavigation: false,
    showCopyright: false,
  });

  // Draw axes with labels
  drawAxes(board, spec.xLabel, spec.yLabel);

  // Render each element
  for (const el of spec.elements) {
    switch (el.type) {
      case 'curve':
        renderCurve(board, el);
        break;
      case 'point':
        renderPoint(board, el);
        break;
      case 'segment':
        renderSegment(board, el);
        break;
      // ... other types
    }
  }

  // Add annotation
  if (spec.annotation) {
    addAnnotation(containerId, spec.annotation);
  }
};
```

### Curve Function Parsing

Curve functions are JavaScript expressions evaluated with `x` as the variable:

```javascript
function renderCurve(board, el) {
  const fn = new Function('x', `return ${el.fn};`);
  board.create('functiongraph', [fn], {
    strokeColor: el.color || '#3b82f6',
    strokeWidth: 2.5,
  });
  // Add label
  if (el.label) {
    // Position label at right end of visible range
    const labelX = board.getBoundingBox()[2] * 0.85;
    const labelY = fn(labelX);
    board.create('text', [labelX, labelY, el.label], {
      fontSize: 13,
      cssStyle: `color:${el.color};font-weight:600`,
      fixed: true,
    });
  }
}
```

---

## Graph Exercises

Interactive graph exercises in `graph_exercises.js` are a separate system:

- Questions with `gx_` prefix IDs
- User interacts with the graph (drag points, select regions)
- Grading is done client-side
- Results logged via `/api/answer` with `gx_` prefix detection
- Bypass FSRS (no spaced repetition for graph exercises)
