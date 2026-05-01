(() => {
  const page = document.querySelector('.station-page');
  if (!page) return;

  const stationId = page.dataset.stationId;
  const state = {
    stationId,
    period: '24H',
    aggregation: 'raw',
    selectedMetrics: [],
    splitSensors: false,
    availableMetrics: [],
    latestPayload: null,
  };

  const emptyValue = '&mdash;';
  const trendColors = ['#5b21b6', '#0f766e', '#2563eb', '#d97706', '#be185d', '#64748b'];

  function displayValue(value) {
    return value === null || value === undefined || value === '' ? emptyValue : App.escapeHtml(String(value));
  }

  function metricValue(value, unit = '') {
    if (value === null || value === undefined || value === '') return emptyValue;
    return `${displayValue(value)}${unit ? ` ${App.escapeHtml(unit)}` : ''}`;
  }

  function trendHostId(metric, index) {
    return `quick-trend-${index}-${String(metric).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  }

  function aggregationLabel(value) {
    return {
      raw: 'raw samples',
      '15m': '15 min',
      '1h': 'hourly',
      '6h': '6 hour',
      '1d': 'daily',
    }[value] || value || 'trend';
  }

  function makeCard(card) {
    const unit = card.unit || '';
    return `
      <article class="metric-card">
        <div class="metric-card__top">
          <span>${App.escapeHtml(card.label)}</span>
          <small>${App.escapeHtml(state.period)}</small>
        </div>
        <div class="metric-current">
          <small>Current</small>
          <strong>${metricValue(card.latest, unit)}</strong>
        </div>
        <div class="metric-stat-grid">
          <div>
            <small>Mean</small>
            <b>${displayValue(card.mean)}</b>
          </div>
          <div>
            <small>Min</small>
            <b>${displayValue(card.min)}</b>
          </div>
          <div>
            <small>Max</small>
            <b>${displayValue(card.max)}</b>
          </div>
        </div>
      </article>
    `;
  }

  function updateLatestCards(payload) {
    state.latestPayload = payload;
    const period = payload.period || state.period;
    const label = document.getElementById('stats-period-label');
    const container = document.getElementById('latest-cards');

    if (label) label.textContent = period;
    if (!payload.cards?.length) {
      container.innerHTML = '<article class="empty-state"><h2>No current readings</h2><p>No data was available for the selected display period.</p></article>';
      renderQuickTrends(payload);
      return;
    }

    container.innerHTML = payload.cards.map((card) => makeCard(card)).join('');
    renderQuickTrends(payload);
  }

  function renderQuickTrends(payload) {
    const panel = document.getElementById('quick-trend-panel');
    const root = document.getElementById('quick-trends');
    const context = document.getElementById('quick-trend-context');
    const trends = payload.trends || [];

    if (!panel || !root) return;
    root.innerHTML = '';

    if (!trends.length) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    if (context) {
      context.textContent = `${payload.period || state.period} trends using ${aggregationLabel(payload.trend_aggregation)} values.`;
    }

    trends.forEach((trend, index) => {
      const hostId = trendHostId(trend.metric, index);
      const unit = trend.unit ? ` ${trend.unit}` : '';
      const card = document.createElement('article');
      card.className = 'chart-card quick-trend-card';
      card.innerHTML = `
        <header>
          <div>
            <h3>${App.escapeHtml(trend.label)}</h3>
            <p>Current ${metricValue(trend.summary?.latest, trend.unit)} &middot; Mean ${displayValue(trend.summary?.mean)} &middot; Min ${displayValue(trend.summary?.min)} &middot; Max ${displayValue(trend.summary?.max)}</p>
          </div>
        </header>
        <div id="${hostId}" class="chart-host quick-trend-host"></div>
      `;
      root.appendChild(card);
      renderQuickTrendChart(hostId, trend, trendColors[index % trendColors.length], unit);
    });
  }

  function renderQuickTrendChart(hostId, trend, color, unit) {
    const host = document.getElementById(hostId);
    if (!host || !window.Plotly) return;
    const points = (trend.series || []).filter((point) => point.y !== null && point.y !== undefined);
    if (!points.length) {
      host.innerHTML = '<div class="empty-trend">No trend data for this display period.</div>';
      return;
    }

    Plotly.newPlot(host, [{
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      type: 'scatter',
      mode: 'lines',
      line: { color, width: 2.4, shape: 'spline' },
      fill: 'tozeroy',
      fillcolor: 'rgba(91, 33, 182, 0.06)',
      hovertemplate: `%{x}<br>%{y:.2f}${unit}<extra></extra>`,
    }], {
      margin: { t: 10, r: 18, b: 38, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { gridcolor: 'rgba(91,101,118,.12)', tickfont: { size: 11 } },
      yaxis: { title: unit.trim(), gridcolor: 'rgba(91,101,118,.12)', zerolinecolor: 'rgba(91,101,118,.16)' },
      showlegend: false,
    }, { displaylogo: false, responsive: true });
  }

  function renderMetricSelector(metrics) {
    const root = document.getElementById('metric-selector');
    root.innerHTML = '';
    metrics.forEach((metric, index) => {
      const id = `metric-${metric.key}`.replace(/[^a-zA-Z0-9_-]/g, '-');
      const checked = state.selectedMetrics.includes(metric.key) || (state.selectedMetrics.length === 0 && index < 6);
      if (checked && !state.selectedMetrics.includes(metric.key)) state.selectedMetrics.push(metric.key);
      const label = document.createElement('label');
      label.className = 'metric-option';
      label.innerHTML = `
        <input type="checkbox" id="${id}" value="${App.escapeHtml(metric.key)}" ${checked ? 'checked' : ''} />
        <div>
          <strong>${App.escapeHtml(metric.label)}</strong>
          <div class="small-note">${App.escapeHtml(metric.key)}</div>
        </div>
      `;
      root.appendChild(label);
    });
    root.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        state.selectedMetrics = Array.from(root.querySelectorAll('input:checked')).map((item) => item.value);
        loadTimeseries();
      });
    });
  }

  function renderChart(chart, events) {
    const card = document.createElement('article');
    card.className = 'chart-card';
    card.innerHTML = `
      <h3>${App.escapeHtml(chart.label)}</h3>
      <div class="chart-meta">
        <span>Current ${displayValue(chart.summary.latest)}</span>
        <span>Mean ${displayValue(chart.summary.mean)}</span>
        <span>Min ${displayValue(chart.summary.min)}</span>
        <span>Max ${displayValue(chart.summary.max)}</span>
      </div>
      <div class="chart-host"></div>
    `;
    const host = card.querySelector('.chart-host');
    const x = chart.series.map((point) => point.x);
    const y = chart.series.map((point) => point.y);
    const shapes = [];
    const annotations = [];
    if (chart.thresholds?.bands) {
      chart.thresholds.bands.forEach((band) => {
        shapes.push({
          type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: band.min, y1: band.max,
          fillcolor: band.color, line: { width: 0 }, layer: 'below'
        });
        shapes.push({
          type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: band.max, y1: band.max,
          line: { color: band.line, width: 1, dash: 'dot' }, layer: 'below'
        });
      });
    }
    events.filter((event) => event.metric === chart.metric).forEach((event) => {
      shapes.push({
        type: 'line', xref: 'x', x0: event.timestamp, x1: event.timestamp, yref: 'paper', y0: 0, y1: 1,
        line: { color: '#7c3aed', width: 1, dash: 'dot' }
      });
      annotations.push({ x: event.timestamp, y: chart.summary.max ?? 0, text: event.type, showarrow: true, arrowhead: 2, ax: 0, ay: -30, font: { size: 11 } });
    });
    Plotly.newPlot(host, [
      {
        x,
        y,
        type: 'scatter',
        mode: 'lines+markers',
        line: { width: 2.2, color: '#4c1d95' },
        marker: { size: 4, color: '#4c1d95' },
        hovertemplate: '%{x}<br>%{y}<extra></extra>'
      }
    ], {
      margin: { t: 18, r: 18, b: 42, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { title: 'GST', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: chart.label, gridcolor: 'rgba(91,101,118,.12)' },
      shapes,
      annotations,
      showlegend: false,
    }, { displaylogo: false, responsive: true });
    return card;
  }

  function updateTable(payload) {
    const table = document.getElementById('raw-data-table');
    const headers = payload.metrics.slice(0, 6);
    table.querySelector('thead').innerHTML = `
      <tr>
        <th>Timestamp</th>
        ${headers.map((metric) => `<th>${App.escapeHtml(metric.label)}</th>`).join('')}
      </tr>
    `;
    table.querySelector('tbody').innerHTML = payload.table.map((row) => `
      <tr>
        <td>${App.escapeHtml(row.timestamp)}</td>
        ${headers.map((metric) => `<td>${row[metric.key] ?? emptyValue}</td>`).join('')}
      </tr>
    `).join('');
  }

  function updateBuoyProfiles(payload) {
    const card = document.getElementById('buoy-profile-card');
    const list = document.getElementById('buoy-profile-list');
    if (!payload.profiles?.length) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    list.innerHTML = payload.profiles.map((profile) => `
      <article class="profile-item">
        <strong>${App.escapeHtml(profile.label)} &middot; ${App.escapeHtml(profile.timestamp)}</strong>
        <code>depth: ${App.escapeHtml(JSON.stringify(profile.depth || []))}\nvalues: ${App.escapeHtml(JSON.stringify(profile.values || []))}</code>
      </article>
    `).join('');
  }

  async function loadLatest() {
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/latest`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('include_trends', 'true');
    const payload = await App.fetchJSON(url.toString());
    updateLatestCards(payload);
  }

  async function loadTimeseries() {
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/timeseries`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('aggregation', state.aggregation);
    url.searchParams.set('split_sensors', state.splitSensors ? 'true' : 'false');
    if (state.selectedMetrics.length) url.searchParams.set('metrics', state.selectedMetrics.join(','));
    const payload = await App.fetchJSON(url.toString());
    if (payload.metrics?.length && state.availableMetrics.length === 0) {
      state.availableMetrics = payload.metrics;
      renderMetricSelector(payload.metrics);
    }
    const grid = document.getElementById('chart-grid');
    grid.innerHTML = '';
    if (!payload.charts?.length) {
      grid.innerHTML = `<article class="empty-state"><h2>No chart data for this view</h2><p>${App.escapeHtml(payload.message || 'No data available for the current selection.')}</p></article>`;
      updateTable({ metrics: [], table: [] });
      updateBuoyProfiles(payload);
      return;
    }
    payload.charts.forEach((chart) => {
      grid.appendChild(renderChart(chart, payload.events || []));
    });
    updateTable(payload);
    updateBuoyProfiles(payload);
  }

  function wireControls() {
    document.querySelectorAll('#period-buttons button').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('#period-buttons button').forEach((item) => item.classList.toggle('is-active', item === button));
        state.period = button.dataset.period;
        const label = document.getElementById('stats-period-label');
        if (label) label.textContent = state.period;
        loadLatest();
        loadTimeseries();
      });
    });
    document.getElementById('aggregation-select')?.addEventListener('change', (event) => {
      state.aggregation = event.target.value;
      loadTimeseries();
    });
    document.getElementById('split-sensors-toggle')?.addEventListener('change', (event) => {
      state.splitSensors = event.target.checked;
      loadTimeseries();
    });

    document.querySelectorAll('#view-tabs button').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('#view-tabs button').forEach((item) => item.classList.toggle('is-active', item === button));
        document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('is-active', panel.id === `${button.dataset.tab}-view`));
      });
    });

    document.getElementById('open-station-metadata')?.addEventListener('click', () => App.showMetadata(state.stationId));
    document.getElementById('open-station-metadata-inline')?.addEventListener('click', () => App.showMetadata(state.stationId));

    document.getElementById('download-csv')?.addEventListener('click', () => {
      const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/export.csv`, window.location.origin);
      url.searchParams.set('period', state.period);
      url.searchParams.set('aggregation', state.aggregation);
      url.searchParams.set('split_sensors', state.splitSensors ? 'true' : 'false');
      if (state.selectedMetrics.length) url.searchParams.set('metrics', state.selectedMetrics.join(','));
      window.open(url.toString(), '_blank');
    });
    document.getElementById('download-json')?.addEventListener('click', () => {
      const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/export.json`, window.location.origin);
      url.searchParams.set('period', state.period);
      url.searchParams.set('aggregation', state.aggregation);
      url.searchParams.set('split_sensors', state.splitSensors ? 'true' : 'false');
      if (state.selectedMetrics.length) url.searchParams.set('metrics', state.selectedMetrics.join(','));
      window.open(url.toString(), '_blank');
    });
  }

  async function init() {
    wireControls();
    await loadLatest();
    await loadTimeseries();
  }

  init().catch((error) => {
    console.error(error);
  });
})();
