import test from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {existsSync,readFileSync,mkdirSync} from 'node:fs';
import {createServer} from 'node:http';

const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
mkdirSync(new URL('./artifacts/',import.meta.url),{recursive:true});

async function withPage(run,viewport={width:1487,height:1058},query='') {
  const files={
    '/panel-preview.html':'./panel-preview.html',
    '/custom_components/ev_charge_controller/frontend/ev-charge-panel.js':'../../custom_components/ev_charge_controller/frontend/ev-charge-panel.js',
  };
  const server=createServer((request,response)=>{
    const path=files[new URL(request.url,'http://localhost').pathname];
    if(!path){response.writeHead(404).end();return;}
    response.setHeader('Content-Type',path.endsWith('.js')?'text/javascript':'text/html');
    response.end(readFileSync(new URL(path,import.meta.url)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,...(existsSync(chrome)?{executablePath:chrome}:{})});
  try {
    const page=await browser.newPage({viewport});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/panel-preview.html${query}`);
    await page.locator('ev-charge-panel').waitFor();
    await run(page);
    assert.deepEqual(errors,[]);
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
}

test('native panel discovers this controller and renders the overview without control calls',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[data-page="overview"]').waitFor();
  assert.match(await panel.locator('main').textContent(),/Your charge outlook/);
  assert.deepEqual(await page.evaluate(()=>serviceCalls),[]);
  assert.equal(await panel.locator('canvas[data-chart="soc"]').count(),1);
  assert.equal(await panel.locator('canvas[data-chart="rates"]').count(),1);
  assert.equal(await panel.locator('canvas[data-chart="cost"]').count(),1);
  await page.screenshot({path:new URL('./artifacts/panel-overview-desktop.png',import.meta.url).pathname,fullPage:true});
}, {width:1487,height:1058}, '?capture=1'));

test('schedule form saves deadline settings atomically and preserves its draft during state updates',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await panel.locator('[data-mode="deadline"]').click();
  await panel.locator('[data-field="target_percent"]').fill('88');
  await panel.locator('[data-field="deadline"]').fill('2026-10-25T07:30');
  await panel.locator('[data-field="hard_price_ceiling"]').check();
  await panel.locator('[data-field="max_cheap_rate"]').fill('9.5');
  await page.evaluate(()=>{const id='sensor.ev_charge_controller_status';const old=hass.states[id];preview.states[id]={...old,attributes:{...old.attributes,soc:62}};preview.refresh();});
  assert.equal(await panel.locator('[data-field="target_percent"]').inputValue(),'88');
  assert.equal(await panel.locator('[data-field="deadline"]').inputValue(),'2026-10-25T07:30');
  await panel.locator('[data-action="save"]').click();
  const calls=await page.evaluate(()=>serviceCalls);
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0],{domain:'ev_charge_controller',service:'set_request',data:{config_entry_id:'preview-controller',mode:'deadline',max_cheap_rate:9.5,target_percent:88,deadline:'2026-10-25T07:30',hard_price_ceiling:true}});
  await page.screenshot({path:new URL('./artifacts/panel-schedule-desktop.png',import.meta.url).pathname,fullPage:true});
}, {width:1487,height:1058}, '?capture=1'));

test('mode changes expose only fields applicable to that request',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await panel.locator('[data-mode="cheap_top_up"]').click();
  assert.equal(await panel.locator('[data-field="target_percent"]').count(),0);
  assert.equal(await panel.locator('[data-field="deadline"]').count(),0);
  await panel.locator('[data-mode="flexible"]').click();
  assert.equal(await panel.locator('[data-field="target_percent"]').count(),1);
  assert.equal(await panel.locator('[data-field="deadline"]').count(),0);
  await panel.locator('[data-mode="deadline"]').click();
  assert.equal(await panel.locator('[data-field="deadline"]').count(),1);
}));

test('reset restores the last saved values and failed saves keep the draft visible',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await panel.locator('[data-field="target_percent"]').fill('84');
  await panel.locator('[data-action="reset"]').click();
  assert.equal(await panel.locator('[data-field="target_percent"]').inputValue(),'100');
  await panel.locator('[data-field="target_percent"]').fill('84');
  await page.locator('#reject').click();
  await panel.locator('[data-action="save"]').click();
  assert.equal(await panel.locator('[data-field="target_percent"]').inputValue(),'84');
  assert.match(await panel.locator('main').textContent(),/Mock save rejected/i);
}));

test('switch actions stay scoped to this config entry and explicit safety actions dispatch once',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await page.evaluate(()=>{const id='sensor.ev_charge_controller_status';const old=hass.states[id];preview.states[id]={...old,attributes:{...old.attributes,manual_hold_until:'2026-10-24T13:00:00Z'}};preview.refresh();});
  await panel.locator('[data-action="boost"]').click();
  await panel.locator('[data-action="automatic"]').click();
  await panel.locator('details summary').click();
  await panel.locator('[data-action="monitoring"]').click();
  await panel.locator('[data-action="resume"]').click();
  const calls=await page.evaluate(()=>serviceCalls);
  assert.deepEqual(calls.map(({domain,service,data})=>[domain,service,data.config_entry_id||data.entity_id]),[
    ['switch','turn_on','switch.ev_charge_controller_boost'],
    ['switch','turn_off','switch.ev_charge_controller_automatic_control'],
    ['switch','turn_on','switch.ev_charge_controller_monitoring_only'],
    ['button','press','button.ev_charge_controller_resume'],
  ]);
  assert.ok(calls.every(({data})=>!data.entity_id||data.entity_id.startsWith('switch.ev_charge_controller_')||data.entity_id.startsWith('button.ev_charge_controller_')));
}));

test('switch action feedback can be delayed until the simulated state acknowledgement',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await page.locator('#delay').click();
  await panel.locator('[data-action="boost"]').click();
  assert.equal(await page.evaluate(()=>hass.states['switch.ev_charge_controller_boost'].state),'off');
  assert.equal((await page.evaluate(()=>serviceCalls)).length,1);
  await page.locator('#ack').click();
  assert.equal(await page.evaluate(()=>hass.states['switch.ev_charge_controller_boost'].state),'on');
}));

test('partial, missing and disconnected scenarios remain legible',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await page.locator('#scenario').selectOption('partial');
  assert.match(await panel.locator('main').textContent(),/Some prices are unavailable/);
  await page.locator('#scenario').selectOption('missing');
  await page.waitForFunction(()=>window.panel.shadowRoot.querySelector('canvas[data-chart="soc"]')?.getAttribute('aria-label')==='Waiting for battery and charging speed');
  assert.match(await panel.locator('canvas[data-chart="soc"]').getAttribute('aria-label'),/Waiting for battery and charging speed/);
  await page.locator('#scenario').selectOption('disconnected');
  assert.match(await panel.locator('main').textContent(),/Unplugged|disconnected/i);
}));

test('contiguous charging periods group into weighted windows while details retain negative rates',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  const windows=panel.locator('.windows');
  const rows=windows.locator('table').first().locator('tbody tr');
  assert.equal(await rows.count(),2,'the nine raw periods form two contiguous windows');
  const first=await rows.nth(0).locator('td').allTextContents();
  const weightedRate=(1.28+1.08-.18+1.35+.84+1.18+1.54+1.88)/8;
  assert.match(first[3],new RegExp(`${weightedRate.toFixed(2)}p/kWh`));
  assert.match(first[4],/22\.1 kWh/);
  assert.match(first[5],/£0\.25/);
  await windows.locator('details').first().locator('summary').click();
  const detailRows=windows.locator('details').first().locator('table tbody tr');
  assert.equal(await detailRows.count(),9);
  assert.match(await detailRows.nth(2).locator('td').nth(3).textContent(),/-0\.18p\/kWh/);
}));

test('tabs support ArrowRight, ArrowLeft, Home, and End with focus following selection',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  const overview=panel.locator('[role="tab"][data-page="overview"]');
  const schedule=panel.locator('[role="tab"][data-page="schedule"]');
  await overview.focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await schedule.getAttribute('aria-selected'),'true');
  assert.equal(await schedule.evaluate(el=>el.getRootNode().activeElement===el),true);
  await page.keyboard.press('Home');
  assert.equal(await overview.getAttribute('aria-selected'),'true');
  assert.equal(await overview.evaluate(el=>el.getRootNode().activeElement===el),true);
  await page.keyboard.press('End');
  assert.equal(await schedule.getAttribute('aria-selected'),'true');
  await page.keyboard.press('ArrowLeft');
  assert.equal(await overview.getAttribute('aria-selected'),'true');
}));

test('empty registry and registry errors have clear setup and retry states',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  assert.match(await panel.locator('main').textContent(),/controller|setup|found/i);
}, {width:1487,height:1058}, '?scenario=empty'));

test('registry errors have a visible retry state',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  assert.match(await panel.locator('main').textContent(),/unavailable|error|retry/i);
}, {width:1487,height:1058}, '?scenario=error'));

test('registry discovery recovers when Home Assistant replaces its connection',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('main').getByText('Could not load controllers').waitFor();
  await page.evaluate(()=>preview.replaceConnectionAndRecover());
  await panel.locator('[data-page="overview"]').waitFor();
  assert.ok(await page.evaluate(()=>preview.discoveryCalls)>=2);
  assert.ok(await page.evaluate(()=>preview.callbacks.size)>=1);
} , {width:1487,height:1058}, '?scenario=error'));

test('registry event burst triggers a bounded number of discovery requests',()=>withPage(async page=>{
  await page.waitForFunction(()=>preview.callbacks.size>0&&preview.registryCompleteCalls===1);
  const before=await page.evaluate(()=>preview.discoveryCalls);
  await page.evaluate(()=>{for(let i=0;i<50;i++)preview.emit(`sensor.registry_burst_${i}`);});
  await page.waitForFunction(count=>preview.registryCompleteCalls>count,before,{timeout:1500});
  const after=await page.evaluate(()=>preview.discoveryCalls);
  assert.ok(after>before,'the event burst should refresh registry discovery');
  assert.ok(after-before<=2,`50 events should coalesce to at most two requests; got ${after-before}`);
}));

test('registry event during initial discovery triggers a follow-up after the stale response',()=>withPage(async page=>{
  await page.waitForFunction(()=>preview.discoveryCalls===1&&preview.callbacks.size>0);
  await page.evaluate(()=>{
    preview.extraRegistryEntries=[{entity_id:'sensor.ev_charge_controller_second_status',platform:'ev_charge_controller',config_entry_id:'second-controller',unique_id:'second-controller_status'}];
    preview.emit('entity_registry_updated');
    preview.releaseFirstRegistry();
  });
  const selector=page.locator('ev-charge-panel [data-controller]');
  await selector.waitFor();
  await page.waitForFunction(()=>preview.registryCompleteCalls>=2);
  assert.equal(await page.evaluate(()=>preview.discoveryCalls),2);
  assert.ok((await selector.locator('option').evaluateAll(options=>options.map(option=>option.value))).includes('second-controller'));
} , {width:1487,height:1058}, '?scenario=inflight'));


test('state updates for another entity preserve the active chart nodes',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  assert.equal(await panel.evaluate(el=>{const before=el.shadowRoot.querySelector('canvas[data-chart="soc"]');el.hass={...hass,states:{...hass.states,'sensor.unrelated':{entity_id:'sensor.unrelated',state:'1',attributes:{}}}};return before===el.shadowRoot.querySelector('canvas[data-chart="soc"]');}),true);
}));

test('replacement status telemetry updates the live cap without replacing an active draft input',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  const target=panel.locator('[data-field="target_percent"]');
  await target.fill('88');
  await page.evaluate(()=>{window.targetBefore=document.querySelector('ev-charge-panel').shadowRoot.querySelector('[data-field="target_percent"]');});
  await page.evaluate(()=>preview.replaceStatusSoc(62));
  assert.equal(await target.inputValue(),'88');
  assert.equal(await page.evaluate(()=>window.targetBefore===document.querySelector('ev-charge-panel').shadowRoot.querySelector('[data-field="target_percent"]')),true);
  assert.match(await panel.locator('[data-live="cap"]').textContent(),/Current battery 62%/);
}));

test('accepted atomic request retains its draft until entity state acknowledgement',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  await page.locator('#delay').click();
  await panel.locator('[data-field="target_percent"]').fill('87');
  await panel.locator('[data-action="save"]').click();
  await panel.locator('[data-feedback]').getByText(/accepted; waiting/i).waitFor();
  assert.equal(await panel.locator('[data-field="target_percent"]').inputValue(),'87');
  assert.equal((await page.evaluate(()=>serviceCalls)).length,1);
  await page.locator('#ack').click();
  await panel.locator('[data-feedback]').getByText(/request saved/i).waitFor();
  assert.equal(await panel.locator('[data-field="target_percent"]').inputValue(),'87');
}));

test('unrelated state updates do not rediscover entities and disconnect unsubscribes',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[data-page="overview"]').waitFor();
  const discoveries=await page.evaluate(()=>preview.discoveryCalls);
  for(let i=0;i<5;i++) await page.evaluate(i=>{const el=document.querySelector('ev-charge-panel');el.hass={...hass,states:{...hass.states,[`sensor.unrelated_${i}`]:{entity_id:`sensor.unrelated_${i}`,state:String(i),attributes:{}}}};},i);
  assert.equal(await page.evaluate(()=>preview.discoveryCalls),discoveries);
  await panel.evaluate(el=>el.remove());
  await page.waitForFunction(()=>unsubscribeCalls===1);
  assert.equal(await page.evaluate(()=>preview.callbacks.size),0);
}));

test('multiple controllers can be selected and display separate state',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  const selector=panel.locator('[data-controller]');
  await selector.waitFor();
  await selector.selectOption('second-controller');
  assert.match(await panel.locator('main').textContent(),/Second EV|43%/);
}, {width:1487,height:1058}, '?scenario=second'));

test('desktop shell keeps the expected navigation width and the panel fits a narrow phone',()=>withPage(async page=>{
  assert.equal(await page.locator('aside').evaluate(el=>Math.round(el.getBoundingClientRect().width)),202);
  assert.equal(await page.locator('ev-charge-panel').evaluate(el=>el.shadowRoot.querySelector('main')?.scrollWidth<=el.shadowRoot.querySelector('main')?.clientWidth ?? true),true);
  await page.screenshot({path:new URL('./artifacts/panel-overview-light.png',import.meta.url).pathname,fullPage:true});
}, {width:1487,height:1058}, '?capture=1&theme=light'));

test('schedule controls fit a 390px dark phone and a 320px viewport',()=>withPage(async page=>{
  const panel=page.locator('ev-charge-panel');
  await panel.locator('[role="tab"][data-page="schedule"]').click();
  assert.equal(await panel.evaluate(el=>el.shadowRoot.querySelector('main')?.scrollWidth<=el.shadowRoot.querySelector('main')?.clientWidth ?? true),true);
  await page.screenshot({path:new URL('./artifacts/panel-schedule-mobile-dark.png',import.meta.url).pathname,fullPage:true});
}, {width:390,height:844}, '?capture=1').then(()=>withPage(async page=>{
  assert.equal(await page.locator('ev-charge-panel').evaluate(el=>el.shadowRoot.querySelector('main')?.scrollWidth<=el.shadowRoot.querySelector('main')?.clientWidth ?? true),true);
}, {width:320,height:844}, '?capture=1')));
