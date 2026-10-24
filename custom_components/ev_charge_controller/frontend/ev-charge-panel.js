/* Native EV Charging panel. Uses HA's state stream; no polling or history requests. */
const DOMAIN = 'ev_charge_controller';
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const numeric = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
const instant = value => value ? Date.parse(value) : NaN;
const MODES = {
  cheap_top_up: ['Cheap top-up', 'Charge below your price limit.', 'mdi:cash-multiple'],
  deadline: ['Charge by deadline', 'Ready when you need it.', 'mdi:clock-outline'],
  flexible: ['Flexible target', 'Reach a target at cheap rates.', 'mdi:bullseye-arrow'],
};
const KEYS = ['status','plan','mode','deadline','target_percent','max_cheap_rate','hard_price_ceiling','boost','automatic_control','monitoring_only','resume'];
const STYLE = `
:host{display:block;min-height:100%;color:var(--ev-text);background:var(--ev-bg);font-family:var(--ha-font-family-body,Roboto,Arial,sans-serif);--ev-bg:#0d1b26;--ev-surface:#102330;--ev-text:#edf3fa;--ev-muted:#b2c7db;--ev-line:#294353;--ev-input:#102331;--ev-accent:#17c5e7;--ev-green:#30dbb0;--ev-amber:#ffb631;--ev-error:#ff9393;--ev-button-text:#062432;color-scheme:dark}
:host([theme=light]){--ev-bg:#f6f8fa;--ev-surface:#fff;--ev-text:#172d3d;--ev-muted:#526a7c;--ev-line:#cbd8e1;--ev-input:#f7fafc;--ev-accent:#007c98;--ev-green:#087f66;--ev-amber:#946000;--ev-error:#bb3434;--ev-button-text:#fff;color-scheme:light}
*{box-sizing:border-box}button,input,select{font:inherit}button,input,select,summary{outline-offset:4px}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--ev-accent)}button{min-height:42px;cursor:pointer;color:var(--ev-text);border:1px solid var(--ev-line);background:transparent;border-radius:6px;padding:10px 16px;font-size:14px;font-weight:600}button:hover{background:color-mix(in srgb,var(--ev-accent) 7%,transparent)}button:disabled{opacity:.5;cursor:default}.primary{background:var(--ev-accent);border-color:var(--ev-accent);color:var(--ev-button-text)}.primary:hover{background:color-mix(in srgb,var(--ev-accent) 85%,white)}.quiet{border:0;padding:5px 0;min-height:32px;color:var(--ev-accent)}ha-icon{--mdc-icon-size:22px;width:22px;height:22px;flex-shrink:0}.shell-header{padding:18px 24px 0;border-bottom:1px solid var(--ev-line);display:grid;grid-template-columns:1fr auto;gap:3px 20px}.heading{display:flex;gap:14px;align-items:center}.heading h1{font-size:25px;letter-spacing:-.6px;margin:0 0 3px;line-height:1.2}.vehicle{font-size:14px;font-weight:600;line-height:1.2}.vehicle-select{display:flex;align-items:center;gap:10px}.vehicle-select select{max-width:260px;background:var(--ev-bg);color:var(--ev-text);border:1px solid var(--ev-line);border-radius:4px;padding:6px;font-size:14px}.menu{display:none;padding:8px;min-width:42px}.clock{color:var(--ev-muted);font-size:13px;align-self:start;padding-top:3px;text-align:right}.tabs{grid-column:1/-1;display:flex;gap:12px;padding-bottom:10px}.tabs button{font-weight:500;padding:8px 20px;min-width:105px;min-height:38px}.tabs button[aria-selected=true]{color:var(--ev-accent);border-color:var(--ev-accent);background:color-mix(in srgb,var(--ev-accent) 4%,transparent)}main{max-width:1510px;margin:auto;padding:22px 22px 18px}h2{font-size:22px;line-height:1.3;margin:0 0 6px;letter-spacing:-.25px}h3{font-size:17px;margin:0 0 6px}p{margin:0;line-height:1.5}.muted,.helper{color:var(--ev-muted)}.helper{font-size:13px;line-height:1.45}.surface{border:1px solid var(--ev-line);background:var(--ev-surface);border-radius:9px;padding:20px;min-width:0}.overview-grid{display:grid;grid-template-columns:minmax(300px,1fr) minmax(0,1.8fr);gap:22px;align-items:start}.outlook{padding:6px 16px 0}.outlook>.helper{margin-bottom:16px}.outlook .journey{margin-top:16px;margin-bottom:14px}.outlook .journey-item{padding-bottom:18px}.outlook .journey-item:last-child{padding-bottom:0}.outlook .facts{margin-top:16px}.journey{margin:22px 0 18px;padding-left:19px;border-left:2px solid var(--ev-line)}.journey-item{position:relative;padding:0 0 22px 15px}.journey-item:last-child{padding-bottom:0}.journey-item::before{content:'';position:absolute;left:-27px;top:7px;width:15px;height:15px;border-radius:50%;background:var(--ev-accent);border:2px solid var(--ev-bg)}.journey-item.target::before{background:var(--ev-bg);border:2px dashed var(--ev-muted)}.journey-item .value{font-size:37px;line-height:1.08;letter-spacing:-1px;font-weight:600;margin-bottom:5px}.journey-item.target .value{font-size:29px}.journey-item .label{font-size:14px;line-height:1.4}.notice{border:1px solid var(--ev-amber);border-radius:7px;padding:12px 14px;display:flex;align-items:start;gap:10px;font-size:13px;line-height:1.5;color:var(--ev-amber);background:color-mix(in srgb,var(--ev-amber) 4%,transparent);margin:14px 0}.notice ha-icon{--mdc-icon-size:19px;width:19px;height:19px;margin-top:1px}.notice strong{display:block;font-weight:650}.notice.error{color:var(--ev-error);border-color:var(--ev-error)}.facts{margin:20px 0 14px}.fact{display:flex;align-items:baseline;justify-content:space-between;gap:18px;font-size:14px;line-height:1.45;margin:10px 0}.fact dt{color:var(--ev-muted)}.fact dd{margin:0;font-weight:600;text-align:right}.activity{border-top:1px solid var(--ev-line);padding:16px 0 0;margin-top:15px}.activity strong{font-size:16px;display:flex;align-items:center;gap:9px}.activity ha-icon{--mdc-icon-size:19px;width:19px;height:19px}.activity.charging strong{color:var(--ev-green)}.activity .helper{margin-left:28px;margin-top:4px}.actions{display:flex;gap:12px;margin-top:19px}.actions button{flex:1}.outlook .actions{margin-top:12px}.outlook .actions button{padding:10px 12px}.outlook .actions button:not(.primary){font-weight:400}.status-reason{margin-top:12px;font-size:13px;line-height:1.5;color:var(--ev-muted)}.chart-card{padding:18px 20px 15px}.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--ev-muted);font-size:11px;margin:13px 0 12px}.legend span{display:flex;gap:6px;align-items:center}.legend i{width:16px;height:3px;display:inline-block;background:var(--ev-accent)}.legend .target-key{height:0;border-top:2px dashed var(--ev-muted);background:transparent}.legend .rate-key{height:10px;background:var(--ev-accent);opacity:.4}.legend .charging-key{height:10px;background:var(--ev-green)}.legend .cost-key{background:var(--ev-green)}.chart-label{font-size:12px;color:var(--ev-muted);margin:8px 0 2px}.chart canvas{display:block;width:100%;height:142px}.chart[data-kind=soc] canvas{height:174px}.chart[data-kind=rates] canvas{height:100px}.chart[data-kind=cost] canvas{height:120px}.chart .empty{min-height:130px}.chart-card>.notice{margin-bottom:0}.empty{padding:28px 12px;color:var(--ev-muted);font-size:14px;line-height:1.6;text-align:center}.windows{margin-top:20px}.windows h2{font-size:20px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:14px}th{text-align:left;color:var(--ev-muted);font-size:12px;font-weight:500}th,td{padding:12px 9px;border-bottom:1px solid var(--ev-line);white-space:nowrap}tbody tr:last-child td{border-bottom:0}details{margin-top:12px}summary{cursor:pointer;color:var(--ev-accent);font-size:13px;min-height:36px;padding:8px 0}.foot{font-size:11px;color:var(--ev-muted);display:flex;gap:20px;justify-content:space-between;flex-wrap:wrap;margin-top:16px}.schedule-grid{display:grid;grid-template-columns:minmax(0,1.94fr) minmax(290px,1fr);gap:16px;align-items:start}.form-card{padding:20px 22px}.form-card h2{font-size:25px}.mode-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:20px 0}.mode-option{display:flex;align-items:start;gap:12px;padding:16px;text-align:left;min-height:104px;font-weight:400}.mode-option ha-icon{--mdc-icon-size:28px;width:28px;height:28px;margin-top:4px}.mode-option b{display:block;font-size:15px;margin-bottom:7px;line-height:1.3}.mode-option .helper{font-size:13px}.mode-option[aria-pressed=true]{border-color:var(--ev-accent);background:color-mix(in srgb,var(--ev-accent) 7%,transparent)}.mode-option[aria-pressed=true] ha-icon{color:var(--ev-accent)}.field{display:grid;grid-template-columns:minmax(150px,.9fr) minmax(0,1.1fr);gap:22px;border-top:1px solid var(--ev-line);padding:17px 0;align-items:start}.field-label{font-size:17px;font-weight:650;margin:0 0 7px}.field .helper{margin-top:7px}.field label{display:block}.field-input{min-width:0}input[type=number],input[type=datetime-local]{border:1px solid var(--ev-line);border-radius:6px;background:var(--ev-input);color:var(--ev-text);padding:11px 12px;min-height:44px;font-size:15px;width:100%;min-width:0}input:disabled{opacity:.45}.with-unit{display:flex;align-items:center;gap:9px}.with-unit span{white-space:nowrap;color:var(--ev-muted);font-size:13px}.target-number{max-width:145px}.target-number input{font-size:22px;padding:8px 12px}input[type=range]{width:100%;margin:18px 0 5px;accent-color:var(--ev-accent);min-height:24px}.range-labels{display:flex;justify-content:space-between;font-size:11px;color:var(--ev-muted)}.toggle{display:flex;align-items:center;gap:10px;min-height:30px;font-size:14px;font-weight:400!important;margin-bottom:10px}.toggle input{appearance:none;flex-shrink:0;width:40px;height:23px;border-radius:20px;background:var(--ev-line);border:1px solid var(--ev-muted);position:relative;margin:0;cursor:pointer}.toggle input::after{content:'';width:17px;height:17px;position:absolute;left:2px;top:2px;border-radius:50%;background:var(--ev-muted)}.toggle input:checked{background:var(--ev-accent);border-color:var(--ev-accent)}.toggle input:checked::after{left:19px;background:var(--ev-button-text)}.speed{font-size:16px;font-weight:600;padding-top:2px}.form-actions{border-top:1px solid var(--ev-line);padding-top:20px;display:flex;gap:14px}.form-actions .primary{min-width:245px}.form-footer{min-height:22px;margin-top:10px}.message{font-size:13px;line-height:1.5;color:var(--ev-green)}.message.error{color:var(--ev-error)}.saved-plan h2{font-size:25px}.saved-plan .journey{margin-top:24px;margin-bottom:24px}.saved-plan .journey-item .value{font-size:30px}.saved-plan .journey-item.date .value{font-size:20px;letter-spacing:0}.saved-plan .journey-item::before{border-color:var(--ev-surface)}.saved-plan .journey-item.target::before{background:var(--ev-surface);border-color:var(--ev-muted)}.controller-tools{border-top:1px solid var(--ev-line);margin-top:18px;padding-top:14px}.controller-row{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:14px}.controller-row button{font-size:12px;padding:5px 10px;min-height:34px}.boost{width:100%;margin-top:14px}.saved-plan .helper.boost-note{margin-top:8px}.saved-plan .helper{font-size:14px;line-height:1.5}.saved-plan .journey{margin-top:30px;margin-bottom:30px}.saved-plan .journey-item{padding-bottom:32px}.saved-plan .journey-item:last-child{padding-bottom:0}.saved-plan .journey-item .value{font-size:32px}.saved-plan .journey-item.date .value{font-size:20px}.saved-plan .facts{margin:24px 0}.saved-plan .notice{padding:14px 16px;font-size:14px}.saved-plan .activity{padding-top:20px;margin-top:22px}.saved-plan .controller-tools{margin-top:20px;padding-top:20px}.saved-plan .boost{margin-top:22px}.resume{width:100%;margin-top:10px}.unavailable{max-width:650px;margin:45px auto;padding:30px}.unavailable h2{font-size:24px}.unavailable button{margin-top:20px}.full-notice{margin-top:0}button,select{touch-action:manipulation}
:host([narrow]) .menu{display:block}
@media(max-width:1150px){.overview-grid{grid-template-columns:minmax(270px,.9fr) minmax(0,1.5fr);gap:14px}.schedule-grid{grid-template-columns:minmax(0,1.7fr) minmax(270px,1fr)}.mode-options{gap:8px}.mode-option{padding:12px;display:block;min-height:128px}.mode-option ha-icon{margin:0 0 8px}.field{grid-template-columns:1fr 1.15fr;gap:14px}.form-actions .primary{min-width:0;flex:1}.fact{gap:12px}.outlook{padding-left:4px;padding-right:4px}}
@media(max-width:900px){.overview-grid,.schedule-grid{grid-template-columns:1fr}.outlook{padding:0}.outlook .journey{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-left:0;margin:22px 0}.outlook .journey-item{padding:0 18px 0 0}.outlook .journey-item::before{display:none}.outlook .journey-item .value{font-size:32px}.outlook .journey-item.target .value{font-size:26px}.outlook .facts{display:grid;grid-template-columns:1fr 1fr;gap:0 24px}.outlook .fact{display:block}.outlook .fact dd{text-align:left;margin-top:4px}.outlook .actions{max-width:600px}.mode-option{display:flex;min-height:100px}.saved-plan .journey{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;border:0;padding:0}.saved-plan .journey-item{padding:0}.saved-plan .journey-item::before{display:none}}
@media(max-width:600px){.menu{display:block}.shell-header{padding:14px 14px 0;gap:14px}.heading h1{font-size:22px}.clock{display:none}main{padding:16px 12px 22px}.tabs{gap:9px;padding-bottom:12px}.tabs button{min-height:42px}.surface{padding:17px 15px}.outlook .journey{gap:9px}.outlook .journey-item{padding-right:0}.outlook .journey-item .value{font-size:31px}.outlook .journey-item .label{font-size:12px}.outlook .journey-item .helper{font-size:11px}.outlook .journey-item.target .value{font-size:26px}.outlook .facts{gap:0 16px}.fact{font-size:13px}.actions{gap:8px}.actions button{font-size:12px;padding:9px}.legend{gap:10px;font-size:10px;margin-bottom:12px}.chart-card{padding:17px 12px}.chart canvas{height:130px}.chart[data-kind=soc] canvas{height:154px}h2{font-size:21px}.mode-options{grid-template-columns:1fr;margin:20px 0}.mode-option{min-height:75px;padding:12px 14px;gap:14px;align-items:center}.mode-option b{margin:0 0 3px}.mode-option ha-icon{margin:0}.field{grid-template-columns:1fr;gap:12px;padding:19px 0}.field-label{font-size:16px}.field .helper{font-size:12px}.form-card h2,.saved-plan h2{font-size:23px}.form-actions{gap:10px}.form-actions button{font-size:13px;padding:10px 12px}.saved-plan .journey{grid-template-columns:1fr;border-left:2px solid var(--ev-line);padding-left:19px}.saved-plan .journey-item{padding:0 0 18px 15px}.saved-plan .journey-item::before{display:block}.vehicle-select select{max-width:200px}input[type=datetime-local]{font-size:14px;padding:11px 8px}.windows th,.windows td{padding:11px 7px}.foot{font-size:10px}.notice{font-size:12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
`;

class EVChargePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this._page = 'overview';
    this._groups = [];
    this._registry = null;
    this._epoch = 0;
    this._dirty = false;
    this._busy = false;
    this._message = '';
    this._error = false;
    this._drafts = new Map();
    this.shadowRoot.addEventListener('click', event => this._click(event));
    this.shadowRoot.addEventListener('input', event => this._input(event));
    this.shadowRoot.addEventListener('change', event => this._change(event));
    this.shadowRoot.addEventListener('keydown', event => {
      if (event.target.getAttribute('role') !== 'tab' || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      this._page = event.key === 'Home' ? 'overview' : event.key === 'End' ? 'schedule' : this._page === 'overview' ? 'schedule' : 'overview';
      this._render();
      this.shadowRoot.querySelector(`.tabs [data-page=${this._page}]`)?.focus();
    });
  }

  connectedCallback() {
    this._connected = true;
    this._registry = null;
    this._registryError = '';
    this._refs = null;
    this._resize = new ResizeObserver(() => this._queueCharts());
    this._resize.observe(this);
    this._connect();
    this._render();
  }

  disconnectedCallback() {
    this._connected = false;
    this._epoch++;
    this._loading = false;
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._subscribedConnection = null;
    this._subscriptionTask = null;
    clearTimeout(this._registryTimer);
    this._registryTimer = null;
    this._registryRefreshPending = false;
    this._resize?.disconnect();
    cancelAnimationFrame(this._frame);
  }

  set hass(value) {
    const oldConnection = this._hass?.connection;
    this._hass = value;
    this.setAttribute('theme', value?.themes?.darkMode === false ? 'light' : 'dark');
    if (oldConnection && oldConnection !== value?.connection) {
      this._epoch++;
      this._unsubscribe?.();
      this._unsubscribe = null;
      this._subscribedConnection = null;
      this._subscriptionTask = null;
      clearTimeout(this._registryTimer);
      this._registryTimer = null;
      this._registryRefreshPending = false;
      this._registry = null;
      this._registryError = '';
      this._loading = false;
    }
    this._connect();
    this._refresh();
  }

  get hass() { return this._hass; }
  set narrow(value) { this.toggleAttribute('narrow',!!value); }

  async _connect() {
    if (!this._connected || !this._hass?.callWS || this._loading) return;
    const connection = this._hass?.connection;
    const epoch = this._epoch;
    if (connection?.subscribeMessage && this._subscribedConnection !== connection) {
      this._subscribedConnection = connection;
      // Subscribe before the first snapshot so a registry change during the
      // request queues a fresh snapshot instead of disappearing in a race.
      this._subscriptionTask = Promise.resolve().then(() => connection.subscribeMessage(
        () => this._scheduleRegistry(), {type:'subscribe_events',event_type:'entity_registry_updated'},
      )).then(unsubscribe => {
        if (!this._connected || epoch !== this._epoch) unsubscribe();
        else this._unsubscribe = unsubscribe;
      }).catch(() => {
        // Ordinary state updates and manual discovery still work if this
        // event subscription is unavailable. Retry on the next connection.
      });
    }
    await this._subscriptionTask;
    if (this._connected && epoch === this._epoch && this._registry === null && !this._registryError) await this._loadRegistry();
  }

  _scheduleRegistry() {
    if (!this._connected) return;
    this._registryRefreshPending = true;
    if (this._loading || this._registryTimer) return;
    this._registryTimer = setTimeout(() => {
      this._registryTimer = null;
      this._loadRegistry();
    },200);
  }

  async _loadRegistry() {
    if (!this._connected) return;
    if (this._loading) { this._registryRefreshPending = true; return; }
    clearTimeout(this._registryTimer);
    this._registryTimer = null;
    this._registryRefreshPending = false;
    this._loading = true;
    const epoch = this._epoch;
    try {
      const registry = await this._hass.callWS({type:'config/entity_registry/list'});
      if (!this._connected || epoch !== this._epoch) return;
      if (!Array.isArray(registry)) throw new Error('The entity registry response was invalid.');
      this._registry = registry;
      const grouped = new Map();
      for (const item of registry) {
        if (item.platform !== DOMAIN || !item.config_entry_id || item.disabled_by) continue;
        const key = KEYS.find(key => item.unique_id === `${item.config_entry_id}_${key}`);
        if (!key) continue;
        if (!grouped.has(item.config_entry_id)) grouped.set(item.config_entry_id, {id:item.config_entry_id, entities:{}});
        grouped.get(item.config_entry_id).entities[key] = item.entity_id;
      }
      this._groups = [...grouped.values()].filter(group => group.entities.status);
      this._registryError = '';
      if (!this._groups.some(group => group.id === this._selected)) this._select(this._groups[0]?.id);
      this._refs = null;
    } catch (error) {
      if (epoch === this._epoch) this._registryError = error.message || String(error);
    } finally {
      if (epoch === this._epoch) {
        this._loading = false;
        this._refresh(true);
        if (this._registryRefreshPending) this._scheduleRegistry();
      }
    }
  }

  _select(id) {
    if (this._selected) this._drafts.set(this._selected, {draft:this._draft,dirty:this._dirty});
    this._selected = id;
    const saved = this._drafts.get(id);
    this._draft = saved?.draft || this._current();
    this._dirty = saved?.dirty || false;
    this._pending = null;
    this._message = '';
    this._error = false;
    this._refs = null;
    this._render();
  }

  _group() { return this._groups.find(group => group.id === this._selected); }
  _state(key) { return this._hass?.states?.[this._group()?.entities[key]]; }
  _available(key) {
    const state = this._state(key);
    // HA buttons have the state "unknown" until first pressed.
    return !!state && state.state !== 'unavailable' && (key === 'resume' || state.state !== 'unknown');
  }
  _zone() { return this._hass?.config?.time_zone || 'UTC'; }
  _date(value, full = false) {
    if (!Number.isFinite(instant(value))) return '—';
    return new Intl.DateTimeFormat(this._hass?.locale?.language || 'en-GB', {
      timeZone:this._zone(), ...(full ? {weekday:'short',day:'numeric',month:'short',timeZoneName:'short'} : {}),
      hour:'2-digit',minute:'2-digit',hourCycle:'h23',
    }).format(instant(value));
  }
  _local(value) {
    if (!Number.isFinite(instant(value))) return '';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
      timeZone:this._zone(),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',
    }).formatToParts(instant(value)).map(part => [part.type,part.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }
  _number(value, suffix = '', places = 0) { const n = numeric(value); return n === null ? '—' : `${n.toFixed(places)}${suffix}`; }
  _money(value) { const n = numeric(value); return n === null ? '—' : new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(n); }
  _title(group = this._group()) {
    const state = this._hass?.states?.[group?.entities.status];
    return (state?.attributes?.friendly_name || 'EV Charge Controller').replace(/\s+Status$/i,'');
  }
  _current() {
    return {mode:this._state('mode')?.state || 'cheap_top_up',target_percent:this._state('target_percent')?.state ?? '',
      max_cheap_rate:this._state('max_cheap_rate')?.state ?? '',deadline:this._local(this._state('deadline')?.state),
      hard_price_ceiling:this._state('hard_price_ceiling')?.state === 'on'};
  }
  _matches(data) {
    const current = this._current();
    return Object.entries(data).every(([key,value]) => key === 'config_entry_id' ||
      (['mode','deadline','hard_price_ceiling'].includes(key) ? current[key] === value : numeric(current[key]) === value));
  }

  _refresh(force = false) {
    if (!this._hass) return;
    const refs = KEYS.map(key => this._state(key)).concat([this._zone(),this._hass.locale?.language,this._hass.themes?.darkMode]);
    if (!force && this._refs && refs.every((value,i) => value === this._refs[i])) return;
    this._refs = refs;
    if (this._pending && this._matches(this._pending)) {
      this._pending = null;
      this._dirty = false;
      this._message = 'Charging request saved.';
    }
    const current = this._current();
    const settings = JSON.stringify(current);
    if (!this._dirty) this._draft = current;
    const theme = this.getAttribute('theme');
    // Telemetry must not recreate focused form inputs or discard a draft.
    if (!force && this._page === 'schedule' && this.shadowRoot.querySelector('.form-card') &&
        this._available('status') && this._renderTheme === theme && (this._dirty || settings === this._settings)) {
      this.shadowRoot.querySelector('.saved-plan').innerHTML = this._summary(true);
      const a = this._state('status').attributes || {};
      this.shadowRoot.querySelector('[data-live=speed]').textContent = `${this._number(a.current_amps,' A')} · ${this._number(a.power_kw,' kW',2)}`;
      const cap = this.shadowRoot.querySelector('[data-live=cap]');
      if (cap) cap.textContent = `Current battery ${this._number(a.soc,'%')} · Car limit ${this._number(a.car_limit,'%')}`;
      this._feedback();
      return;
    }
    this._settings = settings;
    this._render();
  }

  _notice(text, title = '', error = false) {
    return text ? `<div class="notice ${error?'error':''}" role="status"><ha-icon icon="mdi:information"></ha-icon><div>${title?`<strong>${escapeHTML(title)}</strong>`:''}${escapeHTML(text)}</div></div>` : '';
  }
  _activity(a) {
    const charging = a.observed_charging === true;
    const title = charging ? 'Charging now' : a.observed_charging === false ? 'Not charging' : 'Charging feedback unavailable';
    return `<div class="activity ${charging?'charging':''}"><strong><ha-icon icon="${charging?'mdi:circle':'mdi:circle-outline'}"></ha-icon>${title}</strong><p class="helper">${a.home===true?'At home':a.home===false?'Away':'Location unknown'} · ${a.connected===true?'Plugged in':a.connected===false?'Unplugged':'Connection unknown'}</p></div>`;
  }
  _condition(a) {
    if (a.boost_until) return 'Boost is active. Forecasts show the saved price-based request; boost charging can differ.';
    if (a.manual_hold_until) return `Manual hold until ${this._date(a.manual_hold_until,true)}. Forecast assumes control resumes.`;
    if (this._state('monitoring_only')?.state === 'on') return 'Monitoring is on. The plan is shown, but charging won’t be switched on or off.';
    if (this._state('automatic_control')?.state === 'off') return 'Automatic control is paused. Forecast assumes it resumes.';
    if (a.managed_tariff === false) return 'Automatic charging is off for this tariff. Estimates show the saved request.';
    if (a.home === false) return 'Forecast assumes the car is at home and plugged in for the charging windows.';
    if (a.connected !== true) return 'Forecast applies if plugged in for the plan.';
    return '';
  }
  _coverage(data) {
    return data.rates_warning ? 'Some prices are unavailable. Charging uses the available prices and the plan updates when more arrive.' : '';
  }
  _summary(schedule = false) {
    const a = this._state('status')?.attributes || {};
    const data = this._state('plan')?.attributes || {};
    const mode = this._state('mode')?.state;
    const target = mode === 'cheap_top_up' ? a.car_limit : a.requested_target;
    const finish = data.forecast_completion;
    const capped = numeric(a.car_limit) !== null && numeric(target) > numeric(a.car_limit);
    const covered = numeric(data.forecast_soc) !== null && numeric(target) !== null && data.forecast_soc >= target;
    const forecastNote = data.forecast_horizon_end ? `By ${this._date(data.forecast_horizon_end,true)}` : 'Waiting for forecast inputs';
    const current = `<div class="journey-item"><div class="value">${this._number(a.soc,'%')}</div><div class="label">Current battery</div><div class="helper">${escapeHTML(MODES[mode]?.[0] || 'Saved request')}</div></div>`;
    const forecast = `<div class="journey-item"><div class="value">${this._number(data.forecast_soc,'%')}</div><div class="label">Forecast battery</div><div class="helper">${escapeHTML(forecastNote)}</div></div>`;
    const requested = `<div class="journey-item target"><div class="value">${this._number(target,'%')}</div><div class="label">${mode==='cheap_top_up'?'Car charge limit':'Requested target'}</div>${mode==='deadline'?`<div class="helper">Ready by ${escapeHTML(this._date(this._state('deadline')?.state,true))}</div>`:''}</div>`;
    const saveJourney = `<div class="journey-item"><div class="value">${this._number(target,'%')}</div><div class="label">${mode==='cheap_top_up'?'Car charge limit':'Target battery'}</div></div>${forecast}${mode==='deadline'?`<div class="journey-item target date"><div class="value">${escapeHTML(this._date(this._state('deadline')?.state,true))}</div><div class="label">Ready by</div></div>`:''}`;
    const targetWarning = mode !== 'cheap_top_up' && !capped && !covered && !finish && numeric(data.forecast_soc) !== null
      ? this._notice(mode === 'deadline' ? 'Allow more time or increase your price limit.' : 'Increase your price limit or lower the target.','The full charge is not yet planned.') : '';
    const capWarning = capped
      ? this._notice(`The car limit is ${a.car_limit}%. Change it in Tesla or Tessie to permit the requested target.`,'Car limit is below your target.') : '';
    const activity = this._activity(a);
    const facts = `<dl class="facts"><div class="fact"><dt>Estimated remaining cost</dt><dd>${this._money(data.forecast_cost)}</dd></div>${finish?`<div class="fact"><dt>${capped?'Estimated car limit reached':'Estimated target reached'}</dt><dd>${escapeHTML(this._date(finish,true))}</dd></div>`:''}${!schedule?`<div class="fact"><dt>Current charging setting</dt><dd>${this._number(a.current_amps,' A')} · ${this._number(a.power_kw,' kW',2)}</dd></div><div class="fact"><dt>Current electricity rate</dt><dd>${a.price_valid?this._number(a.price_pence,'p/kWh',2):'Unavailable'}</dd></div>`:''}</dl>`;
    const condition = this._condition(a);
    if (schedule) return `<h2>Current saved plan</h2><div class="journey forecast-summary">${saveJourney}</div>${facts}${this._coverage(data)?this._notice('Charging uses the available prices. The plan updates when more arrive.','Some prices are unavailable.'):''}${capWarning}${condition?this._notice(condition):''}${activity}${this._controllerTools(true)}`;
    return `<h2>Your charge outlook</h2><div class="journey forecast-summary">${current}${forecast}${requested}</div>${this._coverage(data)?this._notice('Charging uses the available prices. The plan updates when more arrive.','Some prices are unavailable.'):targetWarning}${capWarning}${facts}${condition?this._notice(condition):''}${activity}${this._state('status')?.state!=='Charging confirmed'?`<p class="status-reason">${escapeHTML(this._state('status')?.state)} · ${escapeHTML((a.reason||'').split(' Price coverage: ')[0])}</p>`:''}<div class="actions"><button class="primary" data-page="schedule">Adjust charging request</button><button data-action="automatic" ${!this._available('automatic_control')||this._busy?'disabled':''}>${this._state('automatic_control')?.state==='off'?'Resume automatic control':'Pause automatic control'}</button></div>${a.manual_hold_until?`<button class="resume" data-action="resume" ${!this._available('resume')||this._busy?'disabled':''}>Resume after manual change</button>`:''}`;
  }
  _controllerTools(includeBoost = false) {
    const automatic = this._state('automatic_control')?.state;
    const monitoring = this._state('monitoring_only')?.state;
    const boost = this._state('boost')?.state === 'on';
    const held = this._state('status')?.attributes?.manual_hold_until;
    return `<div class="controller-tools"><div class="controller-row"><span>Automatic control <b>${automatic==='on'?'On':automatic==='off'?'Paused':'Unavailable'}</b></span><button data-action="automatic" ${!this._available('automatic_control')||this._busy?'disabled':''}>${automatic==='off'?'Resume':'Pause'}</button></div>${held?`<button class="resume" data-action="resume" ${!this._available('resume')||this._busy?'disabled':''}>Resume after manual change</button>`:''}${includeBoost?`<button class="boost" data-action="boost" ${!this._available('boost')||this._busy?'disabled':''}>${boost?'Cancel boost':'Boost now'}</button><p class="helper boost-note">${monitoring==='on'?'Monitoring is on, so Boost won’t start charging.':'Boost temporarily charges outside your schedule and price limit.'}</p>`:''}<details><summary>Controller options</summary><div class="controller-row"><span>Monitoring only <b>${monitoring==='on'?'On':monitoring==='off'?'Off':'Unavailable'}</b></span><button data-action="monitoring" ${!this._available('monitoring_only')||this._busy?'disabled':''}>${monitoring==='on'?'Turn off':'Turn on'}</button></div><p class="helper">Monitoring shows the plan without switching charging on or off.</p></details></div>`;
  }

  _render() {
    if (!this._hass) return;
    const details = [...this.shadowRoot.querySelectorAll('details')].map(item => item.open);
    const selected = this._group();
    const header = `<header class="shell-header"><div class="heading"><button class="menu" data-action="menu" aria-label="Open Home Assistant sidebar"><ha-icon icon="mdi:menu"></ha-icon></button><div><h1>EV Charging</h1><div class="vehicle-select">${this._groups.length>1?`<label class="helper" for="controller">Controller</label><select id="controller" data-controller ${this._busy?'disabled':''}>${this._groups.map(group=>`<option value="${escapeHTML(group.id)}" ${group.id===this._selected?'selected':''}>${escapeHTML(this._title(group))}</option>`).join('')}</select>`:`<span class="vehicle">${escapeHTML(selected?this._title():'EV Charge Controller')}</span>`}</div></div></div><div class="clock">${this._state('status')?.last_updated?'Updated '+escapeHTML(this._date(this._state('status').last_updated,true)):''}</div><nav class="tabs" aria-label="EV Charging pages" role="tablist">${['overview','schedule'].map(page=>`<button role="tab" aria-selected="${page===this._page}" data-page="${page}">${page==='overview'?'Overview':'Schedule'}</button>`).join('')}</nav></header>`;
    let content;
    if (this._registryError) content = `<section class="surface unavailable"><h2>Could not load controllers</h2><p class="helper">${escapeHTML(this._registryError)}</p><button data-action="retry">Retry</button></section>`;
    else if (this._registry === null) content = '<section class="surface unavailable"><h2>Loading EV Charging</h2><p class="helper">Loading your charging controls…</p></section>';
    else if (!selected) content = '<section class="surface unavailable"><h2>No EV Charge Controller found</h2><p class="helper">Add or enable the integration under Settings → Devices & services. </p><button data-action="retry">Refresh controllers</button></section>';
    else if (!this._available('status')) content = '<section class="surface unavailable"><h2>Charging data unavailable</h2><p class="helper">The controller is starting or unavailable. Check its integration under Settings → Devices & services.</p><button data-action="retry">Refresh controllers</button></section>';
    else content = this._page === 'schedule' ? this._schedule() : this._overview();
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${header}<main>${content}</main>`;
    this._renderTheme = this.getAttribute('theme');
    this.shadowRoot.querySelectorAll('details').forEach((item,i) => { item.open = details[i] || false; });
    this._feedback();
    this._queueCharts();
  }

  _overview() {
    const data = this._state('plan')?.attributes || {};
    return `<div class="overview-grid"><section class="outlook">${this._summary()}</section><section class="surface chart-card"><h2>Battery and charging plan</h2><p class="helper">Times in ${escapeHTML(this._zone())}</p><div class="legend"><span><i class="target-key"></i>Target battery</span><span><i class="charging-key"></i>Planned charging</span></div>${[['soc','Battery level (%)'],['rates','Electricity price (p/kWh)'],['cost','Estimated remaining cost (£)']].map(([key,label])=>`<div class="chart" data-kind="${key}"><div class="chart-label">${label}</div><canvas data-chart="${key}" role="img" aria-label="${label}. Exact forecast values and prices are in the tables below."></canvas></div>`).join('')}<div class="message" role="status" data-feedback></div></section></div>${this._windows(data)}<footer class="foot"><span>Estimates assume the car stays plugged in at home.</span></footer>`;
  }

  _intervals(data,key) {
    return (Array.isArray(data[key])?data[key]:[]).slice(0,400).filter(item=>item&&typeof item==='object').map(item=>({...item,startMs:instant(item.start),endMs:instant(item.end),price:numeric(item.price_pence)})).filter(item=>Number.isFinite(item.startMs)&&item.endMs>item.startMs&&item.price!==null).sort((a,b)=>a.startMs-b.startMs);
  }
  _series(data) {
    return (Array.isArray(data.forecast_series)?data.forecast_series:[]).slice(0,400).filter(item=>item&&typeof item==='object').map(item=>({time:instant(item.time),soc:numeric(item.soc),cost:numeric(item.cost)})).filter(item=>Number.isFinite(item.time)&&item.soc!==null&&item.cost!==null).sort((a,b)=>a.time-b.time);
  }
  _windows(data) {
    const periods = this._intervals(data,'forecast_schedule');
    const slots = this._chargingWindows(periods);
    const rates = this._intervals(data,'rates');
    const series = this._series(data);
    return `<section class="surface windows"><h2>Upcoming charging windows</h2>${slots.length?`<div class="table-wrap"><table><thead><tr><th>Start time</th><th>End time</th><th>Duration</th><th>Average rate</th><th>Energy</th><th>Estimated cost</th></tr></thead><tbody>${slots.slice(0,5).map(slot=>this._slotRow(slot)).join('')}</tbody></table></div>${periods.length>slots.length||slots.length>5?`<details><summary>View all ${periods.length} charging periods</summary><div class="table-wrap"><table><thead><tr><th>Start</th><th>End</th><th>Duration</th><th>Rate</th><th>Energy</th><th>Estimated cost</th></tr></thead><tbody>${periods.map(slot=>this._slotRow(slot)).join('')}</tbody></table></div></details>`:''}`:'<p class="empty">No eligible published charging windows are currently forecast.</p>'}<details><summary>Prices and charge details</summary><p class="helper">${escapeHTML(this._state('status')?.attributes?.reason || '')}</p><dl class="facts"><div class="fact"><dt>Energy to add</dt><dd>${this._number(data.forecast_grid_energy_kwh,' kWh',1)}</dd></div><div class="fact"><dt>Energy not yet planned</dt><dd>${this._number(data.forecast_shortfall_kwh,' kWh',1)}</dd></div></dl>${rates.length?`<div class="table-wrap"><table><caption class="helper">Published electricity prices</caption><thead><tr><th>Start</th><th>End</th><th>Price</th></tr></thead><tbody>${rates.map(slot=>`<tr><td>${escapeHTML(this._date(slot.start,true))}</td><td>${escapeHTML(this._date(slot.end,true))}</td><td>${this._number(slot.price,'p/kWh',2)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="helper">No published prices available.</p>'}${series.length?`<div class="table-wrap"><table><caption class="helper">Battery and cost forecast values</caption><thead><tr><th>Time</th><th>Battery</th><th>Cost</th></tr></thead><tbody>${series.map(point=>`<tr><td>${escapeHTML(this._date(new Date(point.time).toISOString(),true))}</td><td>${this._number(point.soc,'%',1)}</td><td>${this._money(point.cost)}</td></tr>`).join('')}</tbody></table></div>`:''}</details></section>`;
  }
  _chargingWindows(periods) {
    const windows = [];
    for (const period of periods) {
      const energy = numeric(period.grid_energy_kwh);
      const cost = energy === null ? null : energy*period.price/100;
      let window = windows.at(-1);
      if (!window || window.endMs !== period.startMs) {
        window = {...period,grid_energy_kwh:energy,cost};
        windows.push(window);
      } else {
        window.end = period.end;
        window.endMs = period.endMs;
        window.grid_energy_kwh = window.grid_energy_kwh === null || energy === null ? null : window.grid_energy_kwh+energy;
        window.cost = window.cost === null || cost === null ? null : window.cost+cost;
        window.price = window.grid_energy_kwh ? window.cost/window.grid_energy_kwh*100 : null;
      }
    }
    return windows;
  }
  _slotRow(slot) {
    const energy = numeric(slot.grid_energy_kwh);
    const minutes = Math.round((slot.endMs-slot.startMs)/60000);
    const duration = minutes >= 60 ? `${Math.floor(minutes/60)} h${minutes%60?` ${minutes%60} min`:''}` : `${minutes} min`;
    return `<tr><td>${escapeHTML(this._date(slot.start,true))}</td><td>${escapeHTML(this._date(slot.end,true))}</td><td>${duration}</td><td>${this._number(slot.price,'p/kWh',2)}</td><td>${this._number(energy,' kWh',1)}</td><td>${this._money(energy===null?null:energy*slot.price/100)}</td></tr>`;
  }

  _schedule() {
    const d = this._draft || this._current();
    this._draft = d;
    const a = this._state('status')?.attributes || {};
    const limited = d.mode !== 'deadline' || d.hard_price_ceiling;
    return `<div class="schedule-grid"><section class="surface form-card"><h2>Plan your charge</h2><p class="muted">Choose how and when ${escapeHTML(this._title())} charges.</p><div class="mode-options" role="group" aria-label="Charging mode">${Object.entries(MODES).map(([mode,[label,helper,icon]])=>`<button class="mode-option" data-mode="${mode}" data-field="mode" aria-pressed="${d.mode===mode}" ${this._busy?'disabled':''}><ha-icon icon="${icon}"></ha-icon><span><b>${label}</b><span class="helper">${helper}</span></span></button>`).join('')}</div>${d.mode!=='cheap_top_up'?`<div class="field"><div><label class="field-label" for="target">Target battery</label></div><div class="field-input"><div class="with-unit target-number"><input id="target" data-field="target_percent" type="number" min="0" max="100" step="1" value="${escapeHTML(d.target_percent)}" ${this._busy?'disabled':''} required><span>%</span></div><input type="range" min="0" max="100" step="1" value="${escapeHTML(d.target_percent)}" aria-label="Target battery slider" data-target-slider ${this._busy?'disabled':''}><div class="range-labels" aria-hidden="true"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><p class="helper" data-live="cap">Current battery ${this._number(a.soc,'%')} · Car limit ${this._number(a.car_limit,'%')}</p></div></div>`:`<div class="field"><div class="field-label">Battery limit</div><div><div class="speed">Car charge limit ${this._number(a.car_limit,'%')}</div><p class="helper">Cheap top-up charges below your price limit, up to the limit set in Tesla or Tessie.</p></div></div>`}${d.mode==='deadline'?`<div class="field"><div><label class="field-label" for="deadline">Ready by</label></div><div class="field-input"><input id="deadline" data-field="deadline" type="datetime-local" value="${escapeHTML(d.deadline)}" ${this._busy?'disabled':''} required><p class="helper">Time zone: ${escapeHTML(this._zone())}.</p></div></div>`:''}<div class="field"><div><label class="field-label" for="rate">${d.mode==='deadline'?'Price limit':'Maximum cheap rate'}</label><p class="helper">${d.mode==='deadline'?'Set a maximum price for this request (optional).':'Charge only when electricity is at or below this rate.'}</p></div><div class="field-input">${d.mode==='deadline'?`<label class="toggle"><input type="checkbox" data-field="hard_price_ceiling" ${d.hard_price_ceiling?'checked':''} ${this._busy?'disabled':''}>Limit price for this request</label>`:''}<div class="with-unit"><input id="rate" data-field="max_cheap_rate" type="number" min="-100" max="200" step="0.1" value="${escapeHTML(d.max_cheap_rate)}" ${!limited||this._busy?'disabled':''} required><span>p/kWh</span></div><p class="helper">${d.mode==='deadline'?'When off, higher prices can be used to meet your deadline. Turning this on may prevent reaching your target.':d.mode==='flexible'?'The planner selects published periods below this limit, without a deadline.':'Negative limits are supported for periods when you are paid to charge.'}</p></div></div><div class="field"><div><div class="field-label">Charging speed</div><p class="helper">Uses the current setting in Tesla or Tessie. Change amps there.</p></div><div class="speed" data-live="speed">${this._number(a.current_amps,' A')} · ${this._number(a.power_kw,' kW',2)}</div></div><div class="form-actions"><button class="primary" data-action="save" ${this._busy||this._pending?'disabled':''}>${this._busy?'Saving…':this._pending?'Waiting for settings…':'Save charging request'}</button><button data-action="reset" ${this._busy?'disabled':''}>Reset changes</button></div><div class="form-footer"><p class="helper" data-draft-note>${this._dirty?'Unsaved changes.':''}</p><div class="message" role="status" data-feedback></div></div></section><aside class="surface saved-plan">${this._summary(true)}</aside></div>`;
  }

  _feedback() {
    for (const element of this.shadowRoot.querySelectorAll('[data-feedback]')) {
      element.textContent = this._message;
      element.classList.toggle('error',this._error);
    }
    const note = this.shadowRoot.querySelector('[data-draft-note]');
    if (note) note.textContent = this._dirty ? 'Unsaved changes.' : '';
  }
  _input(event) {
    const input = event.target;
    if (this._busy) return;
    if (input.hasAttribute('data-target-slider')) {
      this._draft.target_percent = input.value;
      const number = this.shadowRoot.querySelector('[data-field=target_percent]');
      if (number) number.value = input.value;
    } else if (input.dataset.field && input.tagName === 'INPUT') {
      this._draft[input.dataset.field] = input.type === 'checkbox' ? input.checked : input.value;
      if (input.dataset.field === 'target_percent') {
        const slider = this.shadowRoot.querySelector('[data-target-slider]');
        if (slider) slider.value = input.value;
      }
    } else return;
    this._dirty = true;
    this._pending = null;
    this._message = '';
    this._error = false;
    const save = this.shadowRoot.querySelector('[data-action=save]');
    if (save) { save.disabled = false; save.textContent = 'Save charging request'; }
    this._feedback();
  }
  _change(event) {
    if (event.target.hasAttribute('data-controller') && !this._busy) this._select(event.target.value);
    if (event.target.dataset.field === 'hard_price_ceiling') {
      this._input(event);
      const rate = this.shadowRoot.querySelector('[data-field=max_cheap_rate]');
      if (rate) rate.disabled = !event.target.checked || this._busy;
    }
  }
  _click(event) {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.dataset.page) {
      this._page = button.dataset.page;
      this._render();
      return;
    }
    if (button.dataset.mode && !this._busy) {
      this._draft.mode = button.dataset.mode;
      this._dirty = true;
      this._pending = null;
      this._message = '';
      this._render();
      return;
    }
    switch (button.dataset.action) {
      case 'menu': this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true})); break;
      case 'retry': this._registryError = ''; this._loadRegistry(); break;
      case 'save': this._save(); break;
      case 'reset': this._dirty=false; this._pending=null; this._draft=this._current(); this._message=''; this._render(); break;
      case 'boost': this._switch('boost'); break;
      case 'automatic': this._switch('automatic_control'); break;
      case 'monitoring': this._switch('monitoring_only'); break;
      case 'resume': this._action('button','press','resume','Resume requested.'); break;
    }
  }

  async _save() {
    if (this._busy || !this._available('status') || !this._group() || this._registryError) return;
    const entry = this._selected;
    const d = this._draft;
    try {
      if (!this._available('mode') || !(d.mode in MODES)) throw new Error('Charging mode is unavailable.');
      const data = {config_entry_id:this._selected,mode:d.mode};
      const max = numeric(d.max_cheap_rate);
      if (max === null || max < -100 || max > 200) throw new Error('Cheap rate must be between −100 and 200p/kWh.');
      if (!this._available('max_cheap_rate')) throw new Error('The cheap rate setting is unavailable.');
      data.max_cheap_rate = max;
      if (d.mode !== 'cheap_top_up') {
        const target = numeric(d.target_percent);
        if (!this._available('target_percent') || target === null || target < 0 || target > 100) throw new Error('Target battery must be between 0 and 100%.');
        data.target_percent = target;
      }
      if (d.mode === 'deadline') {
        if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(d.deadline) || !this._state('deadline') || !this._available('hard_price_ceiling')) throw new Error('Choose a ready-by date and time, and check that the price limit control is available.');
        data.deadline = d.deadline;
        data.hard_price_ceiling = !!d.hard_price_ceiling;
      }
      this._busy = true;
      this._pending = data;
      this._message = '';
      this._error = false;
      this._render();
      await this._hass.callService(DOMAIN,'set_request',data);
      if (this._selected !== entry) return;
      if (this._matches(data)) {
        this._pending = null;
        this._dirty = false;
        this._draft = this._current();
        this._message = 'Charging request saved.';
      } else this._message = 'Request accepted; waiting for updated controller settings.';
    } catch (error) {
      if (this._selected !== entry) return;
      this._pending = null;
      this._error = true;
      this._message = error.message || String(error);
    } finally {
      this._busy = false;
      this._render();
    }
  }
  async _switch(key) {
    const on = this._state(key)?.state === 'on';
    const message = key === 'boost' ? (on?'Boost cancellation requested.':this._state('monitoring_only')?.state==='on'?'Boost requested. Monitoring is on, so charging won’t start.':'Boost requested.') : 'Change requested.';
    await this._action('switch',on?'turn_off':'turn_on',key,message);
  }
  async _action(domain, service, key, message) {
    if (this._busy || this._registryError || !this._available(key)) return;
    const id = this._group()?.entities[key];
    const entry = this._selected;
    if (!id) return;
    this._busy = true;
    this._message = '';
    this._error = false;
    this._render();
    try {
      await this._hass.callService(domain,service,{entity_id:id});
      if (this._selected === entry) this._message = message;
    } catch (error) {
      if (this._selected === entry) {
        this._error = true;
        this._message = error.message || String(error);
      }
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _queueCharts() {
    cancelAnimationFrame(this._frame);
    if (!this._connected || this._page !== 'overview') return;
    this._frame = requestAnimationFrame(() => this._drawCharts());
  }
  _drawCharts() {
    const data = this._state('plan')?.attributes || {};
    const series = this._series(data), rates = this._intervals(data,'rates'), slots = this._intervals(data,'forecast_schedule');
    const starts = [...series.map(point=>point.time),...rates.map(slot=>slot.startMs)];
    const ends = [...series.map(point=>point.time),...rates.map(slot=>slot.endMs)];
    if (!starts.length) {
      for (const canvas of this.shadowRoot.querySelectorAll('canvas')) this._drawEmpty(canvas,'No electricity prices available');
      return;
    }
    const start = Math.min(...starts), horizon = Math.max(...ends), span = Math.max(1800000,horizon-start);
    const deadline = instant(this._state('deadline')?.state);
    // A bounded empty region makes incomplete price coverage visible, without
    // extending a battery/cost line past the actual forecast horizon.
    const unknown = data.rates_complete === false;
    const end = unknown ? horizon + Math.min(span*.2,Number.isFinite(deadline)&&deadline>horizon?deadline-horizon:span*.2) : horizon;
    for (const canvas of this.shadowRoot.querySelectorAll('canvas')) {
      const key = canvas.dataset.chart;
      if ((key === 'rates' && !rates.length) || (key !== 'rates' && series.length < 2)) {
        this._drawEmpty(canvas,key==='rates'?'No published prices available':'Waiting for battery and charging speed');
        continue;
      }
      this._drawChart(canvas,key,{series,rates,slots,start,end,horizon,unknown});
    }
  }
  _context(canvas) {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return null;
    const ratio = Math.min(window.devicePixelRatio || 1,2);
    canvas.width = Math.round(width*ratio);
    canvas.height = Math.round(height*ratio);
    const ctx = canvas.getContext('2d');
    ctx.scale(ratio,ratio);
    const style = getComputedStyle(this);
    const colour = name => style.getPropertyValue(`--ev-${name}`).trim();
    ctx.font = `11px ${style.fontFamily}`;
    ctx.lineWidth = 1;
    return {ctx,width,height,colour};
  }
  _drawEmpty(canvas,text) {
    const context = this._context(canvas);
    if (!context) return;
    const {ctx,width,height,colour} = context;
    ctx.fillStyle = colour('muted');
    ctx.textAlign = 'center';
    ctx.fillText(text,width/2,height/2,Math.max(30,width-20));
    canvas.setAttribute('aria-label',text);
  }
  _drawChart(canvas,key,{series,rates,slots,start,end,horizon,unknown}) {
    const context = this._context(canvas);
    if (!context) return;
    const {ctx,width,height,colour} = context;
    const left = 38, right = 10, top = 10, bottom = 26;
    const w = width-left-right, h = height-top-bottom;
    const x = time => left + (time-start)/(end-start)*w;
    const values = key==='rates'?rates.map(slot=>slot.price):series.map(point=>point[key]);
    const min = key==='soc'?0:Math.min(0,...values), max = key==='soc'?100:Math.max(key==='cost'?.1:1,...values);
    const y = value => top+(max-value)/(max-min)*h;
    ctx.strokeStyle = colour('line');
    ctx.fillStyle = colour('muted');
    ctx.textAlign = 'right';
    for (const value of [max,(max+min)/2,min]) {
      const py = y(value);
      ctx.beginPath(); ctx.moveTo(left,py); ctx.lineTo(width-right,py); ctx.stroke();
      ctx.fillText(key==='cost'?value.toFixed(2):key==='soc'?`${Math.round(value)}%`:value.toFixed(1),left-7,py+4);
    }
    if (unknown && end > horizon) {
      const hx = x(horizon);
      ctx.save();
      ctx.beginPath(); ctx.rect(hx,top,width-right-hx,h); ctx.clip();
      ctx.strokeStyle = colour('line');
      for (let px=hx-h;px<width+h;px+=9) { ctx.beginPath();ctx.moveTo(px,top+h);ctx.lineTo(px+h,top);ctx.stroke(); }
      ctx.restore();
      ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(hx,top);ctx.lineTo(hx,top+h);ctx.stroke();ctx.setLineDash([]);
      if (key==='soc' && width>400) {
        ctx.textAlign='center';ctx.fillStyle=colour('muted');
        ctx.fillText('Prices not',hx+(width-right-hx)/2,top+h*.43);
        ctx.fillText('published',hx+(width-right-hx)/2,top+h*.43+15);
      }
    }
    if (key==='rates') {
      ctx.fillStyle=colour('accent');ctx.globalAlpha=.4;
      for (const slot of rates) ctx.fillRect(x(slot.startMs),Math.min(y(0),y(slot.price)),Math.max(1,x(slot.endMs)-x(slot.startMs)-1),Math.max(1,Math.abs(y(slot.price)-y(0))));
      ctx.globalAlpha=1;ctx.fillStyle=colour('green');
      for (const slot of slots) ctx.fillRect(x(Math.max(start,slot.startMs)),top+h-6,Math.max(1,x(Math.min(end,slot.endMs))-x(Math.max(start,slot.startMs))),6);
    } else {
      if (key==='soc') {
        const a = this._state('status')?.attributes || {};
        const target = numeric(this._state('mode')?.state==='cheap_top_up'?a.car_limit:a.requested_target);
        if (target !== null && target >= 0 && target <= 100) {
          ctx.strokeStyle=colour('muted');ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(left,y(target));ctx.lineTo(x(horizon),y(target));ctx.stroke();ctx.setLineDash([]);
        }
      }
      ctx.strokeStyle=colour(key==='cost'?'green':'accent');ctx.lineWidth=2.3;ctx.beginPath();
      series.forEach((point,i)=>{ if(i)ctx.lineTo(x(point.time),y(point[key]));else ctx.moveTo(x(point.time),y(point[key])); });
      ctx.stroke();ctx.lineWidth=1;
      const last = series.at(-1);
      ctx.fillStyle=colour(key==='cost'?'green':'accent');ctx.beginPath();ctx.arc(x(last.time),y(last[key]),3,0,Math.PI*2);ctx.fill();
    }
    ctx.fillStyle=colour('muted');
    const ticks = width<450?3:5;
    for (let i=0;i<ticks;i++) {
      const time = start + (horizon-start)*i/(ticks-1);
      ctx.textAlign=i===0?'left':i===ticks-1?'right':'center';
      ctx.fillText(this._date(new Date(time).toISOString()),x(time),height-6);
    }
    canvas.setAttribute('aria-label',`${key==='soc'?'Battery forecast':key==='cost'?'Remaining cost forecast':'Published electricity prices'} from ${this._date(new Date(start).toISOString(),true)} through ${this._date(new Date(horizon).toISOString(),true)}. ${unknown?'Hatched area has no published prices. ':''}Exact values are in the tables below.`);
  }
}

if (!customElements.get('ev-charge-panel')) customElements.define('ev-charge-panel',EVChargePanel);
