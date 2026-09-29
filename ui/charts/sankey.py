"""Sankey interaktif — chip per-node, highlight flow, gradient links."""
from __future__ import annotations

import streamlit.components.v1 as components

def render_sankey_interactive(fig, height=520):
    """
    Sankey interaktif lengkap (defensive):
    - Chip per-node (YP-B / YP-S)
    - Event delegation — chip selalu clickable
    - Highlight arah flow
    - Gradient link (best-effort) + fallback solid
    - Toggle Volume / Value
    """
    if fig is None:
        return

    try:
        labels = list(fig.data[0].node.label or [])
    except Exception:
        labels = []

    try:
        n_buyers = int(fig.layout.meta.get('n_buyers', 0)) if fig.layout.meta else 0
    except Exception:
        n_buyers = 0

    import re as _re

    def _clean_label(s):
        s = _re.sub(r'\s*\([^)]*\)', '', str(s)).strip()
        s = _re.sub(r'^[\d\.,]+\s*[MBK]?\s*', '', s).strip()
        s = _re.sub(r'\s*[\d\.,]+\s*[MBK]?$', '', s).strip()
        return s

    broker_counts = {}
    for lb in labels:
        c = _clean_label(lb)
        if c:
            broker_counts[c] = broker_counts.get(c, 0) + 1

    chips_html = ""
    for i, lb in enumerate(labels):
        c = _clean_label(lb)
        if not c:
            continue
        side = "B" if i < n_buyers else "S"
        suffix = f"-{side}" if broker_counts.get(c, 0) > 1 else ""
        chips_html += (
            f'<button class="chip" data-node-idx="{i}" data-broker="{c}" '
            f'data-side="{side}">{c}{suffix}</button>'
        )

    fig_json = fig.to_json()
    n_buyers_js = n_buyers

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            html, body {{ margin:0; padding:0; background:#0f1116;
                font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                overflow:hidden; }}
            #chart {{ width:100%; height:{height}px; }}
            #mode-toggle {{ display:flex; gap:6px; justify-content:center;
                padding:6px 0 2px 0; background:#0f1116; }}
            .mode-btn {{ background:#1e293b; color:#94a3b8;
                border:1px solid #334155; border-radius:16px;
                padding:6px 16px; font-size:12px; font-weight:600;
                cursor:pointer; user-select:none;
                -webkit-tap-highlight-color:transparent; transition:all 0.15s; }}
            .mode-btn:active {{ background:#334155; }}
            .mode-btn.active {{ background:rgba(168,85,247,0.20) !important;
                color:#a855f7 !important; border-color:#a855f7 !important; }}
            #hint {{ text-align:center; color:#64748b; font-size:10px;
                padding:2px 0 4px 0; background:#0f1116; }}
            #panel {{ padding:4px 8px 10px 8px; background:#0f1116;
                display:flex; flex-wrap:wrap; justify-content:center; gap:4px; }}
            .chip {{ background:#1e293b; color:#cbd5e1;
                border:1px solid #334155; border-radius:14px;
                padding:5px 12px; font-size:11px; cursor:pointer;
                margin:2px; user-select:none;
                -webkit-tap-highlight-color:transparent; transition:all 0.15s; }}
            .chip:active {{ background:#334155; }}
            .chip.active {{ background:#a855f7 !important; color:#fff !important;
                border-color:#a855f7 !important; }}
            #reset {{ background:rgba(168,85,247,0.15); color:#a855f7;
                border:1px solid #a855f7; border-radius:14px;
                padding:5px 14px; font-size:11px; cursor:pointer;
                font-weight:bold; margin:2px 2px 2px 6px;
                -webkit-tap-highlight-color:transparent; }}
            #reset:active {{ background:rgba(168,85,247,0.30); }}
        </style>
    </head>
    <body>
        <div id="mode-toggle">
            <button class="mode-btn active" data-mode="volume">📊 Volume (Lot)</button>
            <button class="mode-btn" data-mode="value">💰 Value (Rp)</button>
        </div>
        <div id="hint">👆 Tap broker di bawah untuk highlight</div>
        <div id="panel">
            {chips_html}
            <button id="reset">↻ Reset</button>
        </div>
        <div id="chart"></div>
        <script>
            (function() {{
                var figData = {fig_json};
                var config = {{ displayModeBar:false, responsive:true,
                    scrollZoom:false, displaylogo:false }};
                var gd = document.getElementById('chart');
                var SVG_NS = 'http://www.w3.org/2000/svg';

                // ▼ Guard semua akses meta
                var META = (figData.layout && figData.layout.meta) || {{}};
                var MODE_PAYLOAD = META.mode_toggle || null;
                var N_BUYERS = META.n_buyers || {n_buyers_js};

                var ORIG = JSON.parse(JSON.stringify(figData.data[0]));
                var LAYOUT = JSON.parse(JSON.stringify(figData.layout));
                // Hapus meta dari layout biar gak ganggu render
                delete LAYOUT.meta;

                var labels = [].concat(ORIG.node.label || []);
                var sources = [].concat(ORIG.link.source || []);
                var targets = [].concat(ORIG.link.target || []);
                var origNodeColors = [].concat(ORIG.node.color || []);
                var origNodeLabels = [].concat(ORIG.node.label || []);
                var origLinkValues = [].concat(ORIG.link.value || []);
                var origLinkColors = [].concat(ORIG.link.color || []);

                if (origNodeColors.length < labels.length) {{
                    var base = origNodeColors[0] || '#a855f7';
                    origNodeColors = labels.map(function(){{ return base; }});
                }}
                if (origLinkColors.length < sources.length) {{
                    var baseL = 'rgba(148,163,184,0.55)';
                    var tmp = [];
                    for (var q = 0; q < sources.length; q++) tmp.push(baseL);
                    origLinkColors = tmp;
                }}

                var GRAY_N = 'rgba(100, 116, 139, 0.15)';
                var GRAY_L = 'rgba(100, 116, 139, 0.05)';
                var currentHighlightIdx = null;
                var CURRENT_MODE = 'volume';

                console.log('[Sankey] init N_BUYERS:', N_BUYERS,
                    'nodes:', labels.length, 'links:', sources.length);

                function fmtFlow(v) {{
                    if (v >= 1e12) return (v/1e12).toFixed(2) + 'T';
                    if (v >= 1e9) return (v/1e9).toFixed(2) + 'B';
                    if (v >= 1e6) return (v/1e6).toFixed(2) + 'M';
                    if (v >= 1e3) return Math.round(v).toLocaleString('id-ID');
                    return Math.round(v).toString();
                }}

                function buildDynamicLabels(activeNodes, activeLinksMap) {{
                    if (!activeLinksMap) return origNodeLabels.slice();
                    var flowPerNode = {{}};
                    for (var i = 0; i < labels.length; i++) flowPerNode[i] = 0;
                    for (var j = 0; j < sources.length; j++) {{
                        if (!activeLinksMap[j]) continue;
                        var v = origLinkValues[j] || 0;
                        flowPerNode[sources[j]] += v;
                        flowPerNode[targets[j]] += v;
                    }}
                    var out = [];
                    for (var k = 0; k < labels.length; k++) {{
                        var codeMatch = String(origNodeLabels[k]).match(/^([A-Z]{{2,4}})/);
                        var code = codeMatch ? codeMatch[1] : String(origNodeLabels[k]).split(' ')[0];
                        if (activeNodes[k]) {{
                            out.push(code + ' (' + fmtFlow(flowPerNode[k]) + ')');
                        }} else {{
                            out.push(code);
                        }}
                    }}
                    return out;
                }}

                function buildTrace(activeNodes, activeLinksMap) {{
                    var t = JSON.parse(JSON.stringify(ORIG));
                    // Node colors
                    var newN = [];
                    for (var i = 0; i < labels.length; i++) {{
                        newN.push(activeNodes[i] ? origNodeColors[i] : GRAY_N);
                    }}
                    t.node.color = newN;
                    // Link colors — fallback solid kalau gradient gagal
                    var newL = [];
                    for (var j = 0; j < sources.length; j++) {{
                        if (!activeLinksMap) {{
                            newL.push(origLinkColors[j] || 'rgba(148,163,184,0.55)');
                        }} else if (activeLinksMap[j]) {{
                            newL.push(origLinkColors[j] || 'rgba(148,163,184,0.55)');
                        }} else {{
                            newL.push(GRAY_L);
                        }}
                    }}
                    t.link.color = newL;
                    t.node.label = buildDynamicLabels(activeNodes, activeLinksMap);
                    return t;
                }}

                function findLinkElements() {{
                    var sels = [
                        '.sankey-link',
                        'path.sankey-link',
                        'g.sankey-links path',
                        'g.sankey-links > path',
                        'g.link path',
                        'g.sankey path',
                        'path[class*="sankey"]',
                        'path[class*="link"]'
                    ];
                    for (var i = 0; i < sels.length; i++) {{
                        try {{
                            var els = gd.querySelectorAll(sels[i]);
                            console.log('[Sankey] try selector:', sels[i],
                                        '→', els.length, 'elements');
                            if (els && els.length > 0) return els;
                        }} catch (e) {{}}
                    }}
                    var svg = gd.querySelector('svg');
                    if (!svg) {{
                        console.warn('[Sankey] ❌ no svg element');
                        return null;
                    }}
                    var allPaths = svg.querySelectorAll('path');
                    console.log('[Sankey] total paths in svg:', allPaths.length);
                    var withCurve = [];
                    allPaths.forEach(function(p) {{
                        var d = p.getAttribute('d') || '';
                        if (d.indexOf('C') !== -1 || d.indexOf('c') !== -1) {{
                            withCurve.push(p);
                        }}
                    }});
                    console.log('[Sankey] paths with curve:', withCurve.length);
                    if (withCurve.length > 0) return withCurve;
                    return allPaths.length > 0 ? allPaths : null;
                }}

                function applyGradients(activeLinksMap) {{
                    var svg = gd.querySelector('svg');
                    if (!svg) return false;

                    var linkEls = findLinkElements();
                    if (!linkEls || linkEls.length === 0) return false;

                    // Buang defs lama
                    var oldDefs = svg.querySelector('#sg-defs');
                    if (oldDefs) oldDefs.remove();
                    var defs = document.createElementNS(SVG_NS, 'defs');
                    defs.setAttribute('id', 'sg-defs');
                    svg.insertBefore(defs, svg.firstChild);

                    // ▼ Hitung lebar SVG dalam user units (viewBox)
                    var svgW = 1000;
                    try {{
                        var vb = svg.viewBox && svg.viewBox.baseVal;
                        if (vb && vb.width > 0) {{
                            svgW = vb.width;
                        }} else {{
                            svgW = svg.clientWidth ||
                                   svg.getBoundingClientRect().width || 1000;
                        }}
                    }} catch(e) {{}}
                    console.log('[Sankey] svgW:', svgW);

                    var nLinks = sources.length;
                    var applied = 0;

                    // ▼ Loop SEMUA element (128), map index → link asli dengan modulo
                    for (var i = 0; i < linkEls.length; i++) {{
                        var linkEl = linkEls[i];
                        var linkIdx = i % nLinks;

                        var isActive = !activeLinksMap || activeLinksMap[linkIdx];
                        if (!isActive) continue;

                        var srcColor = origNodeColors[sources[linkIdx]] || '#64748b';
                        var tgtColor = origNodeColors[targets[linkIdx]] || '#64748b';

                        var gid = 'sg-grad-' + i;
                        var gr = document.createElementNS(SVG_NS, 'linearGradient');
                        gr.setAttribute('id', gid);

                        // ▼ KUNCI FIX: userSpaceOnUse + koordinat absolute SVG
                        gr.setAttribute('gradientUnits', 'userSpaceOnUse');
                        gr.setAttribute('x1', 0);
                        gr.setAttribute('y1', 0);
                        gr.setAttribute('x2', svgW);
                        gr.setAttribute('y2', 0);

                        var s1 = document.createElementNS(SVG_NS, 'stop');
                        s1.setAttribute('offset', '0%');
                        s1.setAttribute('stop-color', srcColor);
                        s1.setAttribute('stop-opacity', '0.85');

                        var s2 = document.createElementNS(SVG_NS, 'stop');
                        s2.setAttribute('offset', '100%');
                        s2.setAttribute('stop-color', tgtColor);
                        s2.setAttribute('stop-opacity', '0.85');

                        gr.appendChild(s1);
                        gr.appendChild(s2);
                        defs.appendChild(gr);

                        linkEl.setAttribute('fill', 'url(#' + gid + ')');
                        linkEl.style.setProperty('fill', 'url(#' + gid + ')', 'important');
                        applied++;
                    }}

                    console.log('[Sankey] ✅ gradient applied:', applied,
                                'of', linkEls.length, 'elements (svgW:' + svgW + ')');
                    return applied > 0;
                }}

                function renderWithGradients(activeNodes, activeLinksMap) {{
                    var t = buildTrace(activeNodes, activeLinksMap);
                    return Plotly.react(gd, [t], LAYOUT, config).then(function() {{
                        function tryApply(attempt) {{
                            if (attempt > 6) {{
                                console.warn('[Sankey] gradient retry exhausted');
                                return;
                            }}
                            var ok = applyGradients(activeLinksMap);
                            if (!ok) {{
                                setTimeout(function() {{
                                    tryApply(attempt + 1);
                                }}, 120 + attempt * 80);
                            }}
                        }}
                        requestAnimationFrame(function() {{
                            requestAnimationFrame(function() {{
                                tryApply(0);
                            }});
                        }});
                    }});
                }}

                function highlightNode(nodeIdx) {{
                    var isBuyer = nodeIdx < N_BUYERS;
                    var activeNodes = {{}};
                    var activeLinks = {{}};
                    activeNodes[nodeIdx] = true;

                    for (var j = 0; j < sources.length; j++) {{
                        if (isBuyer) {{
                            if (sources[j] === nodeIdx) {{
                                activeLinks[j] = true;
                                activeNodes[targets[j]] = true;
                            }}
                        }} else {{
                            if (targets[j] === nodeIdx) {{
                                activeLinks[j] = true;
                                activeNodes[sources[j]] = true;
                            }}
                        }}
                    }}

                    currentHighlightIdx = nodeIdx;
                    renderWithGradients(activeNodes, activeLinks);

                    document.querySelectorAll('.chip').forEach(function(c) {{
                        var idx = parseInt(c.getAttribute('data-node-idx'));
                        if (idx === nodeIdx) c.classList.add('active');
                        else c.classList.remove('active');
                    }});

                    if (navigator.vibrate) {{ try {{ navigator.vibrate(8); }} catch(e) {{}} }}
                }}

                function resetAll() {{
                    currentHighlightIdx = null;
                    var all = {{}};
                    for (var i = 0; i < labels.length; i++) all[i] = true;
                    renderWithGradients(all, null);
                    document.querySelectorAll('.chip').forEach(function(c) {{
                        c.classList.remove('active');
                    }});
                    if (navigator.vibrate) {{ try {{ navigator.vibrate(8); }} catch(e) {{}} }}
                }}

                function applyMode(mode) {{
                    if (!MODE_PAYLOAD || !MODE_PAYLOAD[mode]) return;
                    var md = MODE_PAYLOAD[mode];
                    ORIG.link.value = md.link_values.slice();
                    ORIG.node.label = md.node_labels.slice();
                    origNodeLabels = md.node_labels.slice();
                    origLinkValues = md.link_values.slice();
                    labels = ORIG.node.label.slice();
                    CURRENT_MODE = mode;

                    document.querySelectorAll('.mode-btn').forEach(function(b) {{
                        if (b.getAttribute('data-mode') === mode) b.classList.add('active');
                        else b.classList.remove('active');
                    }});

                    if (currentHighlightIdx !== null) highlightNode(currentHighlightIdx);
                    else resetAll();
                }}

                // INITIAL RENDER 
                var initNodes = {{}};
                for (var ii = 0; ii < labels.length; ii++) initNodes[ii] = true;
                var initTrace = buildTrace(initNodes, null);

                Plotly.newPlot(gd, [initTrace], LAYOUT, config).then(function() {{
                    function tryApplyInit(attempt) {{
                        if (attempt > 6) {{
                            console.warn('[Sankey] init gradient retry exhausted');
                            return;
                        }}
                        var ok = applyGradients(null);
                        if (!ok) {{
                            setTimeout(function() {{
                                tryApplyInit(attempt + 1);
                            }}, 120 + attempt * 80);
                        }}
                    }}
                    requestAnimationFrame(function() {{
                        requestAnimationFrame(function() {{
                            tryApplyInit(0);
                        }});
                    }});
                }}).catch(function(err) {{
                    console.error('[Sankey] newPlot error:', err);
                }});

                // EVENT DELEGATION — attach ke document, bukan chip
                document.addEventListener('click', function(ev) {{
                    var target = ev.target;
                    if (!target) return;

                    // Chip
                    var chip = target.closest ? target.closest('.chip') : null;
                    if (chip) {{
                        var idx = parseInt(chip.getAttribute('data-node-idx'));
                        if (currentHighlightIdx === idx) resetAll();
                        else highlightNode(idx);
                        return;
                    }}

                    // Mode button
                    var mbtn = target.closest ? target.closest('.mode-btn') : null;
                    if (mbtn) {{
                        var m = mbtn.getAttribute('data-mode');
                        if (m !== CURRENT_MODE) applyMode(m);
                        return;
                    }}

                    // Reset button
                    var rbtn = target.closest ? target.closest('#reset') : null;
                    if (rbtn) resetAll();
                }});

                // Native Sankey click (best-effort)
                gd.on('plotly_click', function(data) {{
                    if (!data || !data.points || !data.points.length) return;
                    var pt = data.points[0];
                    if (pt.pointType === 'node' && typeof pt.pointNumber === 'number') {{
                        highlightNode(pt.pointNumber);
                    }}
                }});
            }})();
        </script>
    </body>
    </html>
    """
    components.html(html, height=height + 100, scrolling=False)
