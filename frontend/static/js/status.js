(() => {
  const page = document.querySelector('.status-page');
  if (!page) return;

  function buildIssueModal(row) {
    const issueItems = row.issues?.length
      ? row.issues
          .map((issue, index) => `
            <article class="issue-item">
              <strong>Issue ${index + 1}</strong>
              <div>${App.escapeHtml(issue)}</div>
            </article>
          `)
          .join('')
      : '<article class="issue-item"><strong>No issues</strong><div>This station does not currently have active issues.</div></article>';

    return `
      <article class="modal-panel">
        <header class="modal-head">
          <div>
            <span class="eyebrow">Station issues</span>
            <h2>${App.escapeHtml(row.name)}</h2>
            <p>${App.escapeHtml(row.device_label)} · ${App.escapeHtml(row.status)} · Last update ${App.escapeHtml(row.last_update)}</p>
          </div>
          <button class="ghost-button" data-close-modal>Close</button>
        </header>
        <div class="drawer-kv">
          <div><span>Station</span><strong>${App.escapeHtml(row.name)}</strong></div>
          <div><span>Status</span><strong>${App.escapeHtml(row.status)}</strong></div>
          <div><span>Device</span><strong>${App.escapeHtml(row.device_label)}</strong></div>
          <div><span>Issue count</span><strong>${row.issue_count || 0}</strong></div>
        </div>
        <section class="issue-list">${issueItems}</section>
        <footer class="modal-actions">
          <a class="primary-button" href="/station/${encodeURIComponent(row.station_id)}">Open station</a>
          <button class="ghost-button" data-close-modal>Done</button>
        </footer>
      </article>
    `;
  }

  function renderRows(rows) {
    renderGroups([{ label: 'Stations', count: rows.length, rows }]);
  }

  function issueCell(row) {
    return row.issues.length
      ? `<button class="ghost-button status-issues-button" type="button" data-row="${encodeURIComponent(JSON.stringify(row))}">View ${row.issue_count} issue${row.issue_count === 1 ? '' : 's'}</button>`
      : '<span class="table-meta">No issues</span>';
  }

  function renderGroups(groups) {
    const tbody = document.querySelector('#status-table tbody');
    const safeGroups = (groups || []).filter((group) => Array.isArray(group.rows) && group.rows.length);
    tbody.innerHTML = safeGroups
      .map((group) => `
        <tr class="status-group-row">
          <th colspan="6">
            <span>${App.escapeHtml(group.label)}</span>
            <strong>${App.escapeHtml(String(group.count ?? group.rows.length))}</strong>
          </th>
        </tr>
        ${group.rows.map((row) => `
        <tr>
          <td><strong>${App.escapeHtml(row.name)}</strong><br /><span class="table-meta">${App.escapeHtml(row.device_label)}</span></td>
          <td>${App.escapeHtml(row.device_label)}</td>
          <td><span class="status-pill ${App.escapeHtml(row.status_class || '')}">${App.escapeHtml(row.status)}</span></td>
          <td>${App.escapeHtml(row.last_update)}</td>
          <td>${issueCell(row)}</td>
          <td><a class="ghost-button status-open-link" href="/station/${encodeURIComponent(row.station_id)}">Open</a></td>
        </tr>
      `).join('')}
      `)
      .join('');
  }

  function updateSummary(summary) {
    document.getElementById('status-total').textContent = summary.total;
    document.getElementById('status-healthy').textContent = summary.healthy;
    document.getElementById('status-maintenance').textContent = summary.maintenance;
    document.getElementById('status-disabled').textContent = summary.disabled;
  }

  async function refreshStatus() {
    const payload = await App.fetchJSON('/api/status');
    updateSummary(payload.summary);
    renderGroups(payload.groups || [{ label: 'Stations', rows: payload.rows || [] }]);
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('.status-issues-button');
    if (!button) return;
    const row = JSON.parse(decodeURIComponent(button.dataset.row));
    App.openModal(buildIssueModal(row));
  });

  document.getElementById('refresh-status')?.addEventListener('click', refreshStatus);

  try {
    const initialSummary = JSON.parse(page.dataset.statusSummary || '{}');
    const initialRows = JSON.parse(page.dataset.statusRows || '[]');
    const initialGroups = JSON.parse(page.dataset.statusGroups || '[]');
    if (initialSummary && typeof initialSummary === 'object') updateSummary(initialSummary);
    if (Array.isArray(initialGroups) && initialGroups.length) {
      renderGroups(initialGroups);
    } else if (Array.isArray(initialRows)) {
      renderRows(initialRows);
    }
  } catch (error) {
    console.error(error);
  }
})();
