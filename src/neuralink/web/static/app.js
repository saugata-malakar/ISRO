// NeuraLink dashboard logic — bundled, offline. No external requests.
const COLORS = ["#06b6d4", "#6c8cff", "#10b981", "#f59e0b", "#ef4444", "#a855f7"];

let currentRunData = null;
let playbackInterval = null;
let isAnimating = false;
let terminalTarget = null; // Stores details of command to execute

function sevClass(sev) {
  return sev === "critical" ? "sev-critical" : sev === "warning" ? "sev-warning" : "";
}

function renderChart(data, limitTick = null) {
  const canvas = document.getElementById("chart");
  const metric = document.getElementById("metric-select")?.value || "cpu";
  
  const trendSource = limitTick ? data.trend.slice(0, limitTick) : data.trend;
  const xmax = 30; // Lock to 30 ticks for a smooth left-to-right fill animation
  
  let ymax = 100;
  let thresholds = [];
  
  if (metric === "cpu") {
    ymax = 100;
    thresholds = [
      { value: 85, color: "#ef4444" },
      { value: 60, color: "#f59e0b" },
    ];
  } else if (metric === "temp") {
    ymax = 100;
    thresholds = [
      { value: 80, color: "#ef4444" },
      { value: 65, color: "#f59e0b" },
    ];
  } else if (metric === "errors") {
    let maxVal = 10;
    data.trend.forEach((r) => {
      data.devices.forEach((d) => {
        if (r[d] && r[d].errors > maxVal) {
          maxVal = r[d].errors;
        }
      });
    });
    ymax = Math.ceil(maxVal * 1.2 / 10) * 10;
    thresholds = [
      { value: ymax * 0.8, color: "#ef4444" },
      { value: ymax * 0.5, color: "#f59e0b" },
    ];
  }

  const series = data.devices.map((d, i) => ({
    label: d,
    color: COLORS[i % COLORS.length],
    points: trendSource
      .filter((r) => r[d])
      .map((r) => ({ x: r.tick, y: r[d][metric] || 0 })),
  }));

  drawLineChart(canvas, series, {
    xmin: 0, xmax, ymin: 0, ymax,
    thresholds,
  });

  const legend = document.getElementById("legend");
  legend.innerHTML = data.devices
    .map((d, i) => `<span><span class="dot" style="background:${COLORS[i % COLORS.length]}"></span>${d}</span>`)
    .join("");
}

function renderAlerts(data, currentSimTime = null) {
  const tbody = document.querySelector("#alerts tbody");
  const alertsToRender = currentSimTime !== null
    ? data.alerts.filter((a) => a.alert.event.sim_time <= currentSimTime)
    : data.alerts;

  if (!alertsToRender.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">No alerts in this run.</td></tr>`;
    return;
  }
  tbody.innerHTML = alertsToRender
    .map((a) => {
      const ev = a.alert.event, b = a.blast, r = a.response;
      const rec = r.remediation.find((s) => s.recommended);
      const svc = b.affected_services.map((s) => s.id).join(", ") || "none";
      
      const executeBtn = rec 
        ? `<button class="run execute-btn" style="font-size:11px;padding:3px 8px;margin-left:8px;border-radius:4px;" data-device="${ev.source_device}" data-command="${rec.command}" data-alert="${a.alert.alert_id}">Execute</button>`
        : "";

      return `<tr>
        <td class="${sevClass(ev.severity_raw)}">${a.alert.severity}</td>
        <td>${ev.source_device}<br><span class="muted" style="font-size:11px;font-family:monospace;">${ev.event_type}</span></td>
        <td>${a.alert.anomaly_score} / <b>${b.score}</b></td>
        <td>${svc}</td>
        <td><span class="stepcmd">${rec ? rec.command : "-"}</span>
            ${executeBtn}<br>
            <span class="muted" style="font-size:12px;display:inline-block;margin-top:6px;">${r.root_cause}</span></td>
      </tr>`;
    })
    .join("");
    
  // Bind Execute buttons
  document.querySelectorAll(".execute-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const device = e.target.getAttribute("data-device");
      const command = e.target.getAttribute("data-command");
      const alertId = e.target.getAttribute("data-alert");
      openTerminal(device, command, alertId);
    });
  });
}

function renderForecasts(data, currentSimTime = null) {
  const el = document.getElementById("forecasts");
  const warningsToRender = currentSimTime !== null
    ? data.forecasts.filter((f) => f.sim_time <= currentSimTime)
    : data.forecasts;

  el.innerHTML = warningsToRender.length
    ? warningsToRender.map((f) => `⚠ ${f.message}`).join("<br>")
    : `<span class="muted">No early warnings.</span>`;
}

