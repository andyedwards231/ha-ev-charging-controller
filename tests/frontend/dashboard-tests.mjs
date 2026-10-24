import test from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {existsSync,readFileSync,mkdirSync} from 'node:fs';
import {createServer} from 'node:http';
mkdirSync(new URL('./artifacts/',import.meta.url),{recursive:true});
const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

async function withPage(run,viewport={width:1440,height:1100}) {
  const files={'/preview.html':'./preview.html',
    '/custom_components/ev_charge_controller/frontend/ev-charge-dashboard.js':'../../custom_components/ev_charge_controller/frontend/ev-charge-dashboard.js',
    '/custom_components/ev_charge_controller/frontend/ev-charge-controller-card.js':'../../custom_components/ev_charge_controller/frontend/ev-charge-controller-card.js',
    '/custom_components/ev_charge_controller/frontend/icon.png':'../../custom_components/ev_charge_controller/frontend/icon.png'};
  const server=createServer((request,response)=>{
    const path=files[new URL(request.url,'http://localhost').pathname];
    if(!path){response.writeHead(404).end();return;}
    response.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.png')?'image/png':'text/html');
    response.end(readFileSync(new URL(path,import.meta.url)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,...(existsSync(chrome)?{executablePath:chrome}:{})});
  try {
    const page=await browser.newPage({viewport});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/preview.html`);
    await page.locator('ev-charge-dashboard h1').waitFor();
    await run(page);
    assert.deepEqual(errors,[]);
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
}

test('overview renders forecasts, published prices and requested amps without service calls',()=>withPage(async page=>{
  const dashboard=page.locator('ev-charge-dashboard');
  assert.match(await dashboard.evaluate(el=>el.shadowRoot.textContent),/Demo EV charging/);
  assert.equal(await dashboard.locator('svg').count(),3);
  assert.match(await dashboard.evaluate(el=>el.shadowRoot.textContent),/24 A/);
  assert.match(await dashboard.evaluate(el=>el.shadowRoot.textContent),/5.52 kW/);
  assert.match(await dashboard.evaluate(el=>el.shadowRoot.textContent),/Using available prices/);
  assert.match(await dashboard.evaluate(el=>el.shadowRoot.textContent),/Energy still unplanned/);
  assert.deepEqual(await page.evaluate(()=>serviceCalls),[]);
  await page.screenshot({path:new URL('./artifacts/overview-desktop.png',import.meta.url).pathname,fullPage:true});
}));

test('unrelated Home Assistant changes preserve the overview DOM',()=>withPage(async page=>{
  assert.equal(await page.evaluate(()=>{
    const before=dashboard.shadowRoot.querySelector('svg');
    dashboard.hass={...hass,states:{...hass.states,'sensor.unrelated':{state:'1'}}};
    return before===dashboard.shadowRoot.querySelector('svg');
  }),true);
}));

test('completion is shown as a local time and the requested target remains independent of the car limit',()=>withPage(async page=>{
  await page.evaluate(()=>{
    const status='sensor.ev_charge_controller_status',plan='sensor.ev_charge_controller_charging_plan';
    hass.states[status]={...hass.states[status],attributes:{...hass.states[status].attributes,requested_target:90,car_limit:80}};
    hass.states[plan]={...hass.states[plan],attributes:{...hass.states[plan].attributes,forecast_target:80,forecast_completion:'2026-10-24T20:00:00Z'}};
    refresh();
  });
  const metrics=await page.locator('ev-charge-dashboard .metric .value').allTextContents();
  assert.equal(metrics[2],'21:00');
  assert.match(await page.locator('ev-charge-dashboard .hero').textContent(),/Car limit 80% · Requested target 90%/);
}));

test('unknown inputs do not display a zero-cost forecast',()=>withPage(async page=>{
  await page.locator('#scenario').selectOption('missing');
  const texts=await page.locator('ev-charge-dashboard .metric .value').allTextContents();
  assert.equal(texts[0],'—');
  assert.equal(texts[1],'—');
  assert.equal(await page.locator('ev-charge-dashboard svg').count(),1);
  await page.locator('#scenario').selectOption('no_rates');
  assert.match(await page.locator('ev-charge-dashboard').evaluate(el=>el.shadowRoot.textContent),/Unknown prices are never shown as free electricity/);
  assert.equal(await page.locator('ev-charge-dashboard svg').count(),0);
}));

test('unplugged forecasts are explicitly conditional, and charging follows feedback',()=>withPage(async page=>{
  await page.locator('#scenario').selectOption('unplugged');
  assert.match(await page.locator('ev-charge-dashboard').evaluate(el=>el.shadowRoot.textContent),/if plugged in for the plan/);
  await page.locator('#scenario').selectOption('charging');
  assert.match(await page.locator('ev-charge-dashboard .activity').textContent(),/Charging now/);
  assert.equal(await page.locator('ev-charge-dashboard .hero.charging').count(),1);
}));

test('schedule saves target and deadline atomically and preserves a draft during entity updates',()=>withPage(async page=>{
  await page.locator('#schedule').click();
  const card=page.locator('ev-charge-controller-controls');
  await card.locator('[data-field="target_percent"]').fill('85');
  await card.locator('[data-field="deadline"]').fill('2026-10-26T08:00');
  await page.evaluate(()=>{
    const id='sensor.ev_charge_controller_status';
    hass.states[id]={...hass.states[id],attributes:{...hass.states[id].attributes,soc:57}};
    refresh();
  });
  assert.equal(await card.locator('[data-field="target_percent"]').inputValue(),'85');
  assert.equal(await card.locator('[data-field="deadline"]').inputValue(),'2026-10-26T08:00');
  await card.locator('button.primary').click();
  const calls=await page.evaluate(()=>serviceCalls);
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0],['ev_charge_controller','set_request',{config_entry_id:'preview-controller',mode:'deadline',max_cheap_rate:2,target_percent:85,deadline:'2026-10-26T08:00',hard_price_ceiling:false}]);
  assert.match(await card.evaluate(el=>el.shadowRoot.textContent),/Charging request saved/);
  await page.screenshot({path:new URL('./artifacts/schedule-desktop.png',import.meta.url).pathname,fullPage:true});
}));

test('mobile layout fits and works in both themes with all modes',()=>withPage(async page=>{
  const dashboard=page.locator('ev-charge-dashboard');
  assert.equal(await dashboard.evaluate(el=>el.shadowRoot.querySelector('main').scrollWidth<=el.clientWidth),true);
  await page.locator('#theme').click();
  await page.screenshot({path:new URL('./artifacts/overview-mobile-light.png',import.meta.url).pathname,fullPage:true});
  await page.locator('#schedule').click();
  const card=page.locator('ev-charge-controller-controls');
  await card.locator('[data-field="mode"]').selectOption('cheap_top_up');
  assert.equal(await card.locator('[data-field="target_percent"]').count(),0);
  await card.locator('[data-field="mode"]').selectOption('flexible');
  assert.equal(await card.locator('[data-field="target_percent"]').count(),1);
  assert.equal(await card.locator('[data-field="deadline"]').count(),0);
  assert.equal(await card.evaluate(el=>el.shadowRoot.querySelector('ha-card').scrollWidth<=el.clientWidth),true);
  await page.screenshot({path:new URL('./artifacts/schedule-mobile-light.png',import.meta.url).pathname,fullPage:true});
},{width:390,height:844}));

test('renders data as text and gives a clear unavailable state',()=>withPage(async page=>{
  await page.evaluate(()=>{
    const id='sensor.ev_charge_controller_charging_plan';
    hass.states[id]={...hass.states[id],attributes:{...hass.states[id].attributes,rates_warning:'<img src=x onerror="window.injected=true">'}};
    refresh();
  });
  assert.equal(await page.locator('ev-charge-dashboard img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  await page.locator('#scenario').selectOption('unavailable');
  assert.match(await page.locator('ev-charge-dashboard').evaluate(el=>el.shadowRoot.textContent),/Charging data unavailable/);
}));

test('unknown charging feedback fits a 320px phone without horizontal overflow',()=>withPage(async page=>{
  await page.evaluate(()=>{
    const id='sensor.ev_charge_controller_status';
    hass.states[id]={...hass.states[id],attributes:{...hass.states[id].attributes,observed_charging:null,connected:null}};
    refresh();
  });
  assert.equal(await page.locator('ev-charge-dashboard').evaluate(el=>el.shadowRoot.querySelector('main').scrollWidth<=el.clientWidth),true);
},{width:320,height:844}));
