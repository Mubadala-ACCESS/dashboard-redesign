(() => {
  const page = document.querySelector('.station-page');
  if (!page) return;

  const stationId = page.dataset.stationId;
  const stationTemplate = page.dataset.stationTemplate || 'standard';
  const state = {
    stationId,
    stationTemplate,
    period: '24H',
    aggregation: 'raw',
    selectedMetrics: [],
    selectedProfileMetrics: [],
    splitSensors: false,
    quickSplitSensors: false,
    availableMetrics: [],
    latestPayload: null,
    spectraPayload: null,
    spectraIndex: 0,
    advancedPanel: 'timeseries',
  };

  const emptyValue = '&mdash;';
  const trendColors = ['#5b21b6', '#0f766e', '#2563eb', '#d97706', '#be185d', '#64748b'];
  const sensorTrendColors = ['#0f766e', '#2563eb', '#d97706', '#be185d'];

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

  function isBuoyProfilePanel() {
    return state.stationTemplate === 'buoy' && state.advancedPanel === 'profiles';
  }

  function activeMetricKeys() {
    return isBuoyProfilePanel() ? state.selectedProfileMetrics : state.selectedMetrics;
  }

  function setActiveMetricKeys(keys) {
    if (isBuoyProfilePanel()) {
      state.selectedProfileMetrics = keys;
    } else {
      state.selectedMetrics = keys;
    }
  }

  function metricsForActivePanel(metrics) {
    if (state.stationTemplate !== 'buoy') return metrics || [];
    const profileKeys = new Set(['CTD_tmp', 'conductivity', 'O2', 'chlorophyll', 'salinity_practical', 'density']);
    return (metrics || []).filter((metric) => isBuoyProfilePanel() ? profileKeys.has(metric.key) : !profileKeys.has(metric.key));
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
    const toggle = document.getElementById('quick-sensor-toggle');
    const comparison = document.getElementById('quick-sensor-comparison');
    const trends = payload.trends || [];

    if (!panel || !root) return;
    root.innerHTML = '';
    if (comparison) comparison.innerHTML = '';

    if (!trends.length) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    if (toggle) {
      toggle.hidden = !payload.supports_sensor_trends;
      const input = document.getElementById('quick-split-sensors-toggle');
      if (input) input.checked = state.quickSplitSensors && !!payload.supports_sensor_trends;
    }
    if (context) {
      const sensorText = state.quickSplitSensors && payload.supports_sensor_trends ? ' with individual IoT sensor overlays' : '';
      context.textContent = `${payload.period || state.period} trends using ${aggregationLabel(payload.trend_aggregation)} values${sensorText}.`;
    }

    renderSensorComparison(trends, payload);

    trends.forEach((trend, index) => {
      const hostId = trendHostId(trend.metric, index);
      const unit = trend.unit ? ` ${trend.unit}` : '';
      const card = document.createElement('article');
      card.className = 'chart-card quick-trend-card';
      card.id = `quick-trend-card-${index}`;
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
      renderQuickTrendChart(hostId, trend, trendColors[index % trendColors.length], unit, state.quickSplitSensors && payload.supports_sensor_trends);
    });
  }

  function sensorGapStats(trend) {
    const sensors = (trend.sensor_trends || []).slice(0, 2);
    if (sensors.length < 2) return null;
    const seriesA = (sensors[0].series || []).filter((point) => point.y !== null && point.y !== undefined);
    const seriesB = (sensors[1].series || []).filter((point) => point.y !== null && point.y !== undefined);
    if (!seriesA.length || !seriesB.length) return null;

    const byTime = new Map(seriesB.map((point) => [point.x, point.y]));
    const gaps = [];
    seriesA.forEach((point) => {
      if (!byTime.has(point.x)) return;
      const a = Number(point.y);
      const b = Number(byTime.get(point.x));
      if (Number.isFinite(a) && Number.isFinite(b)) gaps.push(Math.abs(a - b));
    });

    const latestA = seriesA[seriesA.length - 1]?.y;
    const latestB = seriesB[seriesB.length - 1]?.y;
    const latestGap = latestA !== undefined && latestB !== undefined ? roundedGap(Math.abs(Number(latestA) - Number(latestB))) : null;
    const avgGap = gaps.length ? roundedGap(gaps.reduce((sum, value) => sum + value, 0) / gaps.length) : null;
    const maxGap = gaps.length ? roundedGap(Math.max(...gaps)) : null;

    return { sensors, latestA, latestB, latestGap, avgGap, maxGap };
  }

  function roundedGap(value) {
    return Number.isFinite(value) ? Number(value.toFixed(2)) : null;
  }

  function sensorCardValue(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Number(numeric.toFixed(2)) : value;
  }

  function renderSensorComparison(trends, payload) {
    const comparison = document.getElementById('quick-sensor-comparison');
    if (!comparison) return;

    const enabled = state.quickSplitSensors && payload.supports_sensor_trends;
    comparison.hidden = !enabled;
    comparison.innerHTML = '';
    if (!enabled) return;

    trends.forEach((trend, index) => {
      const stats = sensorGapStats(trend);
      if (!stats) return;
      const unit = trend.unit || '';
      const button = document.createElement('button');
      button.className = 'sensor-comparison-card';
      button.type = 'button';
      button.dataset.trendIndex = String(index);
      const sensorALabel = stats.sensors[0].label.split(' - ').pop() || 'Sensor 1';
      const sensorBLabel = stats.sensors[1].label.split(' - ').pop() || 'Sensor 2';
      button.innerHTML = `
        <span>${App.escapeHtml(trend.label)}</span>
        <div class="sensor-readout-row">
          <em><small>${App.escapeHtml(sensorALabel)}</small><b>${metricValue(sensorCardValue(stats.latestA), unit)}</b></em>
          <em><small>${App.escapeHtml(sensorBLabel)}</small><b>${metricValue(sensorCardValue(stats.latestB), unit)}</b></em>
        </div>
        <div class="sensor-comparison-card__stats">
          <em>Latest gap <b>${metricValue(stats.latestGap, unit)}</b></em>
          <em>Avg gap <b>${metricValue(stats.avgGap, unit)}</b></em>
          <em>Max gap <b>${metricValue(stats.maxGap, unit)}</b></em>
        </div>
      `;
      button.addEventListener('click', () => focusTrendCard(index));
      comparison.appendChild(button);
    });

    if (!comparison.children.length) comparison.hidden = true;
  }

  function focusTrendCard(index) {
    document.querySelectorAll('.quick-trend-card.is-focused').forEach((card) => card.classList.remove('is-focused'));
    const card = document.getElementById(`quick-trend-card-${index}`);
    if (!card) return;
    card.classList.add('is-focused');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => card.classList.remove('is-focused'), 2200);
  }

  function renderQuickTrendChart(hostId, trend, color, unit, showSensorTrends = false) {
    const host = document.getElementById(hostId);
    if (!host || !window.Plotly) return;
    const points = (trend.series || []).filter((point) => point.y !== null && point.y !== undefined);
    if (!points.length) {
      host.innerHTML = '<div class="empty-trend">No trend data for this display period.</div>';
      return;
    }

    const traces = [{
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      type: 'scatter',
      mode: 'lines',
      name: 'Station mean',
      line: { color, width: 2.4, shape: 'spline' },
      fill: 'tozeroy',
      fillcolor: 'rgba(91, 33, 182, 0.06)',
      hovertemplate: `%{x}<br>%{y:.2f}${unit}<extra></extra>`,
    }];

    if (showSensorTrends) {
      (trend.sensor_trends || []).forEach((sensorTrend, index) => {
        const sensorPoints = (sensorTrend.series || []).filter((point) => point.y !== null && point.y !== undefined);
        if (!sensorPoints.length) return;
        traces.push({
          x: sensorPoints.map((point) => point.x),
          y: sensorPoints.map((point) => point.y),
          type: 'scatter',
          mode: 'lines',
          name: sensorTrend.label.split(' - ').pop() || `Sensor ${index + 1}`,
          line: { color: sensorTrendColors[index % sensorTrendColors.length], width: 1.9, dash: index % 2 ? 'dot' : 'solid', shape: 'spline' },
          hovertemplate: `%{fullData.name}<br>%{x}<br>%{y:.2f}${unit}<extra></extra>`,
        });
      });
    }

    Plotly.newPlot(host, traces, {
      margin: { t: 10, r: 18, b: 38, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { gridcolor: 'rgba(91,101,118,.12)', tickfont: { size: 11 } },
      yaxis: { title: unit.trim(), gridcolor: 'rgba(91,101,118,.12)', zerolinecolor: 'rgba(91,101,118,.16)' },
      legend: { orientation: 'h', y: 1.14, x: 0, font: { size: 11 } },
      showlegend: traces.length > 1,
    }, { displaylogo: false, responsive: true });
  }

  function renderMetricSelector(metrics, activeMetrics = []) {
    const root = document.getElementById('metric-selector');
    root.innerHTML = '';
    const visibleMetrics = metricsForActivePanel(metrics);
    const selectedKeys = activeMetricKeys();
    const hadSelection = selectedKeys.length > 0;
    const activeKeys = new Set(activeMetrics.map((metric) => metric.key));
    visibleMetrics.forEach((metric, index) => {
      const id = `metric-${metric.key}`.replace(/[^a-zA-Z0-9_-]/g, '-');
      const checked = selectedKeys.includes(metric.key) || (!hadSelection && (activeKeys.has(metric.key) || (!activeKeys.size && index < 6)));
      if (checked && !selectedKeys.includes(metric.key)) selectedKeys.push(metric.key);
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
        setActiveMetricKeys(Array.from(root.querySelectorAll('input:checked')).map((item) => item.value));
        if (isBuoyProfilePanel()) {
          loadBuoyProfiles();
        } else {
          loadTimeseries();
        }
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
    if (!table) return;
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
    if (!card || !list) return;
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

  async function loadBuoyProfiles() {
    const panel = document.getElementById('buoy-profiles-panel');
    const grid = document.getElementById('buoy-profile-grid');
    if (!panel || !grid) return;
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/profiles`, window.location.origin);
    url.searchParams.set('period', state.period);
    if (state.selectedProfileMetrics.length) url.searchParams.set('metrics', state.selectedProfileMetrics.join(','));
    grid.innerHTML = '<article class="empty-state"><h2>Loading profiles</h2><p>Reading the selected depth profiles.</p></article>';
    const payload = await App.fetchJSON(url.toString());
    if (payload.available_metrics?.length && state.availableMetrics.length) {
      renderMetricSelector(state.availableMetrics, payload.metrics || []);
    }
    renderBuoyProfileCharts(payload);
  }

  function renderBuoyProfileCharts(payload) {
    const grid = document.getElementById('buoy-profile-grid');
    if (!grid) return;
    grid.innerHTML = '';
    if (!payload.charts?.length) {
      grid.innerHTML = `<article class="empty-state"><h2>No profile data</h2><p>${App.escapeHtml(payload.message || 'No profiles were available for this display period.')}</p></article>`;
      return;
    }

    payload.charts.forEach((chart, chartIndex) => {
      const card = document.createElement('article');
      card.className = 'chart-card';
      card.innerHTML = `
        <header>
          <div>
            <h3>${App.escapeHtml(chart.label)}</h3>
            <p>Latest profile ${App.escapeHtml(chart.latest_label || '')}</p>
          </div>
        </header>
        <div class="chart-host profile-chart-host"></div>
      `;
      grid.appendChild(card);
      renderBuoyProfileChart(card.querySelector('.profile-chart-host'), chart, chartIndex);
    });
  }

  function renderBuoyProfileChart(host, chart, chartIndex) {
    if (!host || !window.Plotly) return;
    const traces = (chart.profiles || []).map((profile, index) => ({
      x: profile.values || [],
      y: profile.depth || [],
      type: 'scatter',
      mode: 'lines+markers',
      name: profile.label || `Profile ${index + 1}`,
      line: { width: index === (chart.profiles.length - 1) ? 3 : 1.6, color: trendColors[(chartIndex + index) % trendColors.length] },
      marker: { size: index === (chart.profiles.length - 1) ? 5 : 3 },
      hovertemplate: `%{fullData.name}<br>${App.escapeHtml(chart.label)} %{x:.2f}<br>Depth %{y:.2f} m<extra></extra>`,
    }));
    Plotly.newPlot(host, traces, {
      margin: { t: 14, r: 22, b: 48, l: 66 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { title: chart.label, gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: 'Depth (m)', autorange: 'reversed', gridcolor: 'rgba(91,101,118,.12)' },
      legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 10 } },
      showlegend: traces.length > 1,
    }, { displaylogo: false, responsive: true });
  }

  function hasSpectraPanel() {
    return !!document.getElementById('fidas-spectra-panel');
  }

  function activeSpectraFrame() {
    const frames = state.spectraPayload?.frames || [];
    return frames[state.spectraIndex] || null;
  }

  function syncSpectraSlider() {
    const slider = document.getElementById('spectra-index-slider');
    const frames = state.spectraPayload?.frames || [];
    if (!slider) return;
    slider.max = String(Math.max(0, frames.length - 1));
    slider.value = String(Math.max(0, Math.min(state.spectraIndex, frames.length - 1)));
    slider.disabled = frames.length <= 1;
  }

  function setSpectraIndex(index) {
    const frames = state.spectraPayload?.frames || [];
    if (!frames.length) return;
    state.spectraIndex = Math.max(0, Math.min(index, frames.length - 1));
    syncSpectraSlider();
    renderFidasSpectra();
  }

  async function loadFidasSpectra(force = false) {
    if (!hasSpectraPanel()) return;
    if (!force && state.spectraPayload?.period === state.period) {
      renderFidasSpectra();
      return;
    }
    const host = document.getElementById('fidas-spectra-chart');
    if (host) host.innerHTML = '<div class="empty-trend">Loading spectra...</div>';
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/spectra`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('max_frames', '240');
    const payload = await App.fetchJSON(url.toString());
    const latestIndex = Number.isInteger(payload.latest_index) ? payload.latest_index : Math.max(0, (payload.frames || []).length - 1);
    state.spectraPayload = payload;
    state.spectraIndex = latestIndex;
    syncSpectraSlider();
    renderFidasSpectra();
  }

  function renderFidasSpectra() {
    const host = document.getElementById('fidas-spectra-chart');
    const label = document.getElementById('spectra-frame-label');
    if (!host || !window.Plotly) return;
    const frame = activeSpectraFrame();
    const sizes = (state.spectraPayload?.sizes || []).map((value) => Number(value));
    if (!frame || !sizes.length) {
      if (label) label.textContent = 'No spectra';
      host.innerHTML = '<div class="empty-trend">No spectra data for this display period.</div>';
      return;
    }

    const values = (frame.values || []).map((value) => {
      const numeric = Number(value);
      return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    });
    const length = Math.min(sizes.length, values.length);
    const x = sizes.slice(0, length);
    const y = values.slice(0, length);
    if (label) label.textContent = frame.label || frame.timestamp || 'Selected sample';
    host.innerHTML = '';

    Plotly.newPlot(host, [{
      x,
      y,
      type: 'scatter',
      mode: 'lines',
      name: 'Particle count',
      line: { color: '#5b21b6', width: 2.6, shape: 'hv' },
      hovertemplate: `Size %{x:.4f} ${App.escapeHtml(state.spectraPayload?.size_unit || '')}<br>Count %{y:.4f}<extra></extra>`,
    }], {
      margin: { t: 14, r: 24, b: 52, l: 68 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: {
        type: 'log',
        title: `Size (${state.spectraPayload?.size_unit || 'bin'})`,
        gridcolor: 'rgba(91,101,118,.14)',
      },
      yaxis: {
        type: 'log',
        title: state.spectraPayload?.spectra_unit || 'Particle count',
        gridcolor: 'rgba(91,101,118,.14)',
        range: [-3, 3],
      },
      showlegend: false,
    }, { displaylogo: false, responsive: true });
  }

  async function loadLatest() {
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/latest`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('include_trends', 'true');
    if (state.quickSplitSensors) url.searchParams.set('include_sensor_trends', 'true');
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
    const selectorMetrics = payload.available_metrics?.length ? payload.available_metrics : payload.metrics;
    if (selectorMetrics?.length && state.availableMetrics.length === 0) {
      state.availableMetrics = selectorMetrics;
      renderMetricSelector(selectorMetrics, payload.metrics || []);
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
        if (state.advancedPanel === 'spectra') {
          loadFidasSpectra(true);
        } else if (isBuoyProfilePanel()) {
          loadBuoyProfiles();
        } else {
          loadTimeseries();
        }
      });
    });
    document.getElementById('aggregation-select')?.addEventListener('change', (event) => {
      state.aggregation = event.target.value;
      if (!isBuoyProfilePanel()) loadTimeseries();
    });
    document.getElementById('split-sensors-toggle')?.addEventListener('change', (event) => {
      state.splitSensors = event.target.checked;
      loadTimeseries();
    });
    document.getElementById('quick-split-sensors-toggle')?.addEventListener('change', (event) => {
      state.quickSplitSensors = event.target.checked;
      loadLatest();
    });

    document.querySelectorAll('#view-tabs button').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('#view-tabs button').forEach((item) => item.classList.toggle('is-active', item === button));
        document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('is-active', panel.id === `${button.dataset.tab}-view`));
        window.requestAnimationFrame(resizeActiveCharts);
      });
    });

    document.querySelectorAll('#advanced-subtabs button').forEach((button) => {
      button.addEventListener('click', () => {
        setAdvancedPanel(button.dataset.advancedPanel || 'timeseries');
      });
    });

    document.querySelectorAll('[data-spectra-step]').forEach((button) => {
      button.addEventListener('click', () => {
        const step = Number(button.dataset.spectraStep || 0);
        setSpectraIndex(state.spectraIndex + step);
      });
    });

    document.getElementById('spectra-index-slider')?.addEventListener('input', (event) => {
      setSpectraIndex(Number(event.target.value));
    });

    document.getElementById('open-station-metadata')?.addEventListener('click', () => App.showMetadata(state.stationId));
    document.getElementById('open-station-metadata-advanced')?.addEventListener('click', () => App.showMetadata(state.stationId));
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

  function setAdvancedPanel(panelName) {
    state.advancedPanel = panelName;
    document.querySelectorAll('#advanced-subtabs button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.advancedPanel === panelName);
    });
    document.querySelectorAll('#advanced-view .advanced-panel[data-advanced-panel]').forEach((panel) => {
      const isActive = panel.dataset.advancedPanel === panelName;
      panel.classList.toggle('is-active', isActive);
      panel.hidden = !isActive;
    });
    if (state.stationTemplate === 'buoy' && state.availableMetrics.length) {
      renderMetricSelector(state.availableMetrics, []);
    }
    if (panelName === 'spectra') {
      loadFidasSpectra().then(() => window.requestAnimationFrame(resizeActiveCharts));
    } else if (panelName === 'profiles') {
      loadBuoyProfiles().then(() => window.requestAnimationFrame(resizeActiveCharts));
    } else {
      if (panelName === 'atmospheric') loadTimeseries();
      window.requestAnimationFrame(resizeActiveCharts);
    }
  }

  function resizeActiveCharts() {
    if (!window.Plotly) return;
    document.querySelectorAll('.tab-panel.is-active .chart-host').forEach((host) => {
      if (host.data) Plotly.Plots.resize(host);
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