function renderAudit(data, currentProgressFraction = 1.0) {
  const el = document.getElementById("audit");
  const ok = data.audit.ok;
  const targetCount = Math.round(data.audit.count * currentProgressFraction);
  
  if (currentProgressFraction < 1.0) {
    el.innerHTML = `<span class="pill ok">ANALYSING CHAIN</span>
      <span class="muted">${targetCount} of ${data.audit.count} entries verified</span>`;
  } else {
    el.innerHTML = `<span class="pill ${ok ? "ok" : "bad"}">${ok ? "VERIFIED" : "TAMPERED"}</span>
      <span class="muted">${data.audit.count} hash-chained entries</span>`;
  }
}

// Draw the static or dynamic topology map.
function drawTopology(sevMap) {
  const svg = document.getElementById("topo");
  const W = svg.clientWidth || 600, H = 250;
  const N = window.__NODES__, E = window.__EDGES__;
  const pos = {};
  N.forEach((n) => (pos[n.id] = { x: 30 + n.x * (W - 60), y: 30 + n.y * (H - 60) }));
  let s = "";
  E.forEach((e) => {
    const a = pos[e.src], b = pos[e.dst];
    if (a && b) s += `<line class="edge" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`;
  });
  N.forEach((n) => {
    const p = pos[n.id];
    const sev = (sevMap && sevMap[n.id]) || "info";
    const col = sev === "critical" ? "#ef4444" : (sev === "warning" ? "#f59e0b" : "#10b981");
    const status = sev === "critical" ? "crit" : (sev === "warning" ? "warn" : "ok");
    s += `<g class="node node-${status}">
            <circle cx="${p.x}" cy="${p.y}" r="10" fill="${col}" style="transition: fill 0.4s ease;"/>
            <text x="${p.x + 15}" y="${p.y + 4}">${n.id}</text>
          </g>`;
  });
  svg.innerHTML = s;
}

// Interactive Operator Terminal logic
function openTerminal(device, command, alertId) {
  const overlay = document.getElementById("terminal-overlay");
  const termBody = document.getElementById("terminal-body");
  const actionBtn = document.getElementById("terminal-action-btn");
  
  terminalTarget = { device, command, alertId };
  termBody.innerHTML = "";
  overlay.style.display = "flex";
  actionBtn.style.display = "block";
  actionBtn.disabled = true;
  
  let line1 = `> Initiating remote management tunnel to ${device}...\n`;
  let line2 = `> Target node resolved at 10.0.3.${device.includes("3") ? "3" : "1"}\n`;
  let line3 = `> Establishing secure console shell...\n`;
  let line4 = `> Access Granted (Role: Network Operator)\n\n`;
  let fullIntro = line1 + line2 + line3 + line4;
  
  termBody.innerHTML = fullIntro;
  
  // Character typing animation for command line
  let cmdLine = `${device}# ${command}`;
  let cmdIndex = 0;
  
  const typeCmd = () => {
    if (cmdIndex < cmdLine.length) {
      termBody.innerHTML += cmdLine[cmdIndex];
      cmdIndex++;
      termBody.scrollTop = termBody.scrollHeight;
      setTimeout(typeCmd, 35);
    } else {
      termBody.innerHTML += "\n";
      actionBtn.disabled = false;
    }
  };
  
  setTimeout(typeCmd, 800);
}

async function confirmRemediation() {
  if (!terminalTarget) return;
  const termBody = document.getElementById("terminal-body");
  const actionBtn = document.getElementById("terminal-action-btn");
  
  actionBtn.style.display = "none";
  termBody.innerHTML += `\n> Dispatching command block to control plane...\n`;
  
  const { device, command, alertId } = terminalTarget;
  const res = await fetch(`/api/execute?device=${device}&command=${command}&alert_id=${alertId}`);
  const data = await res.json();
  
  if (data.ok) {
    termBody.innerHTML += `\n${data.output}\n`;
    termBody.innerHTML += `> Egress block verified: Clean offline status.\n`;
    termBody.scrollTop = termBody.scrollHeight;
    
    // Update dashboard audit panel count
    if (currentRunData) {
      currentRunData.audit = data.audit;
      renderAudit(currentRunData);
    }
  } else {
    termBody.innerHTML += `\nError: Command execution failed.\n`;
  }
}

// Tamper simulation
async function triggerTamper() {
  const res = await fetch("/api/tamper");
  const data = await res.json();
  if (data.ok) {
    alert("CRITICAL WARNING: Database has been tampered! The signature of the last audit block was altered manually. Run 'Verify Chain' to test signature detection.");
  } else {
    alert(`Failed to tamper: ${data.reason}`);
  }
}

