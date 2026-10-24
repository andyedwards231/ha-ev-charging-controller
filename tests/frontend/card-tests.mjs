import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// The card only needs these browser globals during module registration and
// construction. Tests replace rendering so all behavior stays DOM-free.
class HTMLElementStub {
  attachShadow() {
    return { activeElement: null, innerHTML: '', querySelector: () => null, querySelectorAll: () => [] };
  }
}
const definitions = new Map();
globalThis.HTMLElement = HTMLElementStub;
globalThis.customElements = {
  get: name => definitions.get(name),
  define: (name, value) => definitions.set(name, value),
};
globalThis.window = { customCards: [] };

const source = readFileSync(new URL('../../custom_components/ev_charge_controller/frontend/ev-charge-controller-card.js', import.meta.url));
await import(`data:text/javascript;base64,${source.toString('base64')}`);
const Card = definitions.get('ev-charge-controller-card');
Card.prototype._render = function () {};

const ids = {
  status_entity: 'sensor.ev_status',
  mode_entity: 'select.ev_mode',
  max_cheap_rate_entity: 'number.ev_max_rate',
  target_percent_entity: 'number.ev_target',
  ready_by_entity: 'datetime.ev_ready_by',
  boost_entity: 'switch.ev_boost',
  hard_price_ceiling_entity: 'switch.ev_hard_ceiling',
  monitoring_entity: 'switch.ev_monitoring',
  automatic_control_entity: 'switch.ev_automatic',
  plan_entity: 'sensor.ev_plan',
};

function states(overrides = {}) {
  return {
    [ids.status_entity]: { entity_id: ids.status_entity, state: 'ready', attributes: {} },
    [ids.mode_entity]: { entity_id: ids.mode_entity, state: 'cheap_top_up', attributes: {} },
    [ids.max_cheap_rate_entity]: { entity_id: ids.max_cheap_rate_entity, state: '15', attributes: {} },
    [ids.target_percent_entity]: { entity_id: ids.target_percent_entity, state: '80', attributes: {} },
    [ids.ready_by_entity]: { entity_id: ids.ready_by_entity, state: '2026-01-01T12:00:00Z', attributes: {} },
    [ids.boost_entity]: { entity_id: ids.boost_entity, state: 'off', attributes: {} },
    [ids.hard_price_ceiling_entity]: { entity_id: ids.hard_price_ceiling_entity, state: 'off', attributes: {} },
    [ids.monitoring_entity]: { entity_id: ids.monitoring_entity, state: 'off', attributes: {} },
    [ids.automatic_control_entity]: { entity_id: ids.automatic_control_entity, state: 'on', attributes: {} },
    [ids.plan_entity]: { entity_id: ids.plan_entity, state: 'ready', attributes: {} },
    ...overrides,
  };
}

function hass(entityStates = states(), extras = {}) {
  return {
    states: entityStates,
    config: { time_zone: 'Europe/London' },
    callService: async () => {},
    ...extras,
  };
}

function card(entityStates = states(), extraConfig = {}) {
  const instance = new Card();
  instance._config = { ...ids, config_entry_id: 'entry-one', ...extraConfig };
  instance._registryDone = true;
  instance._resolved = {};
  instance.hass = hass(entityStates);
  return instance;
}

test('submits all deadline controls together in one atomic request', async () => {
  const instance = card();
  instance._draft = {
    mode: 'deadline', max_cheap_rate: '18.5', target_percent: '90',
    deadline: '2026-10-12T07:30', hard_price_ceiling: true,
  };
  instance._dirty = true;
  let calls = [];
  instance._hass.callService = async (...args) => calls.push(args);

  await instance._apply();

  assert.deepEqual(calls, [['ev_charge_controller', 'set_request', {
    config_entry_id: 'entry-one', mode: 'deadline', max_cheap_rate: 18.5,
    target_percent: 90, deadline: '2026-10-12T07:30', hard_price_ceiling: true,
  }]]);
});

test('omits target and deadline fields for cheap top-up requests', async () => {
  const instance = card();
  instance._draft = {
    mode: 'cheap_top_up', max_cheap_rate: '12', target_percent: '77',
    deadline: '2026-10-12T07:30', hard_price_ceiling: true,
  };
  let call;
  instance._hass.callService = async (...args) => { call = args; };

  await instance._apply();

  assert.deepEqual(call, ['ev_charge_controller', 'set_request', {
    config_entry_id: 'entry-one', mode: 'cheap_top_up', max_cheap_rate: 12,
  }]);
});

