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

  function unitFromLabel(label = '') {
    const match = label.match(/\(([^)]+)\)/);
    return match ? match[1] : '';
  }

  function makeCard(card, primaryAqi) {
    const unit = card.unit ? ` ${card.unit}` : '';
    const aqiTag = card.aqi || (!card.aqi && primaryAqi && ['PM2.5', 'PM10'].includes(card.canonical_label) ? primaryAqi : null);
    return `
      <article class="metric-card">
        <span>${App.escapeHtml(card.label)}</span>
        <strong>${card.latest ?? '—'}${unit}</strong>
        <small>Mean ${card.mean ?? '—'} · Max ${card.max ?? '—'}</small>
        ${aqiTag ? `<small><strong>${App.escapeHtml(aqiTag.category)}</strong> · AQI ${aqiTag.aqi}</small>` : ''}
      </article>
    `;
  }

  function updateLatestCards(payload) {
    state.latestPayload = payload;
    const container = document.getElementById('latest-cards');
    container.innerHTML = payload.cards.map((card) => makeCard(card, payload.primary_aqi)).join('');
    const freshness = payload.station.freshness;
    const freshnessText = freshness.is_stale
      ? `Latest reading is stale. Last update: ${freshness.last_update}.`
      : `Fresh data available. Last update: ${freshness.last_update}.`;
    document.getElementById('station-freshness-text').textContent = freshnessText;
    document.getElementById('quick-interpretation').textContent = payload.primary_aqi
      ? `${payload.primary_aqi.category}. ${payload.primary_aqi.health_message}`
      : 'This station does not currently expose particulate AQI-style interpretation from the selected latest metrics.';

    const events = document.getElementById('event-markers');
    if (!payload.events.length) {
      events.innerHTML = '<div class="event-chip"><strong>No active event markers</strong><small>Recent data did not trigger heat, rain, or particulate event heuristics.</small></div>';
      return;
    }
    events.innerHTML = payload.events.map((event) => `
      <article class="event-chip">
        <strong>${App.escapeHtml(event.type)}</strong>
        <small>${App.escapeHtml(event.label)} · ${App.escapeHtml(event.timestamp)} · ${event.value}</small>
      </article>
    `).join('');
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
        <span>Latest ${chart.summary.latest ?? '—'}</span>
        <span>Mean ${chart.summary.mean ?? '—'}</span>
        <span>Max ${chart.summary.max ?? '—'}</span>
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
        ${headers.map((metric) => `<td>${row[metric.key] ?? '—'}</td>`).join('')}
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
        <strong>${App.escapeHtml(profile.label)} · ${App.escapeHtml(profile.timestamp)}</strong>
        <code>depth: ${App.escapeHtml(JSON.stringify(profile.depth || []))}\nvalues: ${App.escapeHtml(JSON.stringify(profile.values || []))}</code>
      </article>
    `).join('');
  }

  async function loadLatest() {
    const payload = await App.fetchJSON(`/api/stations/${encodeURIComponent(state.stationId)}/latest`);
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
        loadTimeseries();
      });
    });
    document.getElementById('aggregation-select').addEventListener('change', (event) => {
      state.aggregation = event.target.value;
      loadTimeseries();
    });
    document.getElementById('split-sensors-toggle').addEventListener('change', (event) => {
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