// Live Audit log verification
async function verifyAuditChain() {
  const verifyBtn = document.getElementById("verify-btn");
  const auditPanel = verifyBtn.closest(".panel");
  
  verifyBtn.textContent = "Verifying...";
  
  const res = await fetch("/api/verify");
  const data = await res.json();
  
  setTimeout(() => {
    verifyBtn.textContent = "Verify Chain";
    const el = document.getElementById("audit");
    const ok = data.ok;
    
    if (ok) {
      el.innerHTML = `<span class="pill ok">VERIFIED</span>
        <span class="muted">${data.count} hash-chained entries. All hashes match cryptographic sign.</span>`;
      auditPanel.style.borderColor = "var(--green)";
      auditPanel.style.boxShadow = "0 0 20px rgba(16, 185, 129, 0.25)";
    } else {
      el.innerHTML = `<span class="pill bad">TAMPER DETECTED</span>
        <span class="muted">${data.count} hash-chained entries. Broken signature: ${data.reason} at seq #${data.bad_seq}</span>`;
      auditPanel.style.borderColor = "var(--red)";
      auditPanel.style.boxShadow = "0 0 20px rgba(239, 68, 68, 0.25)";
      
      // Flash red screen overlay effect
      const origBg = document.body.style.background;
      document.body.style.background = "#240404";
      setTimeout(() => {
        document.body.style.background = origBg;
      }, 500);
    }
    
    // Reset borders after 4 seconds
    setTimeout(() => {
      auditPanel.style.borderColor = "";
      auditPanel.style.boxShadow = "";
    }, 4000);
  }, 600);
}

async function runScenario() {
  if (isAnimating) {
    clearInterval(playbackInterval);
  }
  
  const scenario = document.getElementById("scenario").value;
  const seed = document.getElementById("seed").value || 42;
  const status = document.getElementById("status");
  
  status.textContent = "initializing…";
  
  // Clear dashboard to initial clean look before animating
  document.querySelector("#alerts tbody").innerHTML = `<tr><td colspan="5" class="muted">Live telemetry feed connecting...</td></tr>`;
  document.getElementById("forecasts").innerHTML = `<span class="muted">Awaiting warnings...</span>`;
  document.getElementById("audit").innerHTML = `<span class="muted">—</span>`;
  drawTopology(); // Reset to neutral state
  
  const res = await fetch(`/api/run?scenario=${scenario}&seed=${seed}&ticks=30`);
  const data = await res.json();
  
  currentRunData = data;
  isAnimating = true;
  
  let tickIndex = 1;
  const totalTicks = data.trend.length;
  
  status.textContent = "PLAYBACK TUI ACTIVE";
  
  playbackInterval = setInterval(() => {
    const currentSimTime = data.trend[tickIndex - 1]?.sim_time || 0;
    status.textContent = `TICK ${tickIndex}/30 (SIM_T: ${currentSimTime.toFixed(0)}s)`;
    
    // 1. Draw chart up to current tick
    renderChart(data, tickIndex);
    
    // 2. Render alerts up to current sim time
    renderAlerts(data, currentSimTime);
    
    // 3. Render forecasts up to current sim time
    renderForecasts(data, currentSimTime);
    
    // 4. Render progressive audit logs count
    renderAudit(data, tickIndex / totalTicks);
    
    // 5. Update topology device colors at current tick
    const currentTickRow = data.trend[tickIndex - 1];
    const sevMap = {};
    data.devices.forEach((d) => {
      if (currentTickRow && currentTickRow[d]) {
        sevMap[d] = currentTickRow[d].sev;
      }
    });
    drawTopology(sevMap);
    
    tickIndex++;
    
    if (tickIndex > totalTicks) {
      clearInterval(playbackInterval);
      isAnimating = false;
      status.textContent = "PLAYBACK COMPLETE";
      
      // Finalize states
      renderChart(data);
      renderAlerts(data);
      renderForecasts(data);
      renderAudit(data);
      
      const lastTick = data.trend[totalTicks - 1];
      const finalSevMap = {};
      data.devices.forEach((d) => {
        if (lastTick && lastTick[d]) {
          finalSevMap[d] = lastTick[d].sev;
        }
      });
      drawTopology(finalSevMap);
    }
  }, 180); // 180ms per tick => ~5.4s total playback
}

window.addEventListener("DOMContentLoaded", () => {
  drawTopology();
  document.getElementById("run").addEventListener("click", runScenario);
  
  document.getElementById("metric-select")?.addEventListener("change", () => {
    if (currentRunData && !isAnimating) {
      renderChart(currentRunData);
    }
  });
  
  // Bind Terminal Controls
  document.getElementById("terminal-close").addEventListener("click", () => {
    document.getElementById("terminal-overlay").style.display = "none";
  });
  document.getElementById("terminal-action-btn").addEventListener("click", confirmRemediation);
  
  // Bind Tamper & Verify Buttons
  document.getElementById("tamper-btn").addEventListener("click", triggerTamper);
  document.getElementById("verify-btn").addEventListener("click", verifyAuditChain);
});
