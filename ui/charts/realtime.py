"""Realtime Plotly embed — tooltip follow finger, haptic, legend HTML manual."""
from __future__ import annotations

import streamlit.components.v1 as components

def render_plotly_realtime(fig, height=420, haptic=True):
    """
    Embed Plotly.js ala Stockbit (v3):
    - Tap + geser = vline + tooltip follow jari realtime
    - Haptic vibration tiap index berubah (Android)
    - Legend HTML manual di bawah chart (anti-crop di semua browser)
    - Auto-hide setelah 2.5 detik idle
    """
    if fig is None:
        return

    fig_json = fig.to_json()
    haptic_js = "true" if haptic else "false"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            html, body {{
                margin: 0; padding: 0;
                background: #0f1116;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                overflow: hidden;
            }}
            #wrapper {{ position: relative; width: 100%; height: {height}px; }}
            #chart {{ width: 100%; height: {height}px; touch-action: pan-y; }}
            #tooltip {{
                position: absolute;
                top: 8px; left: 8px;
                background: rgba(30, 41, 59, 0.96);
                color: #e2e8f0;
                padding: 8px 12px;
                border-radius: 8px;
                font-size: 11px;
                line-height: 1.5;
                pointer-events: none;
                display: none;
                z-index: 999;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
                border-left: 3px solid #a855f7;
                max-width: 68%;
            }}
            #tooltip b {{ color: #a855f7; font-size: 12px; }}
            #tooltip .row {{ margin-top: 3px; display: flex; align-items: center; }}
            #tooltip .dot {{
                display: inline-block;
                width: 7px; height: 7px;
                border-radius: 50%;
                margin-right: 6px;
                flex-shrink: 0;
            }}
            #legend {{
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 6px 14px;
                padding: 8px 10px 10px 10px;
                margin: 0;
                background: #0f1116;
                font-size: 11px;
                color: #94a3b8;
            }}
            #legend .item {{
                display: inline-flex;
                align-items: center;
                white-space: nowrap;
                cursor: pointer;
                user-select: none;
                -webkit-tap-highlight-color: transparent;
                padding: 2px 6px;
                border-radius: 4px;
                transition: opacity 0.15s, background 0.15s;
            }}
            #legend .item.hidden {{
                opacity: 0.30;
                text-decoration: line-through;
            }}
            #legend .item:active {{
                background: rgba(168, 85, 247, 0.20);
            }}
            #legend .swatch {{
                display: inline-block;
                width: 10px; height: 10px;
                border-radius: 2px;
                margin-right: 5px;
                flex-shrink: 0;
            }}
        </style>
    </head>
    <body>
        <div id="wrapper">
            <div id="chart"></div>
            <div id="tooltip"></div>
        </div>
        <div id="legend"></div>
        <script>
            (function() {{
                var figData = {fig_json};
                var HAPTIC = {haptic_js};

                if (figData.layout) {{
                    figData.layout.hovermode = false;
                    figData.layout.showlegend = false;
                }}

                var config = {{
                    displayModeBar: false,
                    responsive: true,
                    scrollZoom: false,
                    displaylogo: false
                }};

                var gd = document.getElementById('chart');
                var tooltip = document.getElementById('tooltip');
                var legendDiv = document.getElementById('legend');

                Plotly.newPlot(gd, figData.data, figData.layout, config).then(function() {{
                    // ── Bangun legend HTML dari trace (dengan interaksi) ──
                    var legendHtml = '';
                    for (var i = 0; i < gd._fullData.length; i++) {{
                        var t = gd._fullData[i];
                        var name = t.name || ('Series ' + i);
                        var color = (t.line && t.line.color) ||
                                    (t.marker && t.marker.color) ||
                                    '#a855f7';
                        legendHtml += '<span class="item" data-idx="' + i + '">' +
                                      '<span class="swatch" style="background:' + color + '"></span>' +
                                      name + '</span>';
                    }}
                    legendDiv.innerHTML = legendHtml;

                    // ── Click handler: toggle trace visibility ──
                    var hiddenTraces = {{}};
                    legendDiv.querySelectorAll('.item').forEach(function(el) {{
                        el.addEventListener('click', function() {{
                            var idx = parseInt(el.getAttribute('data-idx'));
                            var nowHidden = !hiddenTraces[idx];

                            // Plotly: 'legendonly' = hidden, true = visible
                            var vis = nowHidden ? 'legendonly' : true;
                            Plotly.restyle(gd, {{ visible: vis }}, [idx]);

                            hiddenTraces[idx] = nowHidden;
                            if (nowHidden) {{
                                el.classList.add('hidden');
                            }} else {{
                                el.classList.remove('hidden');
                            }}

                            // Haptic feedback (Android only)
                            if (HAPTIC && navigator.vibrate) {{
                                try {{ navigator.vibrate(10); }} catch(e) {{}}
                            }}
                        }});
                    }});

                    // ── Ambil xValues ──
                    var xValues = null;
                    for (var i = 0; i < gd._fullData.length; i++) {{
                        var xd = gd._fullData[i].x;
                        if (xd && xd.length > 0) {{
                            xValues = xd;
                            break;
                        }}
                    }}
                    if (!xValues || xValues.length === 0) {{
                        console.error('[Bandarmology] No x values');
                        return;
                    }}

                    // ── y per trace ──
                    var yPerTrace = [];
                    var namePerTrace = [];
                    var colorPerTrace = [];
                    for (var i = 0; i < gd._fullData.length; i++) {{
                        var t = gd._fullData[i];
                        yPerTrace.push(t.y || []);
                        namePerTrace.push(t.name || ('Series ' + i));
                        var c = (t.line && t.line.color) ||
                                (t.marker && t.marker.color) || '#a855f7';
                        colorPerTrace.push(c);
                    }}

                    // ── Shape vline ──
                    var initX = xValues[0];
                    var baseShapes = (gd.layout.shapes || []).slice();
                    baseShapes.push({{
                        type: 'line',
                        xref: 'x', x0: initX, x1: initX,
                        yref: 'paper', y0: 0, y1: 1,
                        line: {{ color: '#a855f7', width: 2, dash: 'dash' }},
                        opacity: 0
                    }});
                    Plotly.relayout(gd, {{ shapes: baseShapes }});
                    var V_IDX = baseShapes.length - 1;

                    function pixelToIndex(clientX) {{
                        var rect = gd.getBoundingClientRect();
                        var fl = gd._fullLayout;
                        var plotLeft = fl.margin.l;
                        var plotRight = rect.width - fl.margin.r;
                        var plotWidth = plotRight - plotLeft;
                        if (plotWidth <= 0) return 0;
                        var relX = clientX - rect.left - plotLeft;
                        var ratio = relX / plotWidth;
                        ratio = Math.max(0, Math.min(1, ratio));
                        return Math.round(ratio * (xValues.length - 1));
                    }}

                    function vibrate() {{
                        if (!HAPTIC || !navigator.vibrate) return;
                        try {{ navigator.vibrate(6); }} catch(e) {{}}
                    }}

                    var lastIdx = -1;
                    var rafPending = false;
                    var pendingX = null;
                    var active = false;
                    var hideTimer = null;

                    function draw(clientX) {{
                        var idx = pixelToIndex(clientX);
                        if (idx < 0) idx = 0;
                        if (idx >= xValues.length) idx = xValues.length - 1;
                        var xVal = xValues[idx];

                        var upd = {{}};
                        upd['shapes[' + V_IDX + '].x0'] = xVal;
                        upd['shapes[' + V_IDX + '].x1'] = xVal;
                        upd['shapes[' + V_IDX + '].opacity'] = 1;
                        Plotly.relayout(gd, upd);

                        function formatKMB(val, name) {{
                            if (val === null || val === undefined || isNaN(val)) return 'N/A';
                            var n = name ? name.toLowerCase() : '';
                            var isPrice = n.indexOf('price') !== -1 || n.indexOf('harga') !== -1;
                            var absVal = Math.abs(val);
                            if (isPrice && absVal < 1000000) {{
                                return val.toLocaleString('id-ID', {{ maximumFractionDigits: 2 }});
                            }}
                            var sign = val < 0 ? '-' : '';
                            var res = '';
                            if (absVal >= 1e9) {{
                                res = sign + (absVal / 1e9).toFixed(2).replace(/\.00$/, '') + 'B';
                            }} else if (absVal >= 1e6) {{
                                res = sign + (absVal / 1e6).toFixed(2).replace(/\.00$/, '') + 'M';
                            }} else if (absVal >= 1e3) {{
                                res = sign + (absVal / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
                            }} else {{
                                res = sign + absVal.toLocaleString('id-ID', {{ maximumFractionDigits: 2 }});
                            }}
                            if (n.indexOf('accum') !== -1 || n.indexOf('dist') !== -1 || n.indexOf('lot') !== -1) {{
                                res += ' Lot';
                            }}
                            return res;
                        }}

                        var lines = ['<b>' + xVal + '</b>'];
                        for (var i = 0; i < yPerTrace.length; i++) {{
                            // Skip trace yang di-hide via legend
                            if (hiddenTraces[i]) continue;

                            var yv = yPerTrace[i][idx];
                            if (typeof yv === 'number' && !isNaN(yv)) {{
                                var fv = formatKMB(yv, namePerTrace[i]);
                                lines.push(
                                    '<div class="row"><span class="dot" style="background:' +
                                    colorPerTrace[i] + '"></span>' +
                                    namePerTrace[i] + ': ' + fv + '</div>'
                                );
                            }}
                        }}
                        tooltip.innerHTML = lines.join('');
                        tooltip.style.display = 'block';

                        var rect = gd.getBoundingClientRect();
                        var tw = tooltip.offsetWidth || 140;
                        var left = clientX - rect.left + 14;
                        if (left + tw > rect.width - 4) {{
                            left = clientX - rect.left - tw - 14;
                        }}
                        if (left < 4) left = 4;
                        tooltip.style.left = left + 'px';

                        if (idx !== lastIdx) {{
                            vibrate();
                            lastIdx = idx;
                        }}

                        if (hideTimer) clearTimeout(hideTimer);
                        hideTimer = setTimeout(function() {{
                            tooltip.style.display = 'none';
                            var u = {{}};
                            u['shapes[' + V_IDX + '].opacity'] = 0;
                            Plotly.relayout(gd, u);
                        }}, 2500);
                    }}

                    function throttled(clientX) {{
                        pendingX = clientX;
                        if (!rafPending) {{
                            rafPending = true;
                            requestAnimationFrame(function() {{
                                rafPending = false;
                                if (pendingX !== null) {{
                                    draw(pendingX);
                                    pendingX = null;
                                }}
                            }});
                        }}
                    }}

                    gd.addEventListener('touchstart', function(e) {{
                        active = true;
                        lastIdx = -1;
                        if (hideTimer) clearTimeout(hideTimer);
                        draw(e.touches[0].clientX);
                    }}, {{ passive: true }});

                    gd.addEventListener('touchmove', function(e) {{
                        if (!active) return;
                        throttled(e.touches[0].clientX);
                    }}, {{ passive: true }});

                    gd.addEventListener('touchend', function() {{ active = false; }}, {{ passive: true }});
                    gd.addEventListener('touchcancel', function() {{ active = false; }}, {{ passive: true }});

                    gd.addEventListener('mousemove', function(e) {{
                        if (e.buttons === 0) {{
                            if (hideTimer) clearTimeout(hideTimer);
                            throttled(e.clientX);
                        }}
                    }});

                    window.addEventListener('resize', function() {{
                        Plotly.Plots.resize(gd);
                    }});
                }});
            }})();
        </script>
    </body>
    </html>
    """
    # ── Hitung tinggi iframe dinamis ──
    # Legend HTML bisa wrap ke beberapa baris tergantung jumlah trace & lebar layar
    # Di iOS (layar sempit) worst case ~2-3 item per baris
    n_traces = len(fig.data)
    legend_rows = max(2, (n_traces + 2) // 3)   
    legend_h = legend_rows * 28 + 20            
    iframe_h = height + legend_h + 10           

    components.html(html, height=iframe_h, scrolling=False)
