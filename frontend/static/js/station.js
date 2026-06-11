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
    spotterPeriod: '30D',
    spotterAggregation: '1d',
    spotterRoseMode: 'energy',
    spotterFullRange: true,
    spotterPanel: 'overview',
    spotterPayload: null,
    spotterRows: [],
    spotterSupplementPayload: null,
    spotterSupplementRows: [],
    spotterRequestId: 0,
    latestCache: new Map(),
    timeseriesCache: new Map(),
    profileCache: new Map(),
    spectraCache: new Map(),
    spotterCache: new Map(),
  };

  const emptyValue = '&mdash;';
  const defaultSelectedMetricLimit = 3;
  const trendColors = ['#5b21b6', '#0f766e', '#2563eb', '#d97706', '#be185d', '#64748b'];
  const sensorTrendColors = ['#0f766e', '#2563eb', '#d97706', '#be185d'];
  const spotterMetricKeys = [
    'significant_wave_height_m',
    'peak_period_s',
    'mean_period_s',
    'peak_direction_deg',
    'mean_direction_deg',
    'mean_directional_spread_deg',
    'peak_directional_spread_deg',
    'wind_speed_m_s',
    'wind_direction_deg',
    'surface_temperature_c',
    'mean_barometric_pressure_hpa',
    'humidity_pct',
    'battery_voltage_v',
    'battery_power_w',
  ];
  const spotterDirectionKeys = new Set(['peak_direction_deg', 'mean_direction_deg', 'wind_direction_deg']);
  const spotterSparseMetricKeys = [
    'wind_speed_m_s',
    'wind_direction_deg',
    'surface_temperature_c',
    'mean_barometric_pressure_hpa',
    'humidity_pct',
    'battery_voltage_v',
    'battery_power_w',
  ];
  const spotterUnits = {
    significant_wave_height_m: 'm',
    peak_period_s: 's',
    mean_period_s: 's',
    peak_direction_deg: 'deg',
    mean_direction_deg: 'deg',
    mean_directional_spread_deg: 'deg',
    peak_directional_spread_deg: 'deg',
    wind_speed_m_s: 'm/s',
    wind_direction_deg: 'deg',
    surface_temperature_c: 'deg C',
    mean_barometric_pressure_hpa: 'hPa',
    humidity_pct: '%',
    battery_voltage_v: 'V',
    battery_power_w: 'W',
  };
  const spotterWaveBins = [
    { label: '0-0.5 m', min: 0, max: 0.5, color: '#c7f3ef' },
    { label: '0.5-1.25 m', min: 0.5, max: 1.25, color: '#8dded9' },
    { label: '1.25-2.5 m', min: 1.25, max: 2.5, color: '#9b7df0' },
    { label: '2.5-4 m', min: 2.5, max: 4, color: '#6d28d9' },
    { label: '>4 m', min: 4, max: Infinity, color: '#3b0764' },
  ];
  const spotterSeaStateBins = [
    { label: 'Calm', min: 0, max: 0.5, color: '#d7f7f2' },
    { label: 'Slight', min: 0.5, max: 1.25, color: '#a7e8e3' },
    { label: 'Moderate', min: 1.25, max: 2.5, color: '#c4b5fd' },
    { label: 'Rough', min: 2.5, max: 4, color: '#8b5cf6' },
    { label: 'Very rough', min: 4, max: 6, color: '#6d28d9' },
    { label: 'High', min: 6, max: Infinity, color: '#4c1d95' },
  ];
  const spotterSectorCount = 16;
  const spotterPlotConfig = { displaylogo: false, responsive: true };
  const maxClientCacheEntries = 24;
  const staleAdvancedThresholdMinutes = 12 * 60;
  const liveTelemetryTypes = new Set(['IoTBox', 'Fidas_Palas', 'Meteorological', 'Buoy']);
  let timeseriesLoadTimer = null;

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

  function isSpotterBuoy() {
    return state.stationTemplate === 'spotter_buoy';
  }

  function shouldUseDateRangeControls() {
    return !liveTelemetryTypes.has(state.deviceType);
  }

  function activePeriod() {
    return state.activeTab === 'advanced' ? state.advancedPeriod : state.quickPeriod;
  }

  function visibleTabContext() {
    return state.activeTab === 'advanced' ? 'advanced' : 'quick';
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

  function shiftDateString(value, days) {
    if (!value) return '';
    const [year, month, day] = String(value).split('-').map(Number);
    if (!year || !month || !day) return value;
    const shifted = new Date(Date.UTC(year, month - 1, day + days));
    return shifted.toISOString().slice(0, 10);
  }

  function dateAxisRangeForContext(context) {
    if (!state.dateRangeMode) return null;
    const range = rangeForContext(context);
    if (!range?.start && !range?.end) return null;
    const start = range.start || state.earliestDate || state.availableDates[0];
    const end = range.end || state.latestDate || state.availableDates[state.availableDates.length - 1];
    if (!start || !end) return null;
    return [start, shiftDateString(end, 1)];
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

  function availableMonthKeys() {
    return [...new Set(state.availableDates.map(monthKey).filter(Boolean))].sort();
  }

  function clampCalendarMonth(key) {
    const months = availableMonthKeys();
    const fallback = String(key || state.latestDate || state.earliestDate || new Date().toISOString().slice(0, 7)).slice(0, 7);
    if (!months.length) return fallback;
    if (months.includes(fallback)) return fallback;
    if (compareDateStrings(fallback, months[0]) < 0) return months[0];
    if (compareDateStrings(fallback, months[months.length - 1]) > 0) return months[months.length - 1];
    let closest = months[0];
    months.forEach((item) => {
      if (compareDateStrings(item, fallback) <= 0) closest = item;
    });
    return closest;
  }

  function shiftAvailableMonth(key, delta) {
    const months = availableMonthKeys();
    if (!months.length) return shiftMonth(key, delta);
    const current = clampCalendarMonth(key);
    const index = Math.max(0, months.indexOf(current));
    const nextIndex = Math.max(0, Math.min(months.length - 1, index + delta));
    return months[nextIndex];
  }

  function availableYears() {
    return [...new Set(availableMonthKeys().map((item) => item.slice(0, 4)))];
  }

  function availableMonthsForYear(year) {
    return availableMonthKeys()
      .filter((item) => item.startsWith(`${year}-`))
      .map((item) => Number(item.slice(5, 7)));
  }

  function monthName(month) {
    return new Date(Date.UTC(2026, month - 1, 1)).toLocaleString(undefined, { month: 'long' });
  }

  function monthKeyFromParts(year, month) {
    return `${year}-${String(month).padStart(2, '0')}`;
  }

  function closestMonthForYear(year, preferredMonth) {
    const months = availableMonthsForYear(year);
    if (!months.length) return clampCalendarMonth(monthKeyFromParts(year, preferredMonth || 1));
    if (months.includes(preferredMonth)) return preferredMonth;
    return months.reduce((best, item) => (
      Math.abs(item - preferredMonth) < Math.abs(best - preferredMonth) ? item : best
    ), months[0]);
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
    state.calendarMonth = clampCalendarMonth(state.calendarMonth || monthKey(range[state.activeDatePart]) || monthKey(state.latestDate));
    const [year, month] = state.calendarMonth.split('-').map(Number);
    const firstDay = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
    const totalDays = daysInMonth(year, month);
    const months = availableMonthKeys();
    const years = availableYears();
    const monthsForYear = availableMonthsForYear(year);
    const canGoBack = months.length ? state.calendarMonth !== months[0] : true;
    const canGoForward = months.length ? state.calendarMonth !== months[months.length - 1] : true;
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
        <button type="button" data-calendar-nav="-1" aria-label="Previous month" ${canGoBack ? '' : 'disabled'}>&lt;</button>
        <div class="date-calendar-selects" aria-label="Calendar month and year">
          <select data-calendar-select="month" aria-label="Month">
            ${monthsForYear.map((item) => `<option value="${item}" ${item === month ? 'selected' : ''}>${App.escapeHtml(monthName(item))}</option>`).join('')}
          </select>
          <select data-calendar-select="year" aria-label="Year">
            ${years.map((item) => `<option value="${item}" ${Number(item) === year ? 'selected' : ''}>${App.escapeHtml(item)}</option>`).join('')}
          </select>
        </div>
        <button type="button" data-calendar-nav="1" aria-label="Next month" ${canGoForward ? '' : 'disabled'}>&gt;</button>
      </div>
      <div class="date-calendar-grid">
        ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => `<span>${day}</span>`).join('')}
        ${cells.join('')}
      </div>
    `;
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

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function setHtml(id, value) {
    const element = document.getElementById(id);
    if (element) element.innerHTML = value;
  }

  function payloadCard(payload, keys) {
    const cards = payload?.cards || [];
    for (const key of keys) {
      const exact = cards.find((card) => card.metric === key);
      if (exact) return exact;
    }
    const normalizedKeys = keys.map((key) => String(key).toLowerCase());
    return cards.find((card) => {
      const text = `${card.metric || ''} ${card.label || ''}`.toLowerCase();
      return normalizedKeys.some((key) => text.includes(key));
    }) || null;
  }

  function numericCardValue(card) {
    const numeric = Number(card?.latest);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function compassSector(degrees) {
    const numeric = Number(degrees);
    if (!Number.isFinite(numeric)) return '';
    const sectors = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const index = Math.round((((numeric % 360) + 360) % 360) / 22.5) % 16;
    return sectors[index];
  }

  function directionLabel(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return emptyValue;
    return `${numeric.toFixed(0)} deg${compassSector(numeric) ? ` ${compassSector(numeric)}` : ''}`;
  }

  function compassPoint(degrees, radius) {
    const radians = (Number(degrees) - 90) * Math.PI / 180;
    return {
      x: 90 + radius * Math.cos(radians),
      y: 90 + radius * Math.sin(radians),
    };
  }

  function compassArcPath(direction, spread) {
    const numericDirection = Number(direction);
    const numericSpread = Number(spread);
    if (!Number.isFinite(numericDirection) || !Number.isFinite(numericSpread) || numericSpread <= 0) return '';
    const span = Math.min(359, Math.max(1, numericSpread));
    const startAngle = numericDirection - span / 2;
    const endAngle = numericDirection + span / 2;
    const start = compassPoint(endAngle, 68);
    const end = compassPoint(startAngle, 68);
    const largeArc = span > 180 ? 1 : 0;
    return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A 68 68 0 ${largeArc} 0 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
  }

  function updateSpotterCompass(direction, spread) {
    const vector = document.getElementById('spotter-wave-vector');
    const arc = document.getElementById('spotter-spread-arc');
    const numericDirection = Number(direction);
    if (vector) {
      if (Number.isFinite(numericDirection)) {
        const outer = compassPoint(numericDirection, 66);
        vector.setAttribute('x1', outer.x.toFixed(2));
        vector.setAttribute('y1', outer.y.toFixed(2));
        vector.setAttribute('x2', '90');
        vector.setAttribute('y2', '90');
        vector.hidden = false;
      } else {
        vector.hidden = true;
      }
    }
    if (arc) arc.setAttribute('d', compassArcPath(direction, spread));
  }

  function updateSpotterOverview(payload) {
    if (!isSpotterBuoy()) return;
    const height = payloadCard(payload, ['significant_wave_height_m', 'wave height']);
    const peakPeriod = payloadCard(payload, ['peak_period_s', 'peak period']);
    const peakDirection = payloadCard(payload, ['peak_direction_deg', 'peak wave direction']);
    const meanDirection = payloadCard(payload, ['mean_direction_deg', 'mean wave direction']);
    const meanSpread = payloadCard(payload, ['mean_directional_spread_deg', 'mean directional spread']);
    const peakSpread = payloadCard(payload, ['peak_directional_spread_deg', 'peak directional spread']);
    const direction = numericCardValue(peakDirection) ?? numericCardValue(meanDirection);
    const spread = numericCardValue(peakSpread) ?? numericCardValue(meanSpread);
    const heightText = height ? metricValue(height.latest, height.unit) : emptyValue;
    const periodText = peakPeriod ? metricValue(peakPeriod.latest, peakPeriod.unit) : emptyValue;
    const directionText = directionLabel(direction);
    setHtml('spotter-wave-readout', `${heightText} @ ${periodText} from ${App.escapeHtml(directionText)}`);
    setText('spotter-sample-time', page.dataset.lastUpdateLabel || payload?.station?.freshness?.last_update || 'N/A');
    const station = payload?.station || {};
    const lat = Number(station.lat);
    const lon = Number(station.lon);
    if (Number.isFinite(lat)) setText('spotter-latitude', lat.toFixed(4));
    if (Number.isFinite(lon)) setText('spotter-longitude', lon.toFixed(4));
    const sampleCount = [height, peakPeriod, peakDirection, meanDirection, meanSpread]
      .map((card) => Number(card?.count))
      .filter((value) => Number.isFinite(value));
    setText('spotter-sample-count', sampleCount.length ? String(Math.max(...sampleCount)) : '--');
    setText('spotter-peak-direction', directionLabel(numericCardValue(peakDirection)));
    setText('spotter-mean-direction', directionLabel(numericCardValue(meanDirection)));
    setText('spotter-directional-spread', Number.isFinite(spread) ? `${spread.toFixed(0)} deg` : '--');
    updateSpotterCompass(direction, spread);
  }

  function finiteNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }

  function normalizeDegrees(value) {
    const numeric = finiteNumber(value);
    if (numeric === null) return null;
    return ((numeric % 360) + 360) % 360;
  }

  function angularDifference(a, b) {
    const first = normalizeDegrees(a);
    const second = normalizeDegrees(b);
    if (first === null || second === null) return null;
    const diff = Math.abs(first - second) % 360;
    return diff > 180 ? 360 - diff : diff;
  }

  function circularMean(values) {
    const numericValues = (values || []).map(normalizeDegrees).filter((value) => value !== null);
    if (!numericValues.length) return null;
    const vector = numericValues.reduce((acc, value) => {
      const radians = value * Math.PI / 180;
      acc.sin += Math.sin(radians);
      acc.cos += Math.cos(radians);
      return acc;
    }, { sin: 0, cos: 0 });
    if (!vector.sin && !vector.cos) return null;
    return normalizeDegrees(Math.atan2(vector.sin, vector.cos) * 180 / Math.PI);
  }

  function arithmeticMean(values) {
    const numericValues = (values || []).map(finiteNumber).filter((value) => value !== null);
    if (!numericValues.length) return null;
    return numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length;
  }

  function quantile(values, q) {
    const numericValues = (values || []).map(finiteNumber).filter((value) => value !== null).sort((a, b) => a - b);
    if (!numericValues.length) return null;
    const pos = (numericValues.length - 1) * q;
    const lower = Math.floor(pos);
    const upper = Math.ceil(pos);
    if (lower === upper) return numericValues[lower];
    return numericValues[lower] + (numericValues[upper] - numericValues[lower]) * (pos - lower);
  }

  function formatSpotterNumber(value, decimals = 1, unit = '') {
    const numeric = finiteNumber(value);
    if (numeric === null) return '--';
    const rounded = numeric.toFixed(decimals);
    return `${rounded}${unit ? ` ${unit}` : ''}`;
  }

  function spotterBearing(value) {
    const numeric = normalizeDegrees(value);
    if (numeric === null) return '--';
    const sector = compassSector(numeric);
    return `${sector ? `${sector} ` : ''}${numeric.toFixed(0)} deg`;
  }

  function formatSpotterTimestamp(value) {
    if (!value) return 'N/A';
    const text = String(value);
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})/);
    if (!match) return text;
    return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]} GST`;
  }

  function compactSpotterDate(value) {
    if (!value) return 'N/A';
    const text = String(value);
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${match[1]}-${match[2]}-${match[3]}` : text;
  }

  function spotterChart(payload, key) {
    return (payload?.charts || []).find((chart) => chart.metric === key) || null;
  }

  function spotterRowsFromPayload(payload) {
    const byTimestamp = new Map();
    (payload?.charts || []).forEach((chart) => {
      if (!spotterMetricKeys.includes(chart.metric)) return;
      (chart.series || []).forEach((point) => {
        if (!point?.x) return;
        if (!byTimestamp.has(point.x)) {
          byTimestamp.set(point.x, {
            timestamp: point.x,
            timeMs: chartTimestampMs(point.x),
          });
        }
        byTimestamp.get(point.x)[chart.metric] = finiteNumber(point.y);
      });
    });
    return Array.from(byTimestamp.values()).sort((a, b) => {
      if (a.timeMs !== null && b.timeMs !== null) return a.timeMs - b.timeMs;
      return String(a.timestamp).localeCompare(String(b.timestamp));
    });
  }

  function spotterMetricValues(rows, key) {
    return (rows || []).map((row) => finiteNumber(row?.[key])).filter((value) => value !== null);
  }

  function spotterRowsHaveAny(rows, keys) {
    return (keys || []).some((key) => spotterMetricValues(rows, key).length > 0);
  }

  function spotterRowsForSparsePanels(rows) {
    if (spotterRowsHaveAny(rows, spotterSparseMetricKeys)) return rows;
    return state.spotterSupplementRows?.length ? state.spotterSupplementRows : rows;
  }

  function spotterDateKey(value) {
    const text = String(value || '');
    const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : text.slice(0, 10);
  }

  function spotterHourKey(value) {
    const text = String(value || '');
    const match = text.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2})/);
    return match ? `${match[1]}T${match[2]}` : text.slice(0, 13);
  }

  function spotterBucketKey(row, aggregation) {
    if (aggregation === '1d') return spotterDateKey(row.timestamp);
    if (aggregation === '1h') return spotterHourKey(row.timestamp);
    return row.timestamp;
  }

  function spotterBucketTimestamp(key, aggregation, fallback) {
    if (aggregation === '1d' && /^\d{4}-\d{2}-\d{2}$/.test(key)) return `${key}T12:00:00+04:00`;
    if (aggregation === '1h' && /^\d{4}-\d{2}-\d{2}T\d{2}$/.test(key)) return `${key}:00:00+04:00`;
    return fallback || key;
  }

  function spotterAggregateRows(rows, aggregation) {
    if (aggregation === 'raw') return [...(rows || [])];
    const groups = new Map();
    (rows || []).forEach((row) => {
      const key = spotterBucketKey(row, aggregation);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    });
    return Array.from(groups.entries()).map(([key, group]) => {
      const first = group[0] || {};
      const row = {
        timestamp: spotterBucketTimestamp(key, aggregation, first.timestamp),
        timeMs: chartTimestampMs(spotterBucketTimestamp(key, aggregation, first.timestamp)),
        sample_count: group.length,
      };
      spotterMetricKeys.forEach((metric) => {
        const values = group.map((item) => item?.[metric]).filter((value) => finiteNumber(value) !== null);
        row[metric] = spotterDirectionKeys.has(metric) ? circularMean(values) : arithmeticMean(values);
      });
      return row;
    }).sort((a, b) => {
      if (a.timeMs !== null && b.timeMs !== null) return a.timeMs - b.timeMs;
      return String(a.timestamp).localeCompare(String(b.timestamp));
    });
  }

  function spotterLatestRow(rows) {
    const preferred = ['significant_wave_height_m', 'peak_period_s', 'peak_direction_deg', 'mean_direction_deg'];
    for (let index = (rows || []).length - 1; index >= 0; index -= 1) {
      const row = rows[index];
      if (preferred.some((key) => finiteNumber(row?.[key]) !== null)) return row;
    }
    return null;
  }

  function spotterSpreadClass(spread) {
    const numeric = finiteNumber(spread);
    if (numeric === null) return '--';
    if (numeric < 30) return 'Narrow';
    if (numeric < 60) return 'Moderate';
    return 'Broad';
  }

  function spotterWaveSystem(row) {
    const period = finiteNumber(row?.peak_period_s);
    const spread = finiteNumber(row?.peak_directional_spread_deg ?? row?.mean_directional_spread_deg);
    const periodText = period === null ? 'Period unavailable' : (period >= 10 ? 'Long-period' : 'Short-period');
    const spreadText = spread === null ? 'spread unavailable' : `${spotterSpreadClass(spread).toLowerCase()} spread`;
    return `${periodText}, ${spreadText}`;
  }

  function spotterGapStats(rows) {
    const deltas = [];
    let previous = null;
    (rows || []).forEach((row) => {
      const ms = row?.timeMs;
      if (ms === null || ms === undefined) return;
      if (previous !== null) {
        const delta = ms - previous;
        if (Number.isFinite(delta) && delta > 0) deltas.push(delta);
      }
      previous = ms;
    });
    const medianDelta = median(deltas);
    const threshold = medianDelta ? medianDelta * 2.75 : null;
    return {
      unique: (rows || []).length,
      gaps: threshold ? deltas.filter((delta) => delta > threshold).length : 0,
      medianDelta,
    };
  }

  function spotterSeaState(value) {
    const numeric = finiteNumber(value);
    if (numeric === null) return null;
    return spotterSeaStateBins.find((bin) => numeric >= bin.min && numeric < bin.max) || null;
  }

  function spotterWaveBin(value) {
    const numeric = finiteNumber(value);
    if (numeric === null) return null;
    return spotterWaveBins.find((bin) => numeric >= bin.min && numeric < bin.max) || null;
  }

  function spotterEmpty(id, message) {
    const host = document.getElementById(id);
    if (!host) return;
    if (window.Plotly && (host.data || host._fullLayout)) Plotly.purge(host);
    host.innerHTML = `<div class="spotter-empty">${App.escapeHtml(message)}</div>`;
  }

  function spotterHasTraceData(trace) {
    if (!trace) return false;
    if (trace.type === 'barpolar') return Array.isArray(trace.r) && trace.r.some((value) => Number(value) > 0);
    if (trace.type === 'histogram') return Array.isArray(trace.x) && trace.x.length > 0;
    if (trace.type === 'box') return Array.isArray(trace.y) && trace.y.length > 0;
    return (Array.isArray(trace.x) && trace.x.length > 0) || (Array.isArray(trace.y) && trace.y.length > 0);
  }

  function spotterBaseLayout(layout = {}) {
    return {
      margin: { t: 18, r: 22, b: 48, l: 58 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#334155', size: 11 },
      colorway: ['#6d28d9', '#0f766e', '#2563eb', '#d97706', '#be185d', '#64748b'],
      hovermode: 'closest',
      ...layout,
    };
  }

  function spotterPlot(id, traces, layout = {}, emptyMessage = 'No samples are present for this figure in the selected window.') {
    const host = document.getElementById(id);
    if (!host || !window.Plotly) return;
    const usableTraces = (traces || []).filter(spotterHasTraceData);
    if (!usableTraces.length) {
      spotterEmpty(id, emptyMessage);
      return;
    }
    host.innerHTML = '';
    Plotly.react(host, usableTraces, spotterBaseLayout(layout), spotterPlotConfig)
      .then(() => Plotly.Plots.resize(host));
  }

  function renderSpotterSummary(payload, rows) {
    const station = payload?.station || {};
    const latest = spotterLatestRow(rows);
    const direction = finiteNumber(latest?.peak_direction_deg) ?? finiteNumber(latest?.mean_direction_deg);
    const spread = finiteNumber(latest?.peak_directional_spread_deg) ?? finiteNumber(latest?.mean_directional_spread_deg);
    const heightText = formatSpotterNumber(latest?.significant_wave_height_m, 2, 'm');
    const periodText = formatSpotterNumber(latest?.peak_period_s, 1, 's');
    setText('spotter-sample-time', formatSpotterTimestamp(latest?.timestamp || page.dataset.lastUpdateIso));
    setText('spotter-wave-readout', `${heightText} @ ${periodText} from ${spotterBearing(direction)}`);
    setText('spotter-wave-caption', latest ? `Latest valid wave observation: ${formatSpotterTimestamp(latest.timestamp)}.` : 'No valid wave observation in the selected window.');
    setText('spotter-station-name', station.name || page.querySelector('.station-heading h1')?.textContent || 'Spotter buoy');
    const first = rows?.[0]?.timestamp;
    const last = rows?.[rows.length - 1]?.timestamp;
    setText('spotter-station-range', first && last ? `${formatSpotterTimestamp(first)} to ${formatSpotterTimestamp(last)}` : 'No timestamp range available.');
    const lat = finiteNumber(station.lat);
    const lon = finiteNumber(station.lon);
    setText('spotter-latitude', lat === null ? '--' : lat.toFixed(4));
    setText('spotter-longitude', lon === null ? '--' : lon.toFixed(4));
    setText('spotter-direction-headline', spotterBearing(direction));
    setText('spotter-directional-spread-card', spread === null ? '--' : `${spread.toFixed(0)} deg`);
    setText('spotter-spread-class', spotterSpreadClass(spread));
    setText('spotter-peak-direction', spotterBearing(finiteNumber(latest?.peak_direction_deg)));
    setText('spotter-mean-direction', spotterBearing(finiteNumber(latest?.mean_direction_deg)));
    setText('spotter-directional-spread', spread === null ? '--' : `${spread.toFixed(0)} deg (${spotterSpreadClass(spread)})`);
    setText('spotter-wave-system', latest ? spotterWaveSystem(latest) : '--');
    updateSpotterCompass(direction, spread);

    const validHs = spotterMetricValues(rows, 'significant_wave_height_m').length;
    const gaps = spotterGapStats(rows);
    const sourcePoints = finiteNumber(payload?.sampling?.source_points);
    setText('spotter-valid-count', String(validHs));
    setText('spotter-unique-count', String(sourcePoints || gaps.unique));
    setText('spotter-gap-count', String(gaps.gaps));
    setText('spotter-coverage-period', state.spotterPeriod);
  }

  function renderSpotterTimeline(rows) {
    const hsValues = spotterMetricValues(rows, 'significant_wave_height_m');
    if (!hsValues.length) {
      spotterEmpty('spotter-timeline', 'No significant wave height samples are present in MongoDB for the selected window.');
      return;
    }
    const x = rows.map((row) => row.timestamp);
    const maxHs = Math.max(...hsValues);
    const focusedMax = quantile(hsValues, 0.96) || maxHs;
    const yMax = state.spotterFullRange ? Math.max(1, Math.ceil((maxHs + 0.25) * 2) / 2) : Math.max(1, focusedMax * 1.18);
    const shapes = spotterSeaStateBins.map((bin) => ({
      type: 'rect',
      xref: 'paper',
      yref: 'y',
      x0: 0,
      x1: 1,
      y0: bin.min,
      y1: Number.isFinite(bin.max) ? Math.min(bin.max, yMax) : yMax,
      fillcolor: hexToRgba(bin.color, 0.18),
      line: { width: 0 },
      layer: 'below',
    })).filter((shape) => shape.y0 < yMax);
    spotterPlot('spotter-timeline', [
      {
        x,
        y: rows.map((row) => row.significant_wave_height_m),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Significant wave height Hs',
        line: { color: '#6d28d9', width: 2.6 },
        marker: { size: 5, color: '#6d28d9' },
        xaxis: 'x',
        yaxis: 'y',
        hovertemplate: '%{x}<br>Hs %{y:.2f} m<extra></extra>',
      },
      {
        x,
        y: rows.map((row) => row.peak_period_s),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Peak period Tp',
        line: { color: '#0f766e', width: 2.2 },
        marker: { size: 4 },
        xaxis: 'x2',
        yaxis: 'y2',
        hovertemplate: '%{x}<br>Tp %{y:.2f} s<extra></extra>',
      },
      {
        x,
        y: rows.map((row) => row.mean_period_s),
        type: 'scatter',
        mode: 'lines',
        name: 'Mean period Tm',
        line: { color: '#64748b', width: 2, dash: 'dot' },
        xaxis: 'x2',
        yaxis: 'y2',
        hovertemplate: '%{x}<br>Tm %{y:.2f} s<extra></extra>',
      },
      {
        x,
        y: rows.map((row) => normalizeDegrees(row.peak_direction_deg)),
        type: 'scatter',
        mode: 'markers',
        name: 'Peak wave direction',
        marker: { size: 7, color: rows.map((row) => normalizeDegrees(row.peak_direction_deg)), colorscale: 'Turbo', cmin: 0, cmax: 360, showscale: false },
        xaxis: 'x3',
        yaxis: 'y3',
        hovertemplate: '%{x}<br>Peak direction %{y:.0f} deg<extra></extra>',
      },
    ], {
      grid: { rows: 3, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
      margin: { t: 16, r: 28, b: 50, l: 62 },
      shapes,
      xaxis: { showticklabels: false, gridcolor: 'rgba(91,101,118,.12)' },
      xaxis2: { showticklabels: false, gridcolor: 'rgba(91,101,118,.12)', matches: 'x' },
      xaxis3: { gridcolor: 'rgba(91,101,118,.12)', matches: 'x' },
      yaxis: { title: 'Hs (m)', range: [0, yMax], gridcolor: 'rgba(91,101,118,.12)' },
      yaxis2: { title: 'Period (s)', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis3: { title: 'Direction', range: [0, 360], tickvals: [0, 90, 180, 270, 360], ticktext: ['N/0', 'E/90', 'S/180', 'W/270', 'N/360'], gridcolor: 'rgba(91,101,118,.12)' },
      legend: { orientation: 'h', y: 1.06, x: 0, font: { size: 11 } },
      showlegend: true,
    });
  }

  function renderSpotterSeaStateBars(rows) {
    const values = spotterMetricValues(rows, 'significant_wave_height_m');
    if (!values.length) {
      spotterEmpty('spotter-sea-state-bars', 'No significant wave height samples are present for category share.');
      return;
    }
    const counts = new Map(spotterSeaStateBins.map((bin) => [bin.label, 0]));
    values.forEach((value) => {
      const bin = spotterSeaState(value);
      if (bin) counts.set(bin.label, counts.get(bin.label) + 1);
    });
    const bins = [...spotterSeaStateBins].reverse();
    const percentages = bins.map((bin) => (counts.get(bin.label) || 0) * 100 / values.length);
    spotterPlot('spotter-sea-state-bars', [{
      x: percentages,
      y: bins.map((bin) => bin.label),
      type: 'bar',
      orientation: 'h',
      marker: { color: bins.map((bin) => bin.color) },
      text: percentages.map((value) => `${value.toFixed(1)}%`),
      textposition: 'auto',
      hovertemplate: '%{y}<br>%{x:.1f}%<extra></extra>',
    }], {
      margin: { t: 8, r: 20, b: 44, l: 82 },
      xaxis: { title: 'Share (%)', range: [0, Math.max(10, Math.ceil(Math.max(...percentages) / 10) * 10)], gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { automargin: true },
      showlegend: false,
    });
  }

  function renderSpotterWaveRose(rows) {
    const sectorWidth = 360 / spotterSectorCount;
    const sectors = Array.from({ length: spotterSectorCount }, (_, index) => index * sectorWidth);
    const totals = spotterWaveBins.map(() => Array(spotterSectorCount).fill(0));
    let totalWeight = 0;
    (rows || []).forEach((row) => {
      const direction = normalizeDegrees(row.peak_direction_deg ?? row.mean_direction_deg);
      const height = finiteNumber(row.significant_wave_height_m);
      const bin = spotterWaveBin(height);
      if (direction === null || height === null || !bin) return;
      const sectorIndex = Math.round(direction / sectorWidth) % spotterSectorCount;
      const binIndex = spotterWaveBins.indexOf(bin);
      const weight = state.spotterRoseMode === 'energy' ? height * height : 1;
      totals[binIndex][sectorIndex] += weight;
      totalWeight += weight;
    });
    if (!totalWeight) {
      spotterEmpty('spotter-wave-rose', 'No wave direction and wave height pairs are present for the selected window.');
      return;
    }
    const traces = spotterWaveBins.map((bin, binIndex) => ({
      type: 'barpolar',
      r: totals[binIndex].map((value) => value * 100 / totalWeight),
      theta: sectors,
      width: sectorWidth,
      name: `Wave ${bin.label}`,
      marker: { color: bin.color, line: { color: 'rgba(255,255,255,.75)', width: 0.6 } },
      hovertemplate: `%{theta:.0f} deg<br>${App.escapeHtml(bin.label)} %{r:.2f}%<extra></extra>`,
    }));
    spotterPlot('spotter-wave-rose', traces, {
      margin: { t: 16, r: 18, b: 34, l: 18 },
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        angularaxis: { direction: 'clockwise', rotation: 90, tickfont: { size: 11 } },
        radialaxis: { ticksuffix: '%', gridcolor: 'rgba(91,101,118,.14)', angle: 90, tickfont: { size: 10 } },
      },
      legend: { orientation: 'h', y: -0.08, x: 0, font: { size: 11 } },
      showlegend: true,
    });
  }

  function renderSpotterRegime(rows) {
    const pairs = (rows || []).filter((row) => finiteNumber(row.significant_wave_height_m) !== null && finiteNumber(row.peak_period_s) !== null);
    if (!pairs.length) {
      spotterEmpty('spotter-regime-scatter', 'No Hs and Tp pairs are present for the selected window.');
      return;
    }
    spotterPlot('spotter-regime-scatter', [{
      x: pairs.map((row) => row.peak_period_s),
      y: pairs.map((row) => row.significant_wave_height_m),
      type: 'scatter',
      mode: 'markers',
      name: 'Wave samples',
      marker: {
        size: pairs.map((row) => Math.max(7, Math.min(24, (finiteNumber(row.peak_directional_spread_deg ?? row.mean_directional_spread_deg) || 35) / 3.5))),
        color: pairs.map((row) => normalizeDegrees(row.peak_direction_deg)),
        colorscale: 'Turbo',
        cmin: 0,
        cmax: 360,
        opacity: 0.82,
        line: { color: '#ffffff', width: 0.7 },
        colorbar: { title: { text: 'Peak dir (deg)' }, thickness: 12, len: 0.78, outlinewidth: 0 },
      },
      hovertemplate: 'Tp %{x:.2f} s<br>Hs %{y:.2f} m<br>Peak dir %{marker.color:.0f} deg<extra></extra>',
    }], {
      margin: { t: 12, r: 74, b: 50, l: 58 },
      shapes: [
        { type: 'rect', xref: 'x', yref: 'paper', x0: 0, x1: 8, y0: 0, y1: 1, fillcolor: 'rgba(15,118,110,.08)', line: { width: 0 }, layer: 'below' },
        { type: 'rect', xref: 'x', yref: 'paper', x0: 8, x1: 28, y0: 0, y1: 1, fillcolor: 'rgba(91,33,182,.08)', line: { width: 0 }, layer: 'below' },
        { type: 'line', xref: 'x', yref: 'paper', x0: 8, x1: 8, y0: 0, y1: 1, line: { color: 'rgba(15,118,110,.38)', dash: 'dot', width: 1.4 } },
      ],
      xaxis: { title: 'Peak period Tp (s)', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      yaxis: { title: 'Hs (m)', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      showlegend: false,
    });
  }

  function renderSpotterExceedance(rows) {
    const values = spotterMetricValues(rows, 'significant_wave_height_m').sort((a, b) => a - b);
    if (!values.length) {
      spotterEmpty('spotter-exceedance', 'No significant wave height samples are present for exceedance.');
      return;
    }
    const count = values.length;
    const y = values.map((_, index) => (count - index) * 100 / count);
    spotterPlot('spotter-exceedance', [{
      x: values,
      y,
      type: 'scatter',
      mode: 'lines',
      name: 'Exceedance',
      line: { color: '#6d28d9', width: 3 },
      hovertemplate: 'Threshold %{x:.2f} m<br>Exceedance %{y:.1f}%<extra></extra>',
    }], {
      xaxis: { title: 'Significant wave height Hs (m)', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      yaxis: { title: 'Exceedance (%)', range: [0, 100], gridcolor: 'rgba(91,101,118,.12)' },
      showlegend: false,
    });
  }

  function renderSpotterHistogram(rows) {
    const values = spotterMetricValues(rows, 'significant_wave_height_m');
    if (!values.length) {
      spotterEmpty('spotter-histogram', 'No significant wave height samples are present for the histogram.');
      return;
    }
    spotterPlot('spotter-histogram', [{
      x: values,
      type: 'histogram',
      nbinsx: 28,
      marker: { color: '#8b5cf6', line: { color: '#ffffff', width: 0.7 } },
      hovertemplate: 'Hs %{x:.2f} m<br>Count %{y}<extra></extra>',
    }], {
      xaxis: { title: 'Hs (m)', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      yaxis: { title: 'Count', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      showlegend: false,
    });
  }

  function renderSpotterDailyBox(rows) {
    const points = (rows || []).filter((row) => finiteNumber(row.significant_wave_height_m) !== null);
    if (!points.length) {
      spotterEmpty('spotter-daily-box', 'No significant wave height samples are present for daily box plots.');
      return;
    }
    spotterPlot('spotter-daily-box', [{
      x: points.map((row) => spotterDateKey(row.timestamp)),
      y: points.map((row) => row.significant_wave_height_m),
      type: 'box',
      name: 'Daily Hs',
      boxpoints: 'outliers',
      marker: { color: '#8b5cf6', opacity: 0.72 },
      line: { color: '#6d28d9' },
      hovertemplate: '%{x}<br>Hs %{y:.2f} m<extra></extra>',
    }], {
      xaxis: { title: 'Date', gridcolor: 'rgba(91,101,118,.12)', tickangle: -35 },
      yaxis: { title: 'Hs (m)', gridcolor: 'rgba(91,101,118,.12)', rangemode: 'tozero' },
      showlegend: false,
    });
  }

  function renderSpotterSpreadTimeline(rows) {
    const hasSpread = spotterMetricValues(rows, 'mean_directional_spread_deg').length || spotterMetricValues(rows, 'peak_directional_spread_deg').length;
    if (!hasSpread) {
      spotterEmpty('spotter-spread-timeline', 'No directional spread samples are present for the selected window.');
      return;
    }
    const x = rows.map((row) => row.timestamp);
    spotterPlot('spotter-spread-timeline', [
      {
        x,
        y: rows.map((row) => row.mean_directional_spread_deg),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Mean spread',
        line: { color: '#64748b', width: 2 },
        marker: { size: 4 },
        hovertemplate: '%{x}<br>Mean spread %{y:.1f} deg<extra></extra>',
      },
      {
        x,
        y: rows.map((row) => row.peak_directional_spread_deg),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Peak spread',
        line: { color: '#6d28d9', width: 2.4 },
        marker: { size: 4 },
        hovertemplate: '%{x}<br>Peak spread %{y:.1f} deg<extra></extra>',
      },
    ], {
      xaxis: { gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: 'Spread (deg)', range: [0, 100], gridcolor: 'rgba(91,101,118,.12)' },
      legend: { orientation: 'h', y: 1.1, x: 0 },
      showlegend: true,
    });
  }

  function renderSpotterWindRose(rows) {
    const windRows = (rows || []).filter((row) => finiteNumber(row.wind_speed_m_s) !== null && normalizeDegrees(row.wind_direction_deg) !== null);
    if (!windRows.length) {
      spotterEmpty('spotter-wind-rose', 'No wind speed and wind direction samples are present in MongoDB for the selected window.');
      return;
    }
    const bins = [
      { label: '0-2 m/s', min: 0, max: 2, color: '#c7f3ef' },
      { label: '2-5 m/s', min: 2, max: 5, color: '#8dded9' },
      { label: '5-8 m/s', min: 5, max: 8, color: '#9b7df0' },
      { label: '>8 m/s', min: 8, max: Infinity, color: '#4c1d95' },
    ];
    const sectorWidth = 360 / spotterSectorCount;
    const sectors = Array.from({ length: spotterSectorCount }, (_, index) => index * sectorWidth);
    const totals = bins.map(() => Array(spotterSectorCount).fill(0));
    windRows.forEach((row) => {
      const speed = finiteNumber(row.wind_speed_m_s);
      const direction = normalizeDegrees(row.wind_direction_deg);
      const binIndex = bins.findIndex((bin) => speed >= bin.min && speed < bin.max);
      if (binIndex < 0 || direction === null) return;
      totals[binIndex][Math.round(direction / sectorWidth) % spotterSectorCount] += 1;
    });
    const total = windRows.length;
    spotterPlot('spotter-wind-rose', bins.map((bin, index) => ({
      type: 'barpolar',
      r: totals[index].map((value) => value * 100 / total),
      theta: sectors,
      width: sectorWidth,
      name: bin.label,
      marker: { color: bin.color, line: { color: '#ffffff', width: 0.6 } },
      hovertemplate: `%{theta:.0f} deg<br>${App.escapeHtml(bin.label)} %{r:.2f}%<extra></extra>`,
    })), {
      margin: { t: 16, r: 18, b: 34, l: 18 },
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        angularaxis: { direction: 'clockwise', rotation: 90 },
        radialaxis: { ticksuffix: '%', gridcolor: 'rgba(91,101,118,.14)' },
      },
      legend: { orientation: 'h', y: -0.08, x: 0 },
      showlegend: true,
    });
  }

  function renderSpotterAlignment(rows) {
    const aligned = (rows || []).map((row) => ({
      timestamp: row.timestamp,
      diff: angularDifference(row.wind_direction_deg, row.peak_direction_deg),
      speed: finiteNumber(row.wind_speed_m_s),
    })).filter((row) => row.diff !== null);
    if (!aligned.length) {
      spotterEmpty('spotter-alignment', 'Wind-wave alignment needs both wind direction and peak wave direction samples in MongoDB.');
      return;
    }
    spotterPlot('spotter-alignment', [{
      x: aligned.map((row) => row.timestamp),
      y: aligned.map((row) => row.diff),
      type: 'scatter',
      mode: 'markers',
      marker: {
        size: aligned.map((row) => Math.max(7, Math.min(20, (row.speed || 1) * 2.2))),
        color: aligned.map((row) => row.speed || 0),
        colorscale: 'Viridis',
        showscale: true,
        colorbar: { title: { text: 'Wind (m/s)' }, thickness: 12, outlinewidth: 0 },
        line: { color: '#ffffff', width: 0.7 },
      },
      hovertemplate: '%{x}<br>Angular difference %{y:.1f} deg<extra></extra>',
    }], {
      margin: { t: 12, r: 74, b: 50, l: 58 },
      xaxis: { gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: 'Difference (deg)', range: [0, 180], gridcolor: 'rgba(91,101,118,.12)' },
      showlegend: false,
    });
  }

  function renderSpotterMetTimeline(rows) {
    const traces = [];
    const x = (rows || []).map((row) => row.timestamp);
    if (spotterMetricValues(rows, 'surface_temperature_c').length) {
      traces.push({
        x,
        y: rows.map((row) => row.surface_temperature_c),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Surface temperature',
        line: { color: '#d97706', width: 2 },
        marker: { size: 4 },
        xaxis: 'x',
        yaxis: 'y',
        hovertemplate: '%{x}<br>Temperature %{y:.2f} deg C<extra></extra>',
      });
    }
    if (spotterMetricValues(rows, 'mean_barometric_pressure_hpa').length) {
      traces.push({
        x,
        y: rows.map((row) => row.mean_barometric_pressure_hpa),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Pressure',
        line: { color: '#2563eb', width: 2 },
        marker: { size: 4 },
        xaxis: 'x2',
        yaxis: 'y2',
        hovertemplate: '%{x}<br>Pressure %{y:.2f} hPa<extra></extra>',
      });
    }
    if (spotterMetricValues(rows, 'humidity_pct').length) {
      traces.push({
        x,
        y: rows.map((row) => row.humidity_pct),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Humidity',
        line: { color: '#0f766e', width: 2 },
        marker: { size: 4 },
        xaxis: 'x3',
        yaxis: 'y3',
        hovertemplate: '%{x}<br>Humidity %{y:.1f}%<extra></extra>',
      });
    }
    if (!traces.length) {
      spotterEmpty('spotter-met-timeline', 'No surface temperature, pressure, or humidity samples are present in MongoDB for the selected window.');
      return;
    }
    spotterPlot('spotter-met-timeline', traces, {
      grid: { rows: 3, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
      margin: { t: 16, r: 28, b: 50, l: 70 },
      xaxis: { showticklabels: false, gridcolor: 'rgba(91,101,118,.12)' },
      xaxis2: { showticklabels: false, gridcolor: 'rgba(91,101,118,.12)', matches: 'x' },
      xaxis3: { gridcolor: 'rgba(91,101,118,.12)', matches: 'x' },
      yaxis: { title: 'deg C', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis2: { title: 'hPa', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis3: { title: '%', range: [0, 100], gridcolor: 'rgba(91,101,118,.12)' },
      legend: { orientation: 'h', y: 1.08, x: 0 },
      showlegend: true,
    });
  }

  function renderSpotterTelemetry(rows) {
    const traces = [];
    const x = (rows || []).map((row) => row.timestamp);
    if (spotterMetricValues(rows, 'battery_voltage_v').length) {
      traces.push({
        x,
        y: rows.map((row) => row.battery_voltage_v),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Battery voltage',
        line: { color: '#6d28d9', width: 2.4 },
        marker: { size: 4 },
        yaxis: 'y',
        hovertemplate: '%{x}<br>Voltage %{y:.2f} V<extra></extra>',
      });
    }
    if (spotterMetricValues(rows, 'battery_power_w').length) {
      traces.push({
        x,
        y: rows.map((row) => row.battery_power_w),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Battery power',
        line: { color: '#0f766e', width: 2.2 },
        marker: { size: 4 },
        yaxis: 'y2',
        hovertemplate: '%{x}<br>Power %{y:.2f} W<extra></extra>',
      });
    }
    if (!traces.length) {
      spotterEmpty('spotter-telemetry', 'No battery voltage or battery power samples are present in MongoDB for the selected window.');
      return;
    }
    spotterPlot('spotter-telemetry', traces, {
      margin: { t: 12, r: 64, b: 50, l: 58 },
      xaxis: { gridcolor: 'rgba(91,101,118,.12)' },
      yaxis: { title: 'Voltage (V)', gridcolor: 'rgba(91,101,118,.12)' },
      yaxis2: { title: 'Power (W)', overlaying: 'y', side: 'right', gridcolor: 'rgba(91,101,118,0)' },
      legend: { orientation: 'h', y: 1.08, x: 0 },
      showlegend: true,
    });
  }

  function syncSpotterControls() {
    document.querySelectorAll('#spotter-period-buttons button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.spotterPeriod === state.spotterPeriod);
    });
    const aggregation = document.getElementById('spotter-aggregation-select');
    if (aggregation) aggregation.value = state.spotterAggregation;
    const roseMode = document.getElementById('spotter-rose-mode');
    if (roseMode) roseMode.value = state.spotterRoseMode;
    const fullRange = document.getElementById('spotter-full-range-toggle');
    if (fullRange) fullRange.checked = state.spotterFullRange;
    document.querySelectorAll('#spotter-tabs button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.spotterPanel === state.spotterPanel);
    });
    document.querySelectorAll('.spotter-panel[data-spotter-panel]').forEach((panel) => {
      const active = panel.dataset.spotterPanel === state.spotterPanel;
      panel.classList.toggle('is-active', active);
      panel.hidden = !active;
    });
  }

  function spotterPanelFromHash() {
    const value = String(window.location.hash || '').replace(/^#/, '');
    const aliases = {
      overview: 'overview',
      waves: 'waves',
      'wave-analysis': 'waves',
      met: 'met',
      meteorology: 'met',
      telemetry: 'met',
    };
    return aliases[value] || '';
  }

  function renderSpotterActivePanel() {
    if (!isSpotterBuoy()) return;
    const rawRows = state.spotterRows || [];
    const displayRows = spotterAggregateRows(rawRows, state.spotterAggregation);
    const sparseRows = spotterRowsForSparsePanels(rawRows);
    const sparseDisplayRows = spotterAggregateRows(sparseRows, state.spotterAggregation);
    syncSpotterControls();
    if (state.spotterPanel === 'overview') {
      renderSpotterTimeline(displayRows);
      renderSpotterSeaStateBars(rawRows);
      renderSpotterWaveRose(rawRows);
      renderSpotterRegime(rawRows);
    } else if (state.spotterPanel === 'waves') {
      renderSpotterExceedance(rawRows);
      renderSpotterHistogram(rawRows);
      renderSpotterDailyBox(rawRows);
      renderSpotterSpreadTimeline(displayRows);
    } else if (state.spotterPanel === 'met') {
      renderSpotterWindRose(sparseRows);
      renderSpotterAlignment(sparseRows);
      renderSpotterMetTimeline(sparseDisplayRows);
      renderSpotterTelemetry(sparseDisplayRows);
    }
    scheduleActiveChartResize();
  }

  function renderSpotterDashboard(payload, supplementPayload = state.spotterSupplementPayload) {
    state.spotterPayload = payload;
    state.spotterRows = spotterRowsFromPayload(payload);
    state.spotterSupplementPayload = supplementPayload || null;
    state.spotterSupplementRows = supplementPayload ? spotterRowsFromPayload(supplementPayload) : [];
    renderSpotterSummary(payload, state.spotterRows);
    renderSpotterActivePanel();
  }

  function spotterCacheKey() {
    return [state.spotterPeriod, metricQueryValue(spotterMetricKeys), 'default-display-points'].join('|');
  }

  async function loadSpotterDashboard(force = false) {
    const key = spotterCacheKey();
    const cached = cachedPayload(state.spotterCache, key);
    if (!force && cached) {
      const cachedPayloadValue = cached.payload || cached;
      renderSpotterDashboard(cachedPayloadValue, cached.supplementPayload || null);
      return cachedPayloadValue;
    }
    const requestId = ++state.spotterRequestId;
    ['spotter-timeline', 'spotter-sea-state-bars', 'spotter-wave-rose', 'spotter-regime-scatter'].forEach((id) => {
      spotterEmpty(id, 'Loading Spotter buoy samples from MongoDB.');
    });
    const url = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/timeseries`, window.location.origin);
    url.searchParams.set('period', state.spotterPeriod);
    url.searchParams.set('aggregation', 'raw');
    url.searchParams.set('metrics', metricQueryValue(spotterMetricKeys));
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.spotterRequestId) return null;
    const selectedRows = spotterRowsFromPayload(payload);
    let supplementPayload = null;
    if (state.spotterPeriod !== 'ALL' && !spotterRowsHaveAny(selectedRows, spotterSparseMetricKeys)) {
      const supplementUrl = new URL(`/api/stations/${encodeURIComponent(state.stationId)}/timeseries`, window.location.origin);
      supplementUrl.searchParams.set('period', 'ALL');
      supplementUrl.searchParams.set('aggregation', 'raw');
      supplementUrl.searchParams.set('metrics', metricQueryValue(spotterMetricKeys));
      supplementPayload = await App.fetchJSON(supplementUrl.toString());
      if (requestId !== state.spotterRequestId) return null;
    }
    rememberPayload(state.spotterCache, key, { payload, supplementPayload });
    renderSpotterDashboard(payload, supplementPayload);
    return payload;
  }

  function wireSpotterControls() {
    state.spotterPanel = spotterPanelFromHash() || state.spotterPanel;
    syncSpotterControls();
    document.querySelectorAll('#spotter-period-buttons button').forEach((button) => {
      button.addEventListener('click', () => {
        state.spotterPeriod = button.dataset.spotterPeriod || '30D';
        syncSpotterControls();
        loadSpotterDashboard(true);
      });
    });
    document.getElementById('spotter-aggregation-select')?.addEventListener('change', (event) => {
      state.spotterAggregation = event.target.value || 'raw';
      renderSpotterActivePanel();
    });
    document.getElementById('spotter-rose-mode')?.addEventListener('change', (event) => {
      state.spotterRoseMode = event.target.value || 'energy';
      renderSpotterActivePanel();
    });
    document.getElementById('spotter-full-range-toggle')?.addEventListener('change', (event) => {
      state.spotterFullRange = event.target.checked;
      renderSpotterActivePanel();
    });
    document.querySelectorAll('#spotter-tabs button').forEach((button) => {
      button.addEventListener('click', () => {
        state.spotterPanel = button.dataset.spotterPanel || 'overview';
        if (window.history?.replaceState) {
          window.history.replaceState(null, '', `#${state.spotterPanel}`);
        }
        renderSpotterActivePanel();
      });
    });
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
          <small>Latest</small>
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
      const heading = isUnderwaterStation() ? 'No statistics available' : 'No latest readings';
      const message = payload.message || 'No data was available for the selected display period.';
      container.innerHTML = `<article class="empty-state"><h2>${heading}</h2><p>${App.escapeHtml(message)}</p></article>`;
      updateSpotterOverview(payload);
      renderQuickTrends(payload);
      return;
    }

    container.innerHTML = payload.cards.map((card) => makeCard(card, period)).join('');
    updateSpotterOverview(payload);
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
            <p>Latest ${metricValue(trend.summary?.latest, trend.unit)} &middot; Mean ${displayValue(trend.summary?.mean)} &middot; Min ${displayValue(trend.summary?.min)} &middot; Max ${displayValue(trend.summary?.max)}</p>
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
        <span>Latest ${displayValue(chart.summary.latest)}</span>
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
      <span>Latest mean ${displayValue(chart.summary.latest)}</span>
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
    const quickDateRange = dateAxisRangeForContext('quick');
    if (quickDateRange) {
      layout.xaxis.range = quickDateRange;
      layout.xaxis.autorange = false;
    }
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
          requestTimeseriesLoad();
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
    const xaxis = { title: 'GST', gridcolor: 'rgba(91,101,118,.12)' };
    const advancedDateRange = dateAxisRangeForContext('advanced');
    if (advancedDateRange) {
      xaxis.range = advancedDateRange;
      xaxis.autorange = false;
    }
    Plotly.newPlot(host, traces, {
      margin: { t: 18, r: 18, b: 42, l: 54 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      autosize: true,
      width: hostWidth,
      xaxis,
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
    if (window.Plotly) {
      grid.querySelectorAll('.chart-host').forEach((host) => {
        if (host.data || host._fullLayout) Plotly.purge(host);
      });
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
    url.searchParams.set('max_frames', '120');
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

    const traces = [{
      x,
      y,
      type: 'scatter',
      mode: 'lines',
      name: 'Particle count',
      line: { color: '#5b21b6', width: 2.6, shape: 'hv' },
      hovertemplate: `Size %{x:.4f} ${App.escapeHtml(state.spectraPayload?.size_unit || '')}<br>Count %{y:.4f}<extra></extra>`,
    }];
    const layout = {
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
      transition: { duration: 0 },
    };
    const config = { displaylogo: false, responsive: true };
    if (host.data || host._fullLayout) {
      Plotly.react(host, traces, layout, config);
    } else {
      host.innerHTML = '';
      Plotly.newPlot(host, traces, layout, config);
    }
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
    if (timeseriesLoadTimer) {
      window.clearTimeout(timeseriesLoadTimer);
      timeseriesLoadTimer = null;
    }
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
    if (isFidasStation()) url.searchParams.set('display_points', '360');
    if (isFidasStation()) url.searchParams.set('clean', state.fidasClean ? 'true' : 'false');
    if (state.selectedMetrics.length || state.metricsTouched) url.searchParams.set('metrics', metricQueryValue(state.selectedMetrics));
    const payload = await App.fetchJSON(url.toString());
    if (requestId !== state.timeseriesRequestId) return;
    rememberPayload(state.timeseriesCache, key, payload);
    renderTimeseriesPayload(payload);
    return payload;
  }

  function requestTimeseriesLoad() {
    if (!isFidasStation()) {
      return loadTimeseries();
    }
    if (timeseriesLoadTimer) window.clearTimeout(timeseriesLoadTimer);
    timeseriesLoadTimer = window.setTimeout(() => {
      timeseriesLoadTimer = null;
      loadTimeseries();
    }, 60);
    return undefined;
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
    document.addEventListener('click', (event) => {
      const dateControl = document.getElementById('date-range-control');
      const calendar = document.getElementById('date-calendar-popover');
      if (!dateControl || !calendar || calendar.hidden) return;
      if (!dateControl.contains(event.target)) calendar.hidden = true;
    });
    const calendar = document.getElementById('date-calendar-popover');
    calendar?.addEventListener('click', (event) => {
      event.stopPropagation();
      const nav = event.target.closest?.('[data-calendar-nav]');
      if (nav) {
        if (nav.disabled) return;
        event.preventDefault();
        state.calendarMonth = shiftAvailableMonth(state.calendarMonth, Number(nav.dataset.calendarNav || 0));
        renderDateCalendar();
        return;
      }
      const target = event.target.closest?.('[data-date-value]');
      if (!target || target.disabled) return;
      event.preventDefault();
      setActiveRangeDate(state.activeDatePart, target.dataset.dateValue);
      calendar.hidden = true;
    });
    calendar?.addEventListener('change', (event) => {
      const selector = event.target.closest?.('[data-calendar-select]');
      if (!selector) return;
      const [currentYear, currentMonth] = clampCalendarMonth(state.calendarMonth).split('-').map(Number);
      const nextYear = selector.dataset.calendarSelect === 'year' ? Number(selector.value) : currentYear;
      const nextMonth = selector.dataset.calendarSelect === 'month'
        ? Number(selector.value)
        : closestMonthForYear(nextYear, currentMonth);
      state.calendarMonth = clampCalendarMonth(monthKeyFromParts(nextYear, nextMonth));
      renderDateCalendar();
    });
    document.querySelectorAll('#period-buttons button').forEach((button) => {
      button.addEventListener('click', () => {
        setActivePeriod(button.dataset.period, { userSelected: true });
      });
    });
    document.getElementById('aggregation-select')?.addEventListener('change', (event) => {
      state.aggregation = event.target.value;
      if (!isBuoyProfilePanel()) requestTimeseriesLoad();
    });
    document.getElementById('split-sensors-toggle')?.addEventListener('change', (event) => {
      state.splitSensors = event.target.checked;
      requestTimeseriesLoad();
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
      if (state.activeTab === 'advanced') {
        if (state.advancedPanel === 'spectra') {
          loadFidasSpectra(true).then(scheduleActiveChartResize);
        } else {
          requestTimeseriesLoad();
        }
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
        if (state.activeTab === 'advanced' && (isFidasStation() || !state.timeseriesPayload)) {
          reloadAdvancedWindow();
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
    const advancedLayout = document.querySelector('#advanced-view .advanced-layout');
    if (advancedLayout) {
      advancedLayout.classList.toggle('is-spectra-full', state.stationTemplate === 'fidas' && panelName === 'spectra');
    }
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
    if (isSpotterBuoy()) {
      wireSpotterControls();
      await loadSpotterDashboard();
      return;
    }
    syncPeriodControls();
    if (shouldUseDateRangeControls()) {
      await initDateRangeControls();
      syncPeriodControls();
      await loadLatest();
      if (!isFidasStation()) requestTimeseriesLoad();
      return;
    }

    const latestReady = loadLatest();
    if (!isFidasStation()) {
      requestTimeseriesLoad();
    }
    await latestReady;
  }

  init().catch((error) => {
    console.error(error);
  });
})();
