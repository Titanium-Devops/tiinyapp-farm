const byId = id => document.getElementById(id);

export function textElement(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = String(value);
  return element;
}

function link(className, value, href) {
  const anchor = textElement('a', className, value);
  anchor.href = href;
  return anchor;
}

function svgIcon(kind) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ic');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('stroke-width', '1.75');
  const paths = kind === 'check'
    ? ['m5 12 5 5L20 7']
    : ['M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 18.333z', 'M4.012 16.737A2 2 0 0 1 3 15V5c0-1.1.9-2 2-2h10c.75 0 1.158.385 1.5 1'];
  for (const value of paths) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', value);
    svg.append(path);
  }
  return svg;
}

function copyButton(command) {
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.copy = '';
  button.setAttribute('aria-label', 'Copy command');
  button.dataset.command = command;
  button.append(svgIcon('copy'));
  return button;
}

function categoryNames(app, config) {
  const found = new Set(app.tags.map(tag => config.map[tag]).filter(Boolean));
  return config.order.filter(name => found.has(name));
}

function permission(value) {
  return value === 'device' ? 'Your Tiiny' : value.charAt(0).toUpperCase() + value.slice(1);
}

function needs(app) {
  return app.requires.device.models.length ? 'needs ' + app.requires.device.models.join(', ') : 'no named models';
}

function chip(value) {
  return textElement('span', 'chip', value);
}

function catalogTile(app, config) {
  const tile = document.createElement('article');
  tile.className = 'tile';
  const art = document.createElement('div');
  art.className = 'art';
  if (app.media?.header) {
    const header = document.createElement('img');
    header.className = 'art-image';
    header.src = app.media.header;
    header.alt = '';
    art.append(header);
  }
  if (app.media?.icon) {
    const icon = document.createElement('img');
    icon.className = 'icon';
    icon.src = app.media.icon;
    icon.alt = '';
    art.append(icon);
  }
  const body = document.createElement('div');
  body.className = 'body';
  const categories = categoryNames(app, config);
  body.append(textElement('span', 'cat-tag', categories[0] || 'Developer tools'));
  const heading = document.createElement('h2');
  heading.className = 'name';
  heading.append(link('', app.name, '/apps/' + encodeURIComponent(app.id) + '/'));
  body.append(heading, textElement('p', 'pitch', app.pitch),
    textElement('div', 'meta', `v${app.version} · by ${app.author.name} · ${needs(app)}`));
  const chips = document.createElement('div');
  chips.className = 'chips';
  for (const value of app.permissions) chips.append(chip(permission(value)));
  body.append(chips);
  const foot = document.createElement('div');
  foot.className = 'foot';
  const command = 'farm install ' + app.id;
  const commandBox = document.createElement('div');
  commandBox.className = 'cmd';
  commandBox.append(textElement('span', '', command), copyButton(command));
  foot.append(commandBox, link('btn hay', 'Install', '/apps/' + encodeURIComponent(app.id) + '/'));
  body.append(foot);
  tile.append(art, body);
  return tile;
}

function setupCopyButtons() {
  document.addEventListener('click', async event => {
    const button = event.target.closest?.('[data-copy]');
    if (!button) return;
    const command = button.dataset.command || button.closest('.cmd')?.querySelector('span')?.textContent || '';
    try {
      await navigator.clipboard.writeText(command);
      button.replaceChildren(svgIcon('check'));
      window.setTimeout(() => button.replaceChildren(svgIcon('copy')), 1200);
    } catch {
      button.setAttribute('aria-label', 'Could not copy command');
    }
  });
}

function setupHome() {
  const input = byId('q-home');
  if (!input) return;
  const rows = [...document.querySelectorAll('[data-catalog-search]')];
  const count = byId('count-home');
  const empty = byId('empty-home');
  const render = () => {
    const query = input.value.trim().toLowerCase();
    let visible = 0;
    for (const row of rows) {
      row.hidden = Boolean(query) && !row.dataset.catalogSearch.includes(query);
      if (!row.hidden) visible += 1;
    }
    count.textContent = `${visible} of ${rows.length}`;
    empty.hidden = visible !== 0;
  };
  input.addEventListener('input', render);
  render();
}

async function setupCatalog() {
  const grid = byId('catalog-grid');
  if (!grid) return;
  const [appsResponse, categoriesResponse] = await Promise.all([fetch('/catalog.json'), fetch('/categories.json')]);
  if (!appsResponse.ok || !categoriesResponse.ok) throw new Error('Catalog data could not be loaded.');
  const apps = await appsResponse.json();
  const config = await categoriesResponse.json();
  for (const app of apps) app.categories = categoryNames(app, config);
  const params = new URLSearchParams(location.search);
  const input = byId('q-catalog');
  input.value = params.get('q') || '';
  let selected = config.order.includes(params.get('cat')) ? params.get('cat') : '';
  const categoryBar = byId('catalog-categories');
  const available = config.order.filter(name => apps.some(app => app.categories.includes(name)));
  categoryBar.replaceChildren();
  for (const name of ['All', ...available]) {
    const button = textElement('button', 'cat', name);
    button.type = 'button';
    button.dataset.cat = name === 'All' ? '' : name;
    button.setAttribute('aria-pressed', String(button.dataset.cat === selected));
    categoryBar.append(button);
  }
  const render = () => {
    const query = input.value.trim().toLowerCase();
    const list = apps.filter(app => (!selected || app.categories.includes(selected)) && (!query ||
      [app.name, app.pitch, app.author.name, ...app.tags, ...app.categories].join(' ').toLowerCase().includes(query)));
    grid.replaceChildren(...list.map(app => catalogTile(app, config)));
    byId('count-catalog').textContent = `${list.length} of ${apps.length}`;
    byId('empty-catalog').hidden = list.length !== 0;
    for (const button of categoryBar.querySelectorAll('.cat')) button.setAttribute('aria-pressed', String(button.dataset.cat === selected));
    const url = new URL(location.href);
    query ? url.searchParams.set('q', input.value.trim()) : url.searchParams.delete('q');
    selected ? url.searchParams.set('cat', selected) : url.searchParams.delete('cat');
    history.replaceState(null, '', url);
  };
  input.addEventListener('input', render);
  categoryBar.addEventListener('click', event => {
    const button = event.target.closest?.('.cat');
    if (button) { selected = button.dataset.cat; render(); }
  });
  render();
}

if (typeof document !== 'undefined') {
  setupCopyButtons();
  setupHome();
  setupCatalog().catch(error => {
    const empty = byId('empty-catalog');
    if (empty) { empty.hidden = false; empty.textContent = error.message; }
  });
}