test('omits deadline ceiling fields for flexible target requests', async () => {
  const instance = card();
  instance._draft = {
    mode: 'flexible', max_cheap_rate: '10', target_percent: '85',
    deadline: '', hard_price_ceiling: true,
  };
  let call;
  instance._hass.callService = async (...args) => { call = args; };

  await instance._apply();

  assert.deepEqual(call, ['ev_charge_controller', 'set_request', {
    config_entry_id: 'entry-one', mode: 'flexible', max_cheap_rate: 10, target_percent: 85,
  }]);
});

test('rejects invalid numbers and missing deadline without calling a service', async t => {
  for (const [name, draft] of [
    ['invalid maximum rate', { mode: 'cheap_top_up', max_cheap_rate: 'NaN' }],
    ['invalid flexible target', { mode: 'flexible', max_cheap_rate: '10', target_percent: '101' }],
    ['missing deadline', { mode: 'deadline', max_cheap_rate: '10', target_percent: '80', deadline: '', hard_price_ceiling: false }],
  ]) {
    await t.test(name, async () => {
      const instance = card();
      instance._draft = { target_percent: '80', deadline: '2026-10-12T07:30', ...draft };
      let calls = 0;
      instance._hass.callService = async () => { calls += 1; };

      await instance._apply();

      assert.equal(calls, 0);
      assert.equal(instance._error, true);
    });
  }
});

test('retains the draft and shows the service error when a request is rejected', async () => {
  const instance = card();
  const draft = { mode: 'flexible', max_cheap_rate: '12', target_percent: '88' };
  instance._draft = { ...draft };
  instance._dirty = true;
  instance._hass.callService = async () => { throw new Error('request rejected'); };

  await instance._apply();

  assert.deepEqual(instance._draft, draft);
  assert.equal(instance._dirty, true);
  assert.equal(instance._pendingRequest, null);
  assert.equal(instance._message, 'request rejected');
  assert.equal(instance._error, true);
});

test('clears a pending draft when Home Assistant reports matching values', async () => {
  const instance = card();
  instance._draft = {
    mode: 'flexible', max_cheap_rate: '20', target_percent: '92',
    deadline: '', hard_price_ceiling: false,
  };
  instance._dirty = true;
  let resolveService;
  instance._hass.callService = () => new Promise(resolve => { resolveService = resolve; });

  const applying = instance._apply();
  assert.equal(instance._pendingRequest.target_percent, 92);
  instance.hass = hass(states({
    [ids.mode_entity]: { entity_id: ids.mode_entity, state: 'flexible', attributes: {} },
    [ids.max_cheap_rate_entity]: { entity_id: ids.max_cheap_rate_entity, state: '20', attributes: {} },
    [ids.target_percent_entity]: { entity_id: ids.target_percent_entity, state: '92', attributes: {} },
  }));

  assert.equal(instance._pendingRequest, null);
  assert.equal(instance._dirty, false);
  assert.deepEqual(instance._draft, {
    mode: 'flexible', max_cheap_rate: '20', target_percent: '92',
    deadline: '2026-01-01T12:00', hard_price_ceiling: false,
  });
  assert.equal(instance._message, 'Charging request saved.');
  resolveService();
  await applying;
});

test('boost calls only the selected switch and uses monitoring state for its message', async () => {
  const instance = card(states({
    [ids.monitoring_entity]: { entity_id: ids.monitoring_entity, state: 'on', attributes: {} },
  }));
  const calls = [];
  instance._hass.callService = async (...args) => calls.push(args);

  await instance._boost();

  assert.deepEqual(calls, [['switch', 'turn_on', { entity_id: ids.boost_entity }]]);
  assert.equal(instance._message, 'Boost simulation requested; monitoring remains enabled.');
});

test('discovers renamed entities only from the selected controller entry', async () => {
  const suffixes = {
    mode_entity: 'mode', max_cheap_rate_entity: 'max_cheap_rate', target_percent_entity: 'target_percent',
    ready_by_entity: 'deadline', boost_entity: 'boost', hard_price_ceiling_entity: 'hard_price_ceiling',
    monitoring_entity: 'monitoring_only', automatic_control_entity: 'automatic_control', plan_entity: 'plan',
  };
  const entries = [
    { entity_id: 'sensor.ev_status', platform: 'ev_charge_controller', config_entry_id: 'entry-one', unique_id: 'status-one' },
    { entity_id: 'sensor.other_ev_status', platform: 'ev_charge_controller', config_entry_id: 'entry-two', unique_id: 'status-two' },
  ];
  for (const [key, suffix] of Object.entries(suffixes)) {
    entries.push({ entity_id: `renamed.${key}`, platform: 'ev_charge_controller', config_entry_id: 'entry-one', unique_id: `entry-one_${suffix}` });
    entries.push({ entity_id: `other_${key}`, platform: 'ev_charge_controller', config_entry_id: 'entry-two', unique_id: `entry-two_${suffix}` });
  }
  const instance = new Card();
  instance._config = { status_entity: 'sensor.ev_status' };
  instance._hass = hass(states(), { callWS: async () => entries });

  await instance._discover();

  assert.equal(instance._resolved.config_entry_id, 'entry-one');
  for (const key of Object.keys(suffixes)) assert.equal(instance._resolved[key], `renamed.${key}`);
});

