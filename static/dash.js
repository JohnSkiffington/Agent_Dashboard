/* Agent Dashboard — Frontend polling and rendering */

const API_URL = "/api/sessions";
const POLL_INTERVAL = 5000;

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
}

function formatTokens(n) {
    if (!n) return "0";
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
    return n.toString();
}

function formatCost(usd) {
    if (!usd) return "$0.00";
    return "$" + usd.toFixed(2);
}

function truncatePrompt(text, maxLen = 120) {
    if (!text) return "No task description";
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen) + "...";
}

function timeAgo(epochMs) {
    const seconds = Math.floor((Date.now() - epochMs) / 1000);
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function getProjectStatus(project) {
    const active = project.active_sessions || [];
    if (active.length === 0) return "idle";
    if (active.some(s => s.status === "stale")) return "stale";
    return "active";
}

function renderSession(session) {
    const isActive = session.status === "active";
    const isStale = session.status === "stale";
    const statusClass = isActive ? "active" : isStale ? "stale" : "completed";

    const inputTokens = session.total_input_tokens || 0;
    const outputTokens = session.total_output_tokens || 0;
    const cacheRead = session.total_cache_read || 0;
    const cost = session.estimated_cost_usd || 0;
    const lastTool = session.last_event ? session.last_event.tool_name : null;

    let timeDisplay = "";
    let timeClass = "";
    if (isActive || isStale) {
        const runSec = session.running_for_seconds || Math.floor((Date.now() - session.started_at) / 1000);
        timeDisplay = formatDuration(runSec);
        timeClass = isActive ? "active-time" : "stale-time";
    } else {
        timeDisplay = timeAgo(session.started_at);
        timeClass = "";
    }

    return `
        <div class="session-card ${statusClass}">
            <div class="session-prompt">
                <span class="session-status-dot ${statusClass}"></span>
                ${escapeHtml(truncatePrompt(session.initial_prompt))}
            </div>
            <div class="session-meta">
                <div class="meta-item">
                    <span class="meta-label">time</span>
                    <span class="meta-value ${timeClass}">${timeDisplay}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">cost</span>
                    <span class="meta-value cost">${formatCost(cost)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">in</span>
                    <span class="meta-value">${formatTokens(inputTokens + cacheRead)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">out</span>
                    <span class="meta-value">${formatTokens(outputTokens)}</span>
                </div>
                ${session.model ? `<div class="meta-item">
                    <span class="meta-label">model</span>
                    <span class="meta-value">${escapeHtml(session.model.replace("claude-", "").replace(/-\d{8}$/, ""))}</span>
                </div>` : ""}
                ${lastTool ? `<div class="meta-item">
                    <span class="meta-label">last</span>
                    <span class="meta-value">${escapeHtml(lastTool)}</span>
                </div>` : ""}
            </div>
        </div>
    `;
}

function renderProject(name, project) {
    const status = getProjectStatus(project);
    const activeSessions = project.active_sessions || [];
    const recentSessions = project.recent_sessions || [];

    const activeCount = activeSessions.length;
    const statusLabel = activeCount > 0
        ? `${activeCount} active`
        : "idle";

    let sessionsHtml = "";

    if (activeSessions.length > 0) {
        sessionsHtml += activeSessions.map(renderSession).join("");
    }

    if (recentSessions.length > 0) {
        sessionsHtml += `<div class="recent-label">Recent</div>`;
        sessionsHtml += recentSessions.map(renderSession).join("");
    }

    if (activeSessions.length === 0 && recentSessions.length === 0) {
        sessionsHtml = `<div class="empty-state">No sessions recorded</div>`;
    }

    return `
        <div class="project-card">
            <div class="project-header" onclick="this.parentElement.classList.toggle('collapsed')">
                <span class="project-name">${escapeHtml(name)}</span>
                <span class="project-status ${status}">${statusLabel}</span>
            </div>
            <div class="project-sessions">
                ${sessionsHtml}
            </div>
        </div>
    `;
}

function renderMonthly(monthly) {
    if (!monthly) return "";

    const monthName = new Date(monthly.month + "-01").toLocaleDateString("en-US", { month: "long", year: "numeric" });
    const totalIn = (monthly.input_tokens || 0) + (monthly.cache_read || 0);
    const totalOut = monthly.output_tokens || 0;
    const sessions = monthly.session_count || 0;
    const days = monthly.days || [];

    // Build bar chart
    const maxCost = Math.max(...days.map(d => d.cost), 0.01);
    let barsHtml = "";
    if (days.length > 0) {
        barsHtml = days.map(d => {
            const height = Math.max(2, (d.cost / maxCost) * 44);
            const label = `${d.date}: ${d.sessions} sessions, $${d.cost.toFixed(2)}`;
            return `<div class="daily-bar" style="height: ${height}px" title="${escapeHtml(label)}"></div>`;
        }).join("");
    }

    const firstDay = days.length > 0 ? days[0].date.split("-")[2] : "";
    const lastDay = days.length > 0 ? days[days.length - 1].date.split("-")[2] : "";

    return `
        <div class="monthly-card">
            <div class="monthly-header">
                <span class="monthly-title">${escapeHtml(monthName)}</span>
                <span class="monthly-cost">${formatCost(monthly.total_cost)}</span>
            </div>
            <div class="monthly-stats">
                <div class="monthly-stat">
                    <span class="stat-label">Sessions</span>
                    <span class="stat-value">${sessions}</span>
                </div>
                <div class="monthly-stat">
                    <span class="stat-label">Input tokens</span>
                    <span class="stat-value">${formatTokens(totalIn)}</span>
                </div>
                <div class="monthly-stat">
                    <span class="stat-label">Output tokens</span>
                    <span class="stat-value">${formatTokens(totalOut)}</span>
                </div>
            </div>
            ${days.length > 0 ? `
                <div class="daily-bar-chart">${barsHtml}</div>
                <div class="daily-bar-label">
                    <span>${firstDay}</span>
                    <span>daily cost</span>
                    <span>${lastDay}</span>
                </div>
            ` : ""}
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

async function refresh() {
    try {
        const res = await fetch(API_URL);
        if (!res.ok) return;
        const data = await res.json();

        // Update header
        const activeCount = data.summary.total_active || 0;
        const badge = document.getElementById("active-count");
        badge.textContent = `${activeCount} active`;
        badge.className = activeCount > 0 ? "badge" : "badge none";

        document.getElementById("cost-today").textContent =
            formatCost(data.summary.total_cost_today_usd) + " today";

        // Render monthly summary
        document.getElementById("monthly-summary").innerHTML = renderMonthly(data.monthly);

        // Render projects
        const dashboard = document.getElementById("dashboard");
        const projects = data.projects || {};
        const names = Object.keys(projects);

        // Sort: active projects first, then alphabetical
        names.sort((a, b) => {
            const aActive = (projects[a].active_sessions || []).length;
            const bActive = (projects[b].active_sessions || []).length;
            if (aActive !== bActive) return bActive - aActive;
            return a.localeCompare(b);
        });

        const html = `<div class="dashboard-grid">${names.map(n => renderProject(n, projects[n])).join("")}</div>`;
        dashboard.innerHTML = html;
    } catch (e) {
        // Silently retry on next interval
    }
}

// Initial load + polling
refresh();
setInterval(refresh, POLL_INTERVAL);
