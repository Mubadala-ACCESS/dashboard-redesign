(() => {
  const page = document.querySelector('.station-page');
  if (!page) return;

  const stationId = page.dataset.stationId;
  const stationTemplate = page.dataset.stationTemplate || 'standard';
  const deviceType = page.dataset.deviceType || '';
  const state = {
    stationId,
    stationTemplate,
    deviceType,
    activeTab: 'quick',
    quickPeriod: '24H',
    advancedPeriod: stationTemplate === 'underwater' ? '6M' : '24H',
    dateRangeMode: false,
    availableDates: [],
    availableDateSet: new Set(),
    earliestDate: '',
    latestDate: '',
    quickRange: { start: '', end: '' },
    advancedRange: { start: '', end: '' },
    activeDatePart: 'start',
    calendarMonth: '',
    aggregation: 'raw',
    selectedMetrics: [],
    selectedProfileMetrics: [],
    metricsTouched: false,
    profileMetricsTouched: false,
    splitSensors: false,
    quickSplitSensors: false,
    quickChartMode: 'bars',
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
    userSelectedAdvancedPeriod: false,
    staleAdvancedPopupShown: false,
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
  const staleAdvancedThresholdMinutes = 12 * 60;
  const liveTelemetryTypes = new Set(['IoTBox', 'Fidas_Palas', 'Meteorological', 'Buoy']);

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

  function pointMarkerSize(count = 0) {
    if (count > 650) return 3.2;
    if (count > 260) return 4;
    return 5.2;
  }

  function isQuickBarMode() {
    return state.quickChartMode === 'bars';
  }

  function hexToRgba(hex, alpha) {
    const normalized = String(hex || '').replace('#', '');
    if (!/^[0-9a-f]{6}$/i.test(normalized)) return `rgba(91, 33, 182, ${alpha})`;
    const value = parseInt(normalized, 16);
    const red = (value >> 16) & 255;
    const green = (value >> 8) & 255;
    const blue = value & 255;
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }

  function isPresentChartValue(value) {
    if (value === null || value === undefined || value === '') return false;
    return Number.isFinite(Number(value));
  }

  function chartTimestampMs(value) {
    if (value === null || value === undefined || value === '') return null;
    if (typeof value === 'number') return null;
    if (value instanceof Date) {
      const ms = value.getTime();
      return Number.isFinite(ms) ? ms : null;
    }
    const text = String(value).trim();
    if (!/[12]\d{3}/.test(text) && !/\d{1,2}:\d{2}/.test(text)) return null;
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function median(values) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function inferredGapThreshold(series) {
    const deltas = [];
    let previousMs = null;
    (series || []).forEach((point) => {
      const ms = chartTimestampMs(point?.x);
      if (ms === null) return;
      if (previousMs !== null) {
        const delta = ms - previousMs;
        if (Number.isFinite(delta) && delta > 0) deltas.push(delta);
      }
      previousMs = ms;
    });
    const medianDelta = median(deltas);
    return medianDelta ? medianDelta * 2.75 : null;
  }

  function contiguousChartSegments(series) {
    const segments = [];
    const threshold = inferredGapThreshold(series);
    let segment = [];
    let previousMs = null;

    (series || []).forEach((point) => {
      const ms = chartTimestampMs(point?.x);
      if (!isPresentChartValue(point?.y)) {
        if (segment.length) segments.push(segment);
        segment = [];
        previousMs = ms;
        return;
      }

      if (
        segment.length &&
        threshold &&
        previousMs !== null &&
        ms !== null &&
        ms - previousMs > threshold
      ) {
        segments.push(segment);
        segment = [];
      }

      segment.push({ x: point.x, y: Number(point.y) });
      if (ms !== null) previousMs = ms;
    });

    if (segment.length) segments.push(segment);
    return segments;
  }

  function validChartPoints(series) {
    return (series || [])
      .filter((point) => isPresentChartValue(point?.y))
      .map((point) => ({ x: point.x, y: Number(point.y) }));
  }

  function pointAreaTraces(series, color, name) {
    return contiguousChartSegments(series)
      .filter((segment) => segment.length >= 4)
      .map((segment, index) => ({
        x: segment.map((point) => point.x),
        y: segment.map((point) => point.y),
        type: 'scatter',
        mode: 'none',
        name: `${name} area ${index + 1}`,
        fill: 'tozeroy',
        fillcolor: hexToRgba(color, 0.12),
        hoverinfo: 'skip',
        showlegend: false,
        legendgroup: name,
      }));
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

  function isUnderwaterStation() {
    return state.stationTemplate === 'underwater';
  }

  function shouldUseDateRangeControls() {
    return !liveTelemetryTypes.has(state.deviceType);
  }

  function activePeriod() {
    return state.activeTab === 'advanced' ? state.advancedPeriod : state.quickPeriod;
  }

  function visibleTabContext() {
    return document.getElementById('advanced-view')?.classList.contains('is-active') ? 'advanced' : 'quick';
  }

  function activeRange() {
    return rangeForContext(visibleTabContext());
  }

  function rangeForContext(context) {
    return context === 'advanced' ? state.advancedRange : state.quickRange;
  }

  function compareDateStrings(a, b) {
    return String(a || '').localeCompare(String(b || ''));
  }

  function formatDateLabel(value) {
    if (!value) return '--';
    const parts = String(value).split('-');
    if (parts.length !== 3) return value;
    return `${parts[2]} ${new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, 1)).toLocaleString(undefined, { month: 'short' })} ${parts[0]}`;
  }

  function rangeLabel(range = activeRange()) {
    if (!state.dateRangeMode) return activePeriod();
    if (!range?.start && !range?.end) return 'No dated samples';
    if (range.start && range.end && range.start === range.end) return formatDateLabel(range.start);
    return `${formatDateLabel(range.start)} to ${formatDateLabel(range.end)}`;
  }

  function syncPeriodControls() {
    const period = activePeriod();
    document.querySelectorAll('#period-buttons button').forEach((item) => {
      item.classList.toggle('is-active', item.dataset.period === period);
    });
    const label = document.getElementById('stats-period-label');
    if (label && state.activeTab === 'quick') label.textContent = state.dateRangeMode ? rangeLabel(state.quickRange) : state.quickPeriod;
    syncDateRangeControls();
  }

  function monthKey(value) {
    return String(value || '').slice(0, 7);
  }

  function shiftMonth(key, delta) {
    const [year, month] = String(key || state.latestDate || state.earliestDate || new Date().toISOString().slice(0, 7)).split('-').map(Number);
    const shifted = new Date(Date.UTC(year || new Date().getUTCFullYear(), (month || 1) - 1 + delta, 1));
    return shifted.toISOString().slice(0, 7);
  }

  function daysInMonth(year, month) {
    return new Date(Date.UTC(year, month, 0)).getUTCDate();
  }

  function syncDateRangeControls() {
    const dateControl = document.getElementById('date-range-control');
    const periodControl = document.getElementById('period-control');
    if (periodControl) {
      periodControl.hidden = state.dateRangeMode;
      periodControl.style.display = state.dateRangeMode ? 'none' : '';
    }
    if (!dateControl) return;
    dateControl.hidden = !state.dateRangeMode;
    dateControl.style.display = state.dateRangeMode ? '' : 'none';
    if (!state.dateRangeMode) return;

    const range = activeRange();
    const startLabel = document.getElementById('date-start-label');
    const endLabel = document.getElementById('date-end-label');
    if (startLabel) startLabel.textContent = formatDateLabel(range.start);
    if (endLabel) endLabel.textContent = formatDateLabel(range.end);
    document.querySelectorAll('.date-field-button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.datePart === state.activeDatePart);
    });
    renderDateCalendar();
  }

  function renderDateCalendar() {
    const calendar = document.getElementById('date-calendar-popover');
    if (!calendar || calendar.hidden || !state.dateRangeMode) return;
    if (!state.availableDates.length) {
      calendar.innerHTML = '<p class="date-range-empty">No dated samples are available for this station yet.</p>';
      return;
    }
    const range = activeRange();
    state.calendarMonth = state.calendarMonth || monthKey(range[state.activeDatePart]) || monthKey(state.latestDate);
    const [year, month] = state.calendarMonth.split('-').map(Number);
    const monthName = new Date(Date.UTC(year, month - 1, 1)).toLocaleString(undefined, { month: 'long', year: 'numeric' });
    const firstDay = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
    const totalDays = daysInMonth(year, month);
    const cells = [];
    for (let index = 0; index < firstDay; index += 1) {
      cells.push('<button type="button" class="date-day is-empty" disabled></button>');
    }
    for (let day = 1; day <= totalDays; day += 1) {
      const value = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const hasData = state.availableDateSet.has(value);
      const isSelected = value === range.start || value === range.end;
      const isInRange = range.start && range.end && compareDateStrings(value, range.start) >= 0 && compareDateStrings(value, range.end) <= 0;
      cells.push(`
        <button
          type="button"
          class="date-day ${isSelected ? 'is-selected' : ''} ${isInRange ? 'is-in-range' : ''}"
          data-date-value="${value}"
          ${hasData ? '' : 'disabled'}
          title="${hasData ? 'Data available' : 'No data on this date'}"
        >${day}</button>
      `);
    }
    calendar.innerHTML = `
      <div class="date-calendar-head">
        <button type="button" data-calendar-nav="-1" aria-label="Previous month">&lt;</button>
        <strong>${App.escapeHtml(monthName)}</strong>
        <button type="button" data-calendar-nav="1" aria-label="Next month">&gt;</button>
      </div>
      <div class="date-calendar-grid">
        ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => `<span>${day}</span>`).join('')}
        ${cells.join('')}
      </div>
    `;
    calendar.querySelectorAll('[data-calendar-nav]').forEach((button) => {
      button.addEventListener('click', () => {
        state.calendarMonth = shiftMonth(state.calendarMonth, Number(button.dataset.calendarNav || 0));
        renderDateCalendar();
      });
    });
  }

  function setActiveRangeDate(part, value) {
    if (!value) return;
    const context = visibleTabContext();
    state.activeTab = context;
    const range = { ...rangeForContext(context) };
    if (part === 'end') {
      range.end = value;
      if (!range.start || compareDateStrings(range.start, range.end) > 0) range.start = value;
    } else {
      range.start = value;
      if (!range.end || compareDateStrings(range.start, range.end) > 0) range.end = value;
    }
    if (context === 'advanced') state.advancedRange = range;
    else state.quickRange = range;
    syncPeriodControls();
    if (context === 'advanced') reloadAdvancedWindow();
    else loadLatest();
  }

  function windowCacheKey(context) {
    if (!state.dateRangeMode) return '';
    const range = rangeForContext(context);
    return `${range.start || ''}:${range.end || ''}`;
  }

  function applyWindowParams(url, context) {
    if (!state.dateRangeMode) {
      url.searchParams.set('period', context === 'advanced' ? state.advancedPeriod : state.quickPeriod);
      return;
    }
    const range = rangeForContext(context);
    url.searchParams.set('period', 'ALL');
    if (range.start) url.searchParams.set('start_date', range.start);
    if (range.end) url.searchParams.set('end_date', range.end);
  }

  async function initDateRangeControls() {
    if (!shouldUseDateRangeControls()) {
      syncDateRangeControls();
      return;
    }
    state.dateRangeMode = true;
    syncDateRangeControls();
    try {
      const payload = await App.fetchJSON(`/api/stations/${encodeURIComponent(state.stationId)}/available-dates`);
      const dates = Array.isArray(payload.dates) ? payload.dates.filter(Boolean).sort() : [];
      state.availableDates = dates;
      state.availableDateSet = new Set(dates);
      state.earliestDate = payload.earliest_date || dates[0] || '';
      state.latestDate = payload.latest_date || dates[dates.length - 1] || '';
      state.quickRange = { start: state.earliestDate, end: state.latestDate };
      state.advancedRange = { start: state.earliestDate, end: state.latestDate };
      state.calendarMonth = monthKey(state.latestDate || state.earliestDate);
    } catch (error) {
      console.error(error);
      state.dateRangeMode = false;
    }
    syncPeriodControls();
  }

  function freshnessMinutes() {
    const explicit = Number(page.dataset.freshnessMinutes);
    if (Number.isFinite(explicit)) return explicit;
    const latestMs = Date.parse(page.dataset.lastUpdateIso || '');
    if (!Number.isFinite(latestMs)) return null;
    return Math.max(0, Math.floor((Date.now() - latestMs) / 60000));
  }

  function isAdvancedDataStale() {
    const minutes = freshnessMinutes();
    return minutes === null || minutes > staleAdvancedThresholdMinutes;
  }

  function staleWindowMessage() {
    const latest = page.dataset.lastUpdateLabel || 'the latest available sample';
    const body = liveTelemetryTypes.has(state.deviceType)
      ? 'This station has not reported within the past 12 hours. In Advanced view, the display periods are calculated backward from the latest available sample, so 24H, 7D, and longer windows still show the most recent usable data instead of an empty window ending now.'
      : 'This station is not a live telemetry feed. Data is collected in the field and uploaded in batches, so Advanced view is anchored to the latest timestamp available in the database. The display periods show windows backward from that timestamp rather than from the current time.';
    return `
      <article class="modal-panel">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Display period notice</span>
            <h2>Showing The Latest Available Data Window</h2>
            <p>Latest sample: ${App.escapeHtml(latest)}</p>
          </div>
          <button class="ghost-button" data-close-modal type="button">Close</button>
        </header>
        <p>${App.escapeHtml(body)}</p>
        <footer class="modal-actions">
          <button class="primary-button" data-close-modal type="button">Got it</button>
        </footer>
      </article>
    `;
  }

  function maybeShowStaleAdvancedPopup() {
    if (state.staleAdvancedPopupShown || !isAdvancedDataStale()) return;
    state.staleAdvancedPopupShown = true;
    App.openModal(staleWindowMessage());
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

  function makeCard(card, periodLabel = state.quickPeriod) {
    const unit = card.unit || '';
    if (isUnderwaterStation()) {
      return `
        <article class="metric-card metric-card--stats">
          <div class="metric-card__top">
            <span>${App.escapeHtml(card.label)}</span>
            <small>${App.escapeHtml(periodLabel)}</small>
          </div>
          <div class="metric-stat-grid underwater-stat-grid">
            <div>
              <small>Mean</small>
              <b>${metricValue(card.mean, unit)}</b>
            </div>
            <div>
              <small>Min</small>
              <b>${metricValue(card.min, unit)}</b>
            </div>
            <div>
              <small>Max</small>
              <b>${metricValue(card.max, unit)}</b>
            </div>
            <div>
              <small>Samples</small>
              <b>${displayValue(card.count)}</b>
            </div>
          </div>
        </article>
      `;
    }
    return `
      <article class="metric-card">
        <div class="metric-card__top">
          <span>${App.escapeHtml(card.label)}</span>
          <small>${App.escapeHtml(periodLabel)}</small>
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
    const period = payload.period || state.quickPeriod;
    const label = document.getElementById('stats-period-label');
    const container = document.getElementById('latest-cards');

    if (label) label.textContent = period;
    if (!payload.cards?.length) {
      const heading = isUnderwaterStation() ? 'No statistics available' : 'No current readings';
      container.innerHTML = `<article class="empty-state"><h2>${heading}</h2><p>No data was available for the selected display period.</p></article>`;
      renderQuickTrends(payload);
      return;
    }

    container.innerHTML = payload.cards.map((card) => makeCard(card, period)).join('');
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
    document.querySelectorAll('#quick-chart-mode-buttons button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.quickChartMode === state.quickChartMode);
    });
    if (toggle) {
      toggle.hidden = !payload.supports_sensor_trends;
      const input = document.getElementById('quick-split-sensors-toggle');
      if (input) input.checked = state.quickSplitSensors && !!payload.supports_sensor_trends;
    }
    if (context) {
      const sensorText = state.quickSplitSensors && payload.supports_sensor_trends ? ' with individual IoT sensor overlays' : '';
      const chartText = isQuickBarMode() ? 'bar charts' : 'point charts';
      const prefix = state.dateRangeMode ? `${payload.period || rangeLabel(state.quickRange)}` : (isUnderwaterStation() ? 'Interval-sampled EXO' : `${payload.period || state.quickPeriod}`);
      context.textContent = `${prefix} ${chartText} using ${aggregationLabel(payload.trend_aggregation)} values${sensorText}.`;
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
    const points = validChartPoints(trend.series);
    if (!points.length) {
      host.innerHTML = '<div class="empty-trend">No trend data for this display period.</div>';
      return;
    }

    const baseTrace = {
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      name: 'Station mean',
      hovertemplate: `%{x}<br>%{y:.2f}${unit}<extra></extra>`,
    };
    const traces = isQuickBarMode()
      ? [{
        ...baseTrace,
        type: 'bar',
        marker: { color, opacity: 0.68 },
      }]
      : [
        ...pointAreaTraces(trend.series, color, baseTrace.name),
        {
          ...baseTrace,
          type: 'scatter',
          mode: 'markers',
          marker: { size: pointMarkerSize(points.length), color, opacity: 0.9, line: { color: '#ffffff', width: 0.7 } },
        },
      ];

    if (showSensorTrends) {
      (trend.sensor_trends || []).forEach((sensorTrend, index) => {
        const sensorPoints = validChartPoints(sensorTrend.series);
        if (!sensorPoints.length) return;
        const sensorColor = sensorTrendColors[index % sensorTrendColors.length];
        const sensorTrace = {
          x: sensorPoints.map((point) => point.x),
          y: sensorPoints.map((point) => point.y),
          name: sensorTrend.label.split(' - ').pop() || `Sensor ${index + 1}`,
          hovertemplate: `%{fullData.name}<br>%{x}<br>%{y:.2f}${unit}<extra></extra>`,
        };
        if (isQuickBarMode()) {
          traces.push({
            ...sensorTrace,
            type: 'bar',
            marker: { color: sensorColor, opacity: 0.58 },
          });
          return;
        }
        traces.push(...pointAreaTraces(sensorTrend.series, sensorColor, sensorTrace.name));
        traces.push({
          ...sensorTrace,
          type: 'scatter',
          mode: 'markers',
          marker: { size: pointMarkerSize(sensorPoints.length), color: sensorColor, opacity: 0.9, line: { color: '#ffffff', width: 0.7 } },
        });
      });
    }

    const layout = {
      margin: { t: 10, r: 18, b: 38, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { gridcolor: 'rgba(91,101,118,.12)', tickfont: { size: 11 } },
      yaxis: { title: unit.trim(), gridcolor: 'rgba(91,101,118,.12)', zerolinecolor: 'rgba(91,101,118,.16)' },
      legend: { orientation: 'h', y: 1.14, x: 0, font: { size: 11 } },
      showlegend: traces.length > 1,
    };
    if (isQuickBarMode()) {
      layout.barmode = traces.length > 1 ? 'group' : 'relative';
      layout.bargap = 0.18;
    }
    Plotly.newPlot(host, traces, layout, { displaylogo: false, responsive: true });
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
    const traces = [];
    traceSource.forEach((sourceChart, index) => {
      const sourcePoints = validChartPoints(sourceChart.series || []);
      const sourceX = sourcePoints.map((point) => point.x);
      const sourceY = sourcePoints.map((point) => point.y);
      const sourceName = sourceChart.sensorLabel || sourceChart.label || chart.label;
      const sourceColor = chart.sensorCharts?.length ? sensorTrendColors[index % sensorTrendColors.length] : '#4c1d95';
      traces.push(...pointAreaTraces(sourceChart.series || [], sourceColor, sourceName));
      traces.push({
        x: sourceX,
        y: sourceY,
        type: 'scatter',
        mode: 'markers',
        name: sourceName,
        marker: {
          size: pointMarkerSize((sourceChart.series || []).length),
          color: sourceColor,
          opacity: 0.9,
          line: { color: '#ffffff', width: 0.7 },
        },
        hovertemplate: '%{fullData.name}<br>%{x}<br>%{y}<extra></extra>',
      });
    });
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

  function downloadMetricOptions() {
    const metrics = metricsForActivePanel(state.availableMetrics || []);
    if (metrics.length) return metrics;
    return metricsForActivePanel(state.timeseriesPayload?.available_metrics || state.timeseriesPayload?.metrics || []);
  }

  function buildDownloadModal() {
    const metrics = downloadMetricOptions();
    const active = new Set(activeMetricKeys());
    const allSelected = !active.size;
    const dateWindowMarkup = state.dateRangeMode
      ? `<div class="download-date-summary">
          <span class="control-label">Date window</span>
          <strong>${App.escapeHtml(rangeLabel(state.advancedRange))}</strong>
          <small>Uses the current Advanced view date selection.</small>
        </div>`
      : `<label>
          <span class="control-label">Display period</span>
          <select name="period">
            ${['24H', '7D', '30D', '3M', '6M', '1Y', 'ALL'].map((period) => `<option value="${period}" ${period === state.advancedPeriod ? 'selected' : ''}>${period === 'ALL' ? 'All data' : period}</option>`).join('')}
          </select>
        </label>`;
    const metricRows = metrics.length ? metrics.map((metric, index) => {
      const checked = allSelected ? index < defaultSelectedMetricLimit : active.has(metric.key);
      return `
        <label class="download-option">
          <input type="checkbox" name="metrics" value="${App.escapeHtml(metric.key)}" ${checked ? 'checked' : ''} />
          <span>
            <strong>${App.escapeHtml(metric.label)}</strong>
            <small>${App.escapeHtml(metric.key)}</small>
          </span>
        </label>
      `;
    }).join('') : '<p class="small-note">No parameter list is available yet. The export will use the default parameters.</p>';

    return `
      <article class="modal-panel download-modal">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Download CSV</span>
            <h2>Choose export options</h2>
            <p>Select the display period, aggregation, parameters, and whether to append public location columns.</p>
          </div>
          <button class="ghost-button" data-close-modal type="button">Close</button>
        </header>
        <form id="download-options-form" class="download-form">
          <div class="download-grid">
            ${dateWindowMarkup}
            <label>
              <span class="control-label">Aggregation</span>
              <select name="aggregation">
                ${[
                  ['raw', 'No aggregation'],
                  ['15m', '15 minutes'],
                  ['1h', 'Hourly'],
                  ['6h', '6 hours'],
                  ['1d', 'Daily'],
                ].map(([value, label]) => `<option value="${value}" ${value === state.aggregation ? 'selected' : ''}>${label}</option>`).join('')}
              </select>
            </label>
          </div>
          <label class="toggle-row download-toggle">
            <input type="checkbox" name="all_data" />
            <span>Export all available data</span>
          </label>
          <label class="toggle-row download-toggle">
            <input type="checkbox" name="append_location" />
            <span>Append station name, latitude, and longitude</span>
          </label>
          ${document.getElementById('split-sensors-toggle') ? `
          <label class="toggle-row download-toggle">
            <input type="checkbox" name="split_sensors" ${state.splitSensors ? 'checked' : ''} />
            <span>Export individual IoT sensor readings</span>
          </label>` : ''}
          ${isFidasStation() ? `
          <label class="toggle-row download-toggle">
            <input type="checkbox" name="clean" ${state.fidasClean ? 'checked' : ''} />
            <span>Use clean Fidas data</span>
          </label>` : ''}
          <div class="download-parameter-head">
            <span class="control-label">Parameters</span>
            <label class="toggle-row">
              <input type="checkbox" id="download-all-parameters" />
              <span>All parameters</span>
            </label>
          </div>
          <div class="download-metric-grid">${metricRows}</div>
          <footer class="modal-actions">
            <button class="ghost-button" data-close-modal type="button">Cancel</button>
            <button class="primary-button" type="submit">Download CSV</button>
          </footer>
        </form>
      </article>
    `;
  }

  function wireDownloadModal() {
    const dialog = document.getElementById('global-modal');
    const form = document.getElementById('download-options-form');
    if (!dialog || !form) return;
    const allParameters = document.getElementById('download-all-parameters');
    const metricInputs = Array.from(form.querySelectorAll('input[name="metrics"]'));
    allParameters?.addEventListener('change', () => {
      metricInputs.forEach((input) => {
        input.checked = allParameters.checked;
      });
    });
    form.querySelector('input[name="all_data"]')?.addEventListener('change', (event) => {
      const periodSelect = form.querySelector('select[name="period"]');
      const aggregationSelect = form.querySelector('select[name="aggregation"]');
      if (!aggregationSelect) return;
      if (event.target.checked) {
        if (periodSelect) periodSelect.value = 'ALL';
        aggregationSelect.value = 'raw';
      }
    });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/export.csv`, window.location.origin);
      if (state.dateRangeMode && !data.get('all_data')) {
        applyWindowParams(url, 'advanced');
      } else {
        url.searchParams.set('period', data.get('all_data') ? 'ALL' : String(data.get('period') || state.advancedPeriod));
      }
      url.searchParams.set('aggregation', String(data.get('aggregation') || state.aggregation));
      url.searchParams.set('split_sensors', data.get('split_sensors') ? 'true' : 'false');
      url.searchParams.set('append_location', data.get('append_location') ? 'true' : 'false');
      if (isFidasStation()) url.searchParams.set('clean', data.get('clean') ? 'true' : 'false');
      const selectedMetrics = data.getAll('metrics').map(String).filter(Boolean);
      if (selectedMetrics.length) url.searchParams.set('metrics', selectedMetrics.join('|'));
      window.open(url.toString(), '_blank');
      dialog.close();
    });
  }

  function showDownloadOptions() {
    App.openModal(buildDownloadModal());
    wireDownloadModal();
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
    const key = [state.advancedPeriod, windowCacheKey('advanced'), metricQueryValue(state.selectedProfileMetrics)].join('|');
    const cached = cachedPayload(state.profileCache, key);
    if (cached) {
      state.profilePayload = cached;
      renderBuoyProfileCharts(cached);
      return cached;
    }
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/profiles`, window.location.origin);
    applyWindowParams(url, 'advanced');
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
            <p>${App.escapeHtml(payload.effective_period || payload.period || state.advancedPeriod)} heatmap · Latest profile ${App.escapeHtml(chart.latest_label || '')}</p>
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
    const key = [state.advancedPeriod, windowCacheKey('advanced'), state.fidasClean ? 'clean' : 'all'].join('|');
    const cached = cachedPayload(state.spectraCache, key);
    if (!force && cached) {
      state.spectraPayload = cached;
      renderFidasSpectra();
      return cached;
    }
    const host = document.getElementById('fidas-spectra-chart');
    if (host) host.innerHTML = '<div class="empty-trend">Loading spectra...</div>';
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/spectra`, window.location.origin);
    applyWindowParams(url, 'advanced');
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

    Plotly.newPlot(host, [
    ...pointAreaTraces(x.map((value, index) => ({ x: value, y: y[index] })), '#5b21b6', 'Particle count'),
    {
      x,
      y,
      type: 'scatter',
      mode: 'markers',
      name: 'Particle count',
      marker: { color: '#5b21b6', size: pointMarkerSize(x.length), opacity: 0.9, line: { color: '#ffffff', width: 0.7 } },
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
    return [state.quickPeriod, windowCacheKey('quick'), state.quickSplitSensors ? 'split' : 'mean', isFidasStation() ? state.fidasClean : 'any'].join('|');
  }

  function timeseriesCacheKey() {
    return [
      state.advancedPeriod,
      windowCacheKey('advanced'),
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
      updateBuoyProfiles(payload);
      return;
    }
    groupAdvancedSensorCharts(payload.charts, payload).forEach((chart) => {
      if (grid) grid.appendChild(renderChart(chart, payload.events || []));
    });
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
    applyWindowParams(url, 'quick');
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
    applyWindowParams(url, 'advanced');
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

  function reloadAdvancedWindow() {
    if (state.advancedPanel === 'spectra') {
      loadFidasSpectra(true);
    } else if (isBuoyProfilePanel()) {
      loadBuoyProfiles();
    } else {
      loadTimeseries();
    }
  }

  function setActivePeriod(period, options = {}) {
    if (!period) return;
    const targetTab = options.targetTab || state.activeTab || 'quick';
    if (targetTab === 'advanced') {
      state.advancedPeriod = period;
      if (options.userSelected) state.userSelectedAdvancedPeriod = true;
    } else {
      state.quickPeriod = period;
    }
    syncPeriodControls();
    if (options.load === false) return;
    if (targetTab === 'advanced') reloadAdvancedWindow();
    else loadLatest();
  }

  function applyUnderwaterAdvancedDefaultPeriod() {
    if (state.dateRangeMode) return;
    if (!isUnderwaterStation() || state.userSelectedAdvancedPeriod || state.advancedPeriod === '6M') return;
    setActivePeriod('6M', { targetTab: 'advanced', load: false });
  }

  function wireControls() {
    document.querySelectorAll('.date-field-button').forEach((button) => {
      button.addEventListener('click', () => {
        state.activeDatePart = button.dataset.datePart || 'start';
        const range = activeRange();
        state.calendarMonth = monthKey(range[state.activeDatePart] || state.latestDate || state.earliestDate);
        const calendar = document.getElementById('date-calendar-popover');
        if (calendar) {
          calendar.hidden = false;
          renderDateCalendar();
        }
        syncDateRangeControls();
      });
    });
    document.getElementById('date-range-control')?.addEventListener('click', (event) => {
      const target = event.target.closest?.('[data-date-value]');
      if (!target || target.disabled) return;
      event.preventDefault();
      event.stopPropagation();
      setActiveRangeDate(state.activeDatePart, target.dataset.dateValue);
      const calendar = document.getElementById('date-calendar-popover');
      if (calendar) calendar.hidden = true;
    }, true);
    document.addEventListener('click', (event) => {
      const dateControl = document.getElementById('date-range-control');
      const calendar = document.getElementById('date-calendar-popover');
      if (!dateControl || !calendar || calendar.hidden) return;
      if (!dateControl.contains(event.target)) calendar.hidden = true;
    });
    document.getElementById('date-calendar-popover')?.addEventListener('click', (event) => {
      const target = event.target.closest?.('[data-date-value]');
      if (!target || target.disabled) return;
      event.stopPropagation();
      setActiveRangeDate(state.activeDatePart, target.dataset.dateValue);
      event.currentTarget.hidden = true;
    });
    document.querySelectorAll('#period-buttons button').forEach((button) => {
      button.addEventListener('click', () => {
        setActivePeriod(button.dataset.period, { userSelected: true });
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
    document.querySelectorAll('#quick-chart-mode-buttons button').forEach((button) => {
      button.addEventListener('click', () => {
        state.quickChartMode = button.dataset.quickChartMode || 'points';
        document.querySelectorAll('#quick-chart-mode-buttons button').forEach((item) => item.classList.toggle('is-active', item === button));
        if (state.latestPayload) renderQuickTrends(state.latestPayload);
      });
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
        state.activeTab = button.dataset.tab || 'quick';
        if (state.activeTab === 'advanced') applyUnderwaterAdvancedDefaultPeriod();
        syncPeriodControls();
        document.querySelectorAll('#view-tabs button').forEach((item) => item.classList.toggle('is-active', item === button));
        document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('is-active', panel.id === `${button.dataset.tab}-view`));
        if (state.activeTab === 'advanced' && !state.dateRangeMode) {
          maybeShowStaleAdvancedPopup();
        }
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

    document.getElementById('download-csv')?.addEventListener('click', () => showDownloadOptions());
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
    await initDateRangeControls();
    syncPeriodControls();
    await loadLatest();
    await loadTimeseries();
  }

  init().catch((error) => {
    console.error(error);
  });
})();
