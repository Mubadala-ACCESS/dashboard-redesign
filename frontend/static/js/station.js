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
    metricsTouched: false,
    profileMetricsTouched: false,
    splitSensors: false,
    quickSplitSensors: false,
    availableMetrics: [],
    latestPayload: null,
    timeseriesPayload: null,
    profilePayload: null,
    spectraPayload: null,
    spectraIndex: 0,
    advancedPanel: 'timeseries',
    fidasClean: false,
    latestRequestId: 0,
    timeseriesRequestId: 0,
    profileRequestId: 0,
    latestCache: new Map(),
    timeseriesCache: new Map(),
    profileCache: new Map(),
    spectraCache: new Map(),
  };

  const emptyValue = '&mdash;';
  const defaultSelectedMetricLimit = 3;
  const trendColors = ['#5b21b6', '#0f766e', '#2563eb', '#d97706', '#be185d', '#64748b'];
  const sensorTrendColors = ['#0f766e', '#2563eb', '#d97706', '#be185d'];
  const maxClientCacheEntries = 24;

  function rememberPayload(cache, key, payload) {
    if (!cache || !key) return;
    if (cache.has(key)) cache.delete(key);
    cache.set(key, payload);
    while (cache.size > maxClientCacheEntries) {
      cache.delete(cache.keys().next().value);
    }
  }

  function cachedPayload(cache, key) {
    return cache?.get(key) || null;
  }

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

  function isFidasStation() {
    return state.stationTemplate === 'fidas';
  }

  function activeMetricKeys() {
    return isBuoyProfilePanel() ? state.selectedProfileMetrics : state.selectedMetrics;
  }

  function setActiveMetricKeys(keys) {
    const uniqueKeys = Array.from(new Set((keys || []).filter(Boolean)));
    if (isBuoyProfilePanel()) {
      state.selectedProfileMetrics = uniqueKeys;
    } else {
      state.selectedMetrics = uniqueKeys;
    }
  }

  function checkedMetricKeys(root) {
    return Array.from(root.querySelectorAll('input:checked')).map((item) => item.value);
  }

  function syncClickedMetricOrder(root, clickedKey, isChecked) {
    const checked = new Set(checkedMetricKeys(root));
    const previous = activeMetricKeys();
    if (isChecked) {
      const next = [
        clickedKey,
        ...previous.filter((key) => key !== clickedKey && checked.has(key)),
        ...Array.from(checked).filter((key) => key !== clickedKey && !previous.includes(key)),
      ];
      setActiveMetricKeys(next);
      return;
    }
    setActiveMetricKeys(previous.filter((key) => key !== clickedKey && checked.has(key)));
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

  function metricQueryValue(keys) {
    const selected = (keys || []).filter(Boolean);
    return selected.length ? selected.join('|') : '__none__';
  }

  function activeMetricsTouched() {
    return isBuoyProfilePanel() ? state.profileMetricsTouched : state.metricsTouched;
  }

  function setActiveMetricsTouched(value) {
    if (isBuoyProfilePanel()) {
      state.profileMetricsTouched = value;
    } else {
      state.metricsTouched = value;
    }
  }

  function splitSensorLabel(label = '') {
    const parts = String(label).split(' - ');
    if (parts.length < 2) {
      return { baseLabel: label, sensorLabel: '' };
    }
    return {
      baseLabel: parts.slice(0, -1).join(' - '),
      sensorLabel: parts[parts.length - 1],
    };
  }

  function lastNumericValue(series = []) {
    for (let index = series.length - 1; index >= 0; index -= 1) {
      const value = Number(series[index]?.y);
      if (Number.isFinite(value)) return value;
    }
    return null;
  }

  function roundStat(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Number(numeric.toFixed(2)) : null;
  }

  function groupedSensorSummary(sensorCharts) {
    const values = [];
    const latestValues = [];
    sensorCharts.forEach((chart) => {
      (chart.series || []).forEach((point) => {
        const value = Number(point.y);
        if (Number.isFinite(value)) values.push(value);
      });
      const latest = lastNumericValue(chart.series || []);
      if (latest !== null) latestValues.push(latest);
    });
    const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const latest = latestValues.length ? latestValues.reduce((sum, value) => sum + value, 0) / latestValues.length : null;
    return {
      min: values.length ? roundStat(Math.min(...values)) : null,
      max: values.length ? roundStat(Math.max(...values)) : null,
      mean: roundStat(mean),
      latest: roundStat(latest),
    };
  }

  function groupAdvancedSensorCharts(charts, payload) {
    if (!state.splitSensors || payload.station?.device_type !== 'IoTBox') return charts;
    const groups = [];
    const byKey = new Map();
    (charts || []).forEach((chart) => {
      const labels = splitSensorLabel(chart.label);
      const groupKey = `${chart.canonical_label || labels.baseLabel}:${labels.baseLabel}`;
      if (!byKey.has(groupKey)) {
        const group = {
          ...chart,
          label: labels.baseLabel,
          summary: {},
          sensorCharts: [],
        };
        byKey.set(groupKey, group);
        groups.push(group);
      }
      const group = byKey.get(groupKey);
      group.sensorCharts.push({
        ...chart,
        sensorLabel: labels.sensorLabel || `Sensor ${group.sensorCharts.length + 1}`,
      });
    });
    groups.forEach((group) => {
      group.summary = groupedSensorSummary(group.sensorCharts);
      group.series = group.sensorCharts[0]?.series || [];
      group.metric = group.sensorCharts[0]?.metric || group.metric;
    });
    return groups;
  }

  function chartMetaHtml(chart) {
    if (!chart.sensorCharts?.length) {
      return `
        <span>Current ${displayValue(chart.summary.latest)}</span>
        <span>Mean ${displayValue(chart.summary.mean)}</span>
        <span>Min ${displayValue(chart.summary.min)}</span>
        <span>Max ${displayValue(chart.summary.max)}</span>
      `;
    }

    const latest = chart.sensorCharts
      .map((sensorChart) => ({
        label: sensorChart.sensorLabel,
        value: roundStat(lastNumericValue(sensorChart.series || [])),
      }))
      .filter((item) => item.value !== null);
    const gap = latest.length >= 2 ? roundStat(Math.abs(latest[0].value - latest[1].value)) : null;
    return `
      <span>Current mean ${displayValue(chart.summary.latest)}</span>
      <span>Mean ${displayValue(chart.summary.mean)}</span>
      ${latest.map((item) => `<span>${App.escapeHtml(item.label)} ${displayValue(item.value)}</span>`).join('')}
      ${gap !== null ? `<span>Gap ${displayValue(gap)}</span>` : ''}
    `;
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
    const selectedKeys = [...activeMetricKeys()];
    const hadSelection = selectedKeys.length > 0 || activeMetricsTouched();
    const activeKeys = new Set(activeMetrics.map((metric) => metric.key));
    visibleMetrics.forEach((metric, index) => {
      const id = `metric-${metric.key}`.replace(/[^a-zA-Z0-9_-]/g, '-');
      const checked = selectedKeys.includes(metric.key) || (!hadSelection && (activeKeys.has(metric.key) || (!activeKeys.size && index < defaultSelectedMetricLimit)));
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
    setActiveMetricKeys(selectedKeys);
    root.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.addEventListener('change', () => {
        setActiveMetricsTouched(true);
        syncClickedMetricOrder(root, checkbox.value, checkbox.checked);
        if (isBuoyProfilePanel()) {
          loadBuoyProfiles();
        } else {
          loadTimeseries();
        }
      });
    });
  }

  const deferredCharts = new WeakMap();
  const chartObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const payload = deferredCharts.get(entry.target);
      if (!payload) return;
      chartObserver.unobserve(entry.target);
      deferredCharts.delete(entry.target);
      plotAdvancedChart(entry.target, payload.chart, payload.events);
    });
  }, { rootMargin: '700px 0px' }) : null;

  function renderChart(chart, events) {
    const card = document.createElement('article');
    card.className = 'chart-card';
    card.innerHTML = `
      <h3>${App.escapeHtml(chart.label)}</h3>
      <div class="chart-meta">
        ${chartMetaHtml(chart)}
      </div>
      <div class="chart-host"></div>
    `;
    const host = card.querySelector('.chart-host');
    if (chartObserver) {
      deferredCharts.set(host, { chart, events });
      chartObserver.observe(host);
    } else {
      window.requestAnimationFrame(() => plotAdvancedChart(host, chart, events));
    }
    return card;
  }

  function plotAdvancedChart(host, chart, events) {
    if (!host || !window.Plotly) return;
    if (!host.isConnected) {
      window.requestAnimationFrame(() => plotAdvancedChart(host, chart, events));
      return;
    }
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
    const eventMetrics = new Set(chart.sensorCharts?.map((sensorChart) => sensorChart.metric) || [chart.metric]);
    events.filter((event) => eventMetrics.has(event.metric)).forEach((event) => {
      shapes.push({
        type: 'line', xref: 'x', x0: event.timestamp, x1: event.timestamp, yref: 'paper', y0: 0, y1: 1,
        line: { color: '#7c3aed', width: 1, dash: 'dot' }
      });
      annotations.push({ x: event.timestamp, y: chart.summary.max ?? 0, text: event.type, showarrow: true, arrowhead: 2, ax: 0, ay: -30, font: { size: 11 } });
    });
    const hostWidth = Math.max(320, Math.floor(host.getBoundingClientRect().width || host.clientWidth || 0));
    const traceSource = chart.sensorCharts?.length ? chart.sensorCharts : [chart];
    const traces = traceSource.map((sourceChart, index) => ({
      x: (sourceChart.series || []).map((point) => point.x),
      y: (sourceChart.series || []).map((point) => point.y),
      type: 'scatter',
      mode: (sourceChart.series || []).length > 220 ? 'lines' : 'lines+markers',
      name: sourceChart.sensorLabel || sourceChart.label || chart.label,
      line: {
        width: chart.sensorCharts?.length ? 2 : 2.2,
        color: chart.sensorCharts?.length ? sensorTrendColors[index % sensorTrendColors.length] : '#4c1d95',
        dash: index % 2 ? 'dot' : 'solid',
      },
      marker: {
        size: 4,
        color: chart.sensorCharts?.length ? sensorTrendColors[index % sensorTrendColors.length] : '#4c1d95',
      },
      hovertemplate: '%{fullData.name}<br>%{x}<br>%{y}<extra></extra>',
    }));
    Plotly.newPlot(host, traces, {
      margin: { t: 18, r: 18, b: 42, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      autosize: true,
      width: hostWidth,
      xaxis: { title: 'GST', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: chart.label, gridcolor: 'rgba(91,101,118,.12)' },
      shapes,
      annotations,
      legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 11 } },
      showlegend: traces.length > 1,
    }, { displaylogo: false, responsive: true }).then(() => Plotly.Plots.resize(host));
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

  function rawDataCell(value) {
    if (value === null || value === undefined || value === '') return emptyValue;
    if (typeof value === 'number') return App.escapeHtml(String(roundStat(value) ?? value));
    return App.escapeHtml(String(value));
  }

  function rowsFromTimeseries(payload) {
    const charts = payload?.charts || [];
    const columns = [
      { key: 'timestamp', label: 'Timestamp' },
      ...charts.map((chart) => ({ key: chart.metric, label: chart.label })),
    ];
    const byTime = new Map();
    charts.forEach((chart) => {
      (chart.series || []).forEach((point) => {
        if (!byTime.has(point.x)) byTime.set(point.x, { timestamp: point.x });
        byTime.get(point.x)[chart.metric] = point.y;
      });
    });
    const rows = Array.from(byTime.values())
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 250);
    return { columns, rows, count: byTime.size };
  }

  function rowsFromProfiles(payload) {
    const columns = [
      { key: 'metric', label: 'Metric' },
      { key: 'timestamp', label: 'Timestamp' },
      { key: 'depth', label: 'Depth (m)' },
      { key: 'value', label: 'Value' },
    ];
    const rows = [];
    (payload?.charts || []).forEach((chart) => {
      (chart.profiles || []).forEach((profile) => {
        (profile.depth || []).forEach((depth, index) => {
          rows.push({
            metric: chart.label,
            timestamp: profile.timestamp || profile.label,
            depth,
            value: profile.values?.[index],
          });
        });
      });
    });
    return { columns, rows: rows.slice(0, 300), count: rows.length };
  }

  function rowsFromSpectra(payload) {
    const frame = activeSpectraFrame();
    const columns = [
      { key: 'size', label: `Size (${payload?.size_unit || 'bin'})` },
      { key: 'count', label: payload?.spectra_unit || 'Particle count' },
    ];
    const rows = (payload?.sizes || []).map((size, index) => ({
      size,
      count: frame?.values?.[index],
    })).filter((row) => row.count !== undefined);
    return { columns, rows, count: rows.length };
  }

  function buildRawDataModal(title, context, tableData) {
    const rows = tableData.rows || [];
    const columns = tableData.columns || [];
    const body = rows.length ? rows.map((row) => `
      <tr>
        ${columns.map((column) => `<td>${rawDataCell(row[column.key])}</td>`).join('')}
      </tr>
    `).join('') : `
      <tr><td colspan="${Math.max(1, columns.length)}">${emptyValue}</td></tr>
    `;
    return `
      <article class="modal-panel raw-data-modal">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Raw data</span>
            <h2>${App.escapeHtml(title)}</h2>
            <p>${App.escapeHtml(context)}</p>
          </div>
          <button class="ghost-button" data-close-modal>Close</button>
        </header>
        <div class="raw-data-summary">
          <span>Showing ${App.escapeHtml(String(rows.length))} of ${App.escapeHtml(String(tableData.count || rows.length))} rows</span>
          <span>${App.escapeHtml(state.period)} - ${App.escapeHtml(aggregationLabel(state.aggregation))}</span>
        </div>
        <div class="metadata-table raw-data-table">
          <table>
            <thead>
              <tr>${columns.map((column) => `<th>${App.escapeHtml(column.label)}</th>`).join('')}</tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
        <footer class="modal-actions">
          <button class="ghost-button" data-close-modal>Done</button>
        </footer>
      </article>
    `;
  }

  async function showRawData() {
    if (state.advancedPanel === 'profiles') {
      if (!state.profilePayload) await loadBuoyProfiles();
      App.openModal(buildRawDataModal('Buoy profiles', 'Depth-profile values for the current display period.', rowsFromProfiles(state.profilePayload)));
      return;
    }
    if (state.advancedPanel === 'spectra') {
      if (!state.spectraPayload) await loadFidasSpectra();
      App.openModal(buildRawDataModal('Fidas spectra', 'Particle-size bins for the selected spectra sample.', rowsFromSpectra(state.spectraPayload)));
      return;
    }
    if (!state.timeseriesPayload) await loadTimeseries();
    App.openModal(buildRawDataModal('Advanced time series', 'Chart values for the current advanced selection.', rowsFromTimeseries(state.timeseriesPayload)));
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

  function clearChartGrid(grid, loadingHtml = '') {
    if (!grid) return;
    if (chartObserver) {
      grid.querySelectorAll('.chart-host').forEach((host) => chartObserver.unobserve(host));
    }
    grid.innerHTML = loadingHtml;
  }

  async function loadBuoyProfiles() {
    const panel = document.getElementById('buoy-profiles-panel');
    const grid = document.getElementById('buoy-profile-grid');
    if (!panel || !grid) return;
    const requestId = ++state.profileRequestId;
    const key = [state.period, metricQueryValue(state.selectedProfileMetrics)].join('|');
    const cached = cachedPayload(state.profileCache, key);
    if (cached) {
      state.profilePayload = cached;
      renderBuoyProfileCharts(cached);
      return cached;
    }
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/profiles`, window.location.origin);
    url.searchParams.set('period', state.period);
    if (state.selectedProfileMetrics.length || state.profileMetricsTouched) url.searchParams.set('metrics', metricQueryValue(state.selectedProfileMetrics));
    grid.innerHTML = '<article class="empty-state"><h2>Loading profiles</h2><p>Reading the selected depth profiles.</p></article>';
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.profileRequestId) return;
    state.profilePayload = payload;
    rememberPayload(state.profileCache, key, payload);
    if (payload.available_metrics?.length && state.availableMetrics.length) {
      renderMetricSelector(state.availableMetrics, payload.metrics || []);
    }
    renderBuoyProfileCharts(payload);
    return payload;
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
            <p>${App.escapeHtml(payload.effective_period || payload.period || state.period)} heatmap · Latest profile ${App.escapeHtml(chart.latest_label || '')}</p>
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
    const profiles = chart.profiles || [];
    const depthSource = profiles.find((profile) => Array.isArray(profile.depth) && profile.depth.length);
    const depths = (depthSource?.depth || [])
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value));
    const times = profiles.map((profile, index) => profile.label || profile.timestamp || `Profile ${index + 1}`);
    const heatmapValues = depths.map((_, depthIndex) => (
      profiles.map((profile) => {
        const numeric = Number(profile.values?.[depthIndex]);
        return Number.isFinite(numeric) && numeric !== 0 ? numeric : null;
      })
    ));
    const finiteValues = heatmapValues.flat().filter((value) => Number.isFinite(value));

    if (!depths.length || !times.length || !finiteValues.length) {
      host.innerHTML = '<div class="empty-trend">No depth profile values for this selection.</div>';
      return;
    }

    host.innerHTML = '';
    const trace = {
      x: times,
      y: depths,
      z: heatmapValues,
      type: 'heatmap',
      colorscale: 'Viridis',
      zmin: Math.min(...finiteValues),
      zmax: Math.max(...finiteValues),
      xgap: 1,
      ygap: 1,
      hoverongaps: false,
      colorbar: {
        title: { text: chart.unit || chart.label || '' },
        thickness: 12,
        len: 0.82,
        outlinewidth: 0,
      },
      hovertemplate: `Time (GST): %{x}<br>Depth: %{y:.2f} m<br>${App.escapeHtml(chart.label)}: %{z:.2f}${chart.unit ? ` ${App.escapeHtml(chart.unit)}` : ''}<extra></extra>`,
    };

    Plotly.newPlot(host, [trace], {
      margin: { t: 14, r: 72, b: 68, l: 72 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: {
        title: 'Time (GST)',
        gridcolor: 'rgba(91,101,118,.12)',
        tickangle: -35,
        automargin: true,
      },
      yaxis: {
        title: 'Depth (m)',
        autorange: 'reversed',
        gridcolor: 'rgba(91,101,118,.12)',
        automargin: true,
      },
      showlegend: false,
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
    const key = [state.period, state.fidasClean ? 'clean' : 'all'].join('|');
    const cached = cachedPayload(state.spectraCache, key);
    if (!force && cached) {
      state.spectraPayload = cached;
      renderFidasSpectra();
      return cached;
    }
    const host = document.getElementById('fidas-spectra-chart');
    if (host) host.innerHTML = '<div class="empty-trend">Loading spectra...</div>';
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/spectra`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('max_frames', '240');
    if (isFidasStation()) url.searchParams.set('clean', state.fidasClean ? 'true' : 'false');
    const payload = await App.fetchJSON(url.toString());
    const latestIndex = Number.isInteger(payload.latest_index) ? payload.latest_index : Math.max(0, (payload.frames || []).length - 1);
    state.spectraPayload = payload;
    state.spectraIndex = latestIndex;
    rememberPayload(state.spectraCache, key, payload);
    syncSpectraSlider();
    renderFidasSpectra();
    return payload;
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

    const rawValues = frame.values || [];
    const pairs = [];
    const length = Math.min(sizes.length, rawValues.length);
    for (let index = 0; index < length; index += 1) {
      const size = Number(sizes[index]);
      const value = Number(rawValues[index]);
      if (!Number.isFinite(size) || size <= 0) continue;
      pairs.push([size, Number.isFinite(value) && value > 0 ? value : 0.001]);
    }
    const x = pairs.map(([size]) => size);
    const y = pairs.map(([, value]) => value);
    if (!x.length) {
      if (label) label.textContent = 'No spectra';
      host.innerHTML = '<div class="empty-trend">No valid spectra bins for this sample.</div>';
      return;
    }
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

  function latestCacheKey() {
    return [state.period, state.quickSplitSensors ? 'split' : 'mean', isFidasStation() ? state.fidasClean : 'any'].join('|');
  }

  function timeseriesCacheKey() {
    return [
      state.period,
      state.aggregation,
      state.splitSensors ? 'split' : 'mean',
      isFidasStation() ? state.fidasClean : 'any',
      metricQueryValue(state.selectedMetrics),
    ].join('|');
  }

  function renderTimeseriesPayload(payload) {
    state.timeseriesPayload = payload;
    const grid = document.getElementById('chart-grid');
    const selectorMetrics = payload.available_metrics?.length ? payload.available_metrics : payload.metrics;
    if (selectorMetrics?.length && state.availableMetrics.length === 0) {
      state.availableMetrics = selectorMetrics;
      renderMetricSelector(selectorMetrics, payload.metrics || []);
    }
    clearChartGrid(grid);
    if (!payload.charts?.length) {
      if (grid) grid.innerHTML = `<article class="empty-state"><h2>No chart data for this view</h2><p>${App.escapeHtml(payload.message || 'No data available for the current selection.')}</p></article>`;
      updateTable({ metrics: [], table: [] });
      updateBuoyProfiles(payload);
      return;
    }
    groupAdvancedSensorCharts(payload.charts, payload).forEach((chart) => {
      if (grid) grid.appendChild(renderChart(chart, payload.events || []));
    });
    updateTable(payload);
    updateBuoyProfiles(payload);
    scheduleActiveChartResize();
  }

  async function loadLatest() {
    const requestId = ++state.latestRequestId;
    const key = latestCacheKey();
    const cached = cachedPayload(state.latestCache, key);
    if (cached) {
      updateLatestCards(cached);
      return cached;
    }
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/latest`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('include_trends', 'true');
    if (state.quickSplitSensors) url.searchParams.set('include_sensor_trends', 'true');
    if (isFidasStation()) url.searchParams.set('clean', state.fidasClean ? 'true' : 'false');
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.latestRequestId) return;
    rememberPayload(state.latestCache, key, payload);
    updateLatestCards(payload);
    return payload;
  }

  async function loadTimeseries() {
    const requestId = ++state.timeseriesRequestId;
    const key = timeseriesCacheKey();
    const cached = cachedPayload(state.timeseriesCache, key);
    if (cached) {
      renderTimeseriesPayload(cached);
      return cached;
    }
    const grid = document.getElementById('chart-grid');
    clearChartGrid(grid, '<article class="empty-state"><h2>Loading charts</h2><p>Updating the selected parameters.</p></article>');
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/timeseries`, window.location.origin);
    url.searchParams.set('period', state.period);
    url.searchParams.set('aggregation', state.aggregation);
    url.searchParams.set('split_sensors', state.splitSensors ? 'true' : 'false');
    if (isFidasStation()) url.searchParams.set('clean', state.fidasClean ? 'true' : 'false');
    if (state.selectedMetrics.length || state.metricsTouched) url.searchParams.set('metrics', metricQueryValue(state.selectedMetrics));
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.timeseriesRequestId) return;
    rememberPayload(state.timeseriesCache, key, payload);
    renderTimeseriesPayload(payload);
    return payload;
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
    document.getElementById('fidas-clean-data-toggle')?.addEventListener('change', (event) => {
      state.fidasClean = event.target.checked;
      state.spectraPayload = null;
      loadLatest();
      if (state.advancedPanel === 'spectra') {
        loadFidasSpectra(true).then(scheduleActiveChartResize);
      } else {
        loadTimeseries();
      }
    });

    document.querySelectorAll('#view-tabs button').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('#view-tabs button').forEach((item) => item.classList.toggle('is-active', item === button));
        document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('is-active', panel.id === `${button.dataset.tab}-view`));
        scheduleActiveChartResize();
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
      if (isFidasStation()) url.searchParams.set('clean', state.fidasClean ? 'true' : 'false');
      if (state.selectedMetrics.length || state.metricsTouched) url.searchParams.set('metrics', metricQueryValue(state.selectedMetrics));
      window.open(url.toString(), '_blank');
    });
    document.getElementById('view-raw-data')?.addEventListener('click', () => showRawData().catch((error) => console.error(error)));
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
      loadFidasSpectra().then(scheduleActiveChartResize);
    } else if (panelName === 'profiles') {
      loadBuoyProfiles().then(scheduleActiveChartResize);
    } else {
      if (panelName === 'atmospheric') loadTimeseries();
      scheduleActiveChartResize();
    }
  }

  function scheduleActiveChartResize() {
    window.requestAnimationFrame(() => {
      resizeActiveCharts();
      [120, 320, 720].forEach((delay) => window.setTimeout(resizeActiveCharts, delay));
    });
  }

  function resizeActiveCharts() {
    if (!window.Plotly) return;
    document.querySelectorAll('.tab-panel.is-active .chart-host').forEach((host) => {
      if (host.data || host._fullLayout) Plotly.Plots.resize(host);
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