test('blocks request and boost when the configured entry differs from the selected status sensor', async () => {
  const entries = [
    { entity_id: ids.status_entity, platform: 'ev_charge_controller', config_entry_id: 'entry-one', unique_id: 'status-one' },
  ];
  const instance = new Card();
  instance._config = { ...ids, status_entity: ids.status_entity, config_entry_id: 'entry-two' };
  instance._draft = { mode: 'cheap_top_up', max_cheap_rate: '15' };
  instance._dirty = true;
  instance._hass = hass(states(), { callWS: async () => entries });
  const calls = [];
  instance._hass.callService = async (...args) => calls.push(args);

  await instance._discover();
  await instance._apply();
  await instance._boost();

  assert.match(instance._scopeError, /does not match/);
  assert.equal(calls.length, 0);
  assert.equal(instance._error, true);
});

test('blocks request and boost when an entity override belongs to another controller', async () => {
  const entries = [
    { entity_id: ids.status_entity, platform: 'ev_charge_controller', config_entry_id: 'entry-one', unique_id: 'status-one' },
    { entity_id: 'switch.other_boost', platform: 'ev_charge_controller', config_entry_id: 'entry-two', unique_id: 'entry-two_boost' },
  ];
  const instance = new Card();
  instance._config = { ...ids, status_entity: ids.status_entity, boost_entity: 'switch.other_boost' };
  instance._draft = { mode: 'cheap_top_up', max_cheap_rate: '15' };
  instance._dirty = true;
  instance._hass = hass(states({
    'switch.other_boost': { entity_id: 'switch.other_boost', state: 'off', attributes: {} },
  }), { callWS: async () => entries });
  const calls = [];
  instance._hass.callService = async (...args) => calls.push(args);

  await instance._discover();
  await instance._apply();
  await instance._boost();

  assert.match(instance._scopeError, /override belongs to another controller/);
  assert.equal(calls.length, 0);
});

test('blocks requests and boost while controller registry discovery is pending', async () => {
  const instance = card();
  instance._registryDone = false;
  instance._registryLoading = false;
  let finishDiscovery;
  instance._hass.callWS = () => new Promise(resolve => { finishDiscovery = resolve; });
  const discovery = instance._discover();
  const calls = [];
  instance._hass.callService = async (...args) => calls.push(args);
  instance._draft = { mode: 'cheap_top_up', max_cheap_rate: '15' };

  await instance._apply();
  await instance._boost();

  assert.equal(instance._registryLoading, true);
  assert.equal(calls.length, 0);
  finishDiscovery([{ entity_id: ids.status_entity, platform: 'ev_charge_controller', config_entry_id: 'entry-one', unique_id: 'status-one' }]);
  await discovery;
});

test('filters invalid schedule ranges and sorts valid slots by start time', () => {
  const instance = card(states({
    [ids.plan_entity]: { entity_id: ids.plan_entity, state: 'ready', attributes: { schedule: [
      { start: '2026-01-01T03:00:00Z', end: '2026-01-01T04:00:00Z' },
      null,
      { start: 'bad', end: '2026-01-01T02:00:00Z' },
      { start: '2026-01-01T02:00:00Z', end: '2026-01-01T02:00:00Z' },
      { start: '2026-01-01T01:00:00Z', end: '2026-01-01T01:30:00Z' },
    ] } },
  }));

  assert.deepEqual(instance._slots().map(slot => slot.start), [
    '2026-01-01T01:00:00Z', '2026-01-01T03:00:00Z',
  ]);
});

test('formats local editor values in Home Assistant’s configured time zone', () => {
  const instance = card();

  assert.equal(instance._local('2026-01-15T12:00:00Z'), '2026-01-15T12:00');
  assert.equal(instance._local('2026-07-15T12:00:00Z'), '2026-07-15T13:00');
});


test('observed feedback alone determines charging label, including monitoring and problems', () => {
  const instance=card();
  for(const attributes of [
    {observed_charging:true},
    {observed_charging:true,problem:true},
    {observed_charging:true,desired_charging:false,monitoring_only:true},
  ])assert.equal(instance._chargingFeedback(attributes).label,'Charging now');
  assert.equal(instance._chargingFeedback({observed_charging:false,desired_charging:true,boost_until:'2026-10-13T20:00:00Z'}).label,'Not charging');
  for(const observed_charging of [undefined,null,'true',1]){
    assert.equal(instance._chargingFeedback({observed_charging}).key,'unknown');
  }
});
