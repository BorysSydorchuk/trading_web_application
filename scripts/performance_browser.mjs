// Native Node WebSocket/CDP only. Fresh private Chrome, loopback targets, no packages.
import fs from 'node:fs'
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(input.origin) || !Number.isInteger(input.debugPort)) throw Error('loopback only')
const targets = await (await fetch(`http://127.0.0.1:${input.debugPort}/json/list`)).json()
const target = targets.find(t => t.type === 'page')
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject })
let sequence = 0
const pending = new Map()
let receiver
const network = []
ws.onmessage = event => {
  const msg = JSON.parse(event.data)
  if (input.profile && msg.method?.startsWith('Network.') && msg.params?.requestId) {
    const p = msg.params
    if (['Network.requestWillBeSent', 'Network.responseReceived', 'Network.loadingFinished'].includes(msg.method))
      network.push({event:msg.method, id:p.requestId, timestamp:p.timestamp, url:p.request?.url ?? p.response?.url})
  }
  if (msg.id) {
    const item = pending.get(msg.id)
    pending.delete(msg.id)
    if (msg.error) item?.reject(Error(msg.error.message)); else item?.resolve(msg.result)
  } else if (msg.method === 'Runtime.bindingCalled' && msg.params.name === '__perfReport') {
    receiver?.(JSON.parse(msg.params.payload))
  }
}
function call(method, params = {}) {
  const id = ++sequence
  return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })) })
}
await call('Page.enable')
await call('Runtime.enable')
if (input.profile) {
  await call('Profiler.enable')
  await call('Profiler.setSamplingInterval', {interval:1000})
  await call('Performance.enable')
}
await call('Network.enable')
await call('Network.setBlockedURLs', { urls: ['https://*', 'http://*.anthropic.com/*'] })
await call('Runtime.addBinding', { name: '__perfReport' })
await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
await call('Page.addScriptToEvaluateOnNewDocument', { source: `
window.__perfPending = 0; window.__perfErrors = []; window.__perfRequests = [];
const originalFetch = window.fetch;
window.fetch = async (...args) => {
  const url = String(args[0]);
  if (!url.includes('/api/')) return originalFetch(...args);
  window.__perfPending++;
  const start = performance.now();
  try {
    const response = await originalFetch(...args);
    window.__perfRequests.push({url, status:response.status, ms:performance.now()-start});
    if (!response.ok) window.__perfErrors.push('HTTP '+response.status+' '+url);
    return response;
  } finally {window.__perfPending--;}
};
function usable() {
  const main = document.querySelector('main'); if (!main || main.querySelector('[role=alert]')) return false;
  const path = location.pathname;
  if (!main.querySelector('h1')) return false;
  const titles = {'/':'Головна','/journal':'Журнал','/digests':'Дайджести','/calculator':'Калькулятор'};
  if (main.querySelector('h1').textContent !== titles[path]) return false;
  if (path === '/' && !main.querySelector('#dashboard-accounts')) return false;
  if ((path === '/journal' || path === '/digests') && !main.querySelector('table tbody tr')) return false;
  if (path === '/' || path === '/calculator') {
    const symbol = main.querySelector('select[id$="-symbol"]');
    if (!symbol || symbol.disabled || symbol.options.length < 5) return false;
  }
  return window.__perfPending === 0;
}
window.__perfUsable = usable;
let finished = false;
function watch() {
  if (finished) return;
  if (usable()) requestAnimationFrame(() => requestAnimationFrame(() => {
    if (finished) return;
    if (!usable()) {setTimeout(watch, 5); return;}
    finished = true;
    window.__perfReport(JSON.stringify({path:location.pathname, ms:performance.now(),
      requests:window.__perfRequests, errors:window.__perfErrors,
      navigation:performance.getEntriesByType('navigation')[0]?.toJSON(),
      title:document.querySelector('main h1')?.textContent}));
  }));
  else setTimeout(watch, 5);
}
addEventListener('DOMContentLoaded', watch);
setTimeout(() => {if (!finished) {finished=true; window.__perfReport(JSON.stringify({path:location.pathname,
  failed:true, errors:window.__perfErrors, text:document.querySelector('main')?.innerText?.slice(0,300)}));}}, 15000);
` })
async function visit(path) {
  if (input.profile) await call('Profiler.start')
  const metricsBefore = input.profile ? await call('Performance.getMetrics') : null
  const networkStart = network.length
  const result = new Promise((resolve, reject) => {
    receiver = resolve
    setTimeout(() => reject(Error('browser measurement timeout')), 20000).unref()
  })
  await call('Page.navigate', { url: input.origin + path })
  const data = await result
  if (input.profile) {
    data.profile = (await call('Profiler.stop')).profile
    data.metricsBefore = metricsBefore
    data.metricsAfter = await call('Performance.getMetrics')
    data.network = network.slice(networkStart)
  }
  if (data.failed || data.errors.length) throw Error(JSON.stringify(data))
  return data
}
try {
  const pages = input.homeOnly ? ['/'] : ['/', '/journal', '/digests', '/calculator']
  const priming = []
  const samples = Object.fromEntries(pages.map(path => [path, []]))
  if (!input.homeOnly) for (const path of pages) priming.push(await visit(path))
  for (let n = 0; n < (input.repetitions ?? 1); n++) for (const path of pages) samples[path].push(await visit(path))
  const spa = Object.fromEntries(pages.map(path => [path, []]))
  if (!input.homeOnly) {
    for (let n = 0; n <= input.repetitions; n++) for (const path of pages) {
      const expression = `(async () => {
        const expected = ${JSON.stringify(path)};
        const began = performance.now();
        const link = [...document.querySelectorAll('a')].find(a => a.getAttribute('href') === expected);
        if (!link) throw Error('Missing sidebar route');
        link.click();
        return await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(Error('SPA readiness timeout')), 15000);
          function poll() {
            if (location.pathname === expected && window.__perfUsable()) requestAnimationFrame(() => requestAnimationFrame(() => {
              if (!window.__perfUsable()) {setTimeout(poll,5); return;}
              clearTimeout(timer); resolve({path:expected, ms:performance.now()-began});
            })); else setTimeout(poll,5);
          }
          poll();
        });
      })()`
      const result = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
      if (result.exceptionDetails) throw Error('SPA measurement failed')
      if (n) spa[path].push(result.result.value)
    }
  }
  const version = await call('Browser.getVersion')
  process.stdout.write(JSON.stringify({priming, samples, spa, version}))
} finally { ws.close() }
