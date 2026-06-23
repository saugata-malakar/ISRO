// Tiny self-contained canvas line chart (no external libraries / CDN).
// drawLineChart(canvas, series, opts) where series = [{label,color,points:[{x,y}]}].
(function (global) {
  function drawLineChart(canvas, series, opts) {
    opts = opts || {};
    var ctx = canvas.getContext("2d");
    var dpr = global.devicePixelRatio || 1;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr; ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    var padL = 36, padB = 22, padT = 10, padR = 10;
    var x0 = padL, y0 = h - padB, x1 = w - padR, y1 = padT;
    var xmin = opts.xmin ?? 0, xmax = opts.xmax ?? 1;
    var ymin = opts.ymin ?? 0, ymax = opts.ymax ?? 100;
    function sx(x) { return x0 + (x - xmin) / (xmax - xmin || 1) * (x1 - x0); }
    function sy(y) { return y0 + (y - ymin) / (ymax - ymin || 1) * (y1 - y0); }

    // grid + y labels
    ctx.strokeStyle = "#222a44"; ctx.fillStyle = "#8b97c0"; ctx.font = "10px monospace";
    for (var g = 0; g <= 4; g++) {
      var yv = ymin + (ymax - ymin) * g / 4;
      var yy = sy(yv);
      ctx.beginPath(); ctx.moveTo(x0, yy); ctx.lineTo(x1, yy); ctx.stroke();
      ctx.fillText(String(Math.round(yv)), 6, yy + 3);
    }
    // threshold lines (warning/critical)
    (opts.thresholds || []).forEach(function (t) {
      ctx.strokeStyle = t.color; ctx.setLineDash([4, 4]);
      var yy = sy(t.value); ctx.beginPath(); ctx.moveTo(x0, yy); ctx.lineTo(x1, yy); ctx.stroke();
      ctx.setLineDash([]);
    });

    series.forEach(function (s) {
      if (!s.points.length) return;

      // 1. Draw area gradient under the line
      var hex = s.color;
      var rgba1 = "rgba(108, 140, 255, 0.12)";
      if (hex.startsWith("#")) {
        var r = parseInt(hex.slice(1, 3), 16);
        var g = parseInt(hex.slice(3, 5), 16);
        var b = parseInt(hex.slice(5, 7), 16);
        rgba1 = "rgba(" + r + "," + g + "," + b + ", 0.12)";
      }
      var grad = ctx.createLinearGradient(0, y1, 0, y0);
      grad.addColorStop(0, rgba1);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(sx(s.points[0].x), y0);
      s.points.forEach(function (p) {
        ctx.lineTo(sx(p.x), sy(p.y));
      });
      ctx.lineTo(sx(s.points[s.points.length - 1].x), y0);
      ctx.closePath();
      ctx.fill();

      // 2. Draw line with neon glow shadow
      ctx.strokeStyle = s.color; ctx.lineWidth = 2.5;
      ctx.shadowBlur = 6; ctx.shadowColor = s.color;
      ctx.beginPath();
      s.points.forEach(function (p, i) {
        var X = sx(p.x), Y = sy(p.y);
        if (i === 0) ctx.moveTo(X, Y); else ctx.lineTo(X, Y);
      });
      ctx.stroke();
      ctx.shadowBlur = 0; // reset shadow
    });
  }
  global.drawLineChart = drawLineChart;
})(window);
