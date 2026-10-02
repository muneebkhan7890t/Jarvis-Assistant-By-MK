'use strict';
let speaker = null;
function clearSpeaker(state) {
  for (const source of state.sources) { try { source.stop(); } catch {} }
  state.sources.clear();
  state.next = state.context.currentTime;
}
function stopSpeaker() {
  const state = speaker;
  speaker = null;
  if (!state) return;
  clearSpeaker(state);
  state.socket?.close();
  state.context.close().catch(() => {});
  if (document.getElementById('speakerState')) document.getElementById('speakerState').textContent = 'Phone speaker off';
}
async function startSpeaker() {
  if (speaker) return;
  const state = {context: new AudioContext(), sources: new Set(), next: 0};
  speaker = state;
  try {
    await state.context.resume();
    const grant = await post('audio-ticket', {});
    if (speaker !== state) return;
    const socket = new WebSocket(`wss://${location.host}/remote-listen?ticket=${encodeURIComponent(grant.ticket)}`);
    state.socket = socket;
    socket.binaryType = 'arraybuffer';
    socket.onmessage = event => {
      if (speaker !== state || document.hidden) return;
      if (typeof event.data === 'string') {
        try { if (JSON.parse(event.data).type === 'clear') clearSpeaker(state); } catch {}
        return;
      }
      if (event.data.byteLength > 8192 || event.data.byteLength % 2) { stopSpeaker(); return; }
      if (state.next - state.context.currentTime > 2) {
        stopSpeaker(); say('Phone speaker stopped because playback fell behind.'); return;
      }
      const pcm = new DataView(event.data);
      const buffer = state.context.createBuffer(1, pcm.byteLength / 2, 24000);
      const samples = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) samples[i] = pcm.getInt16(i * 2, true) / 32768;
      const source = state.context.createBufferSource();
      source.buffer = buffer; source.connect(state.context.destination);
      state.sources.add(source);
      source.onended = () => { state.sources.delete(source); source.disconnect(); };
      state.next = Math.max(state.next, state.context.currentTime + .03);
      source.start(state.next); state.next += buffer.duration;
    };
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = () => reject(Error('Phone speaker connection failed'));
      socket.onclose = () => reject(Error('Phone speaker connection was refused'));
    });
    if (speaker !== state) { socket.close(); return; }
    socket.onclose = () => { if (speaker === state) { stopSpeaker(); say('Phone speaker disconnected.'); } };
    document.getElementById('speakerState').textContent = 'Phone speaker on — shared assistant audio';
  } catch (error) { if (speaker === state) stopSpeaker(); throw error; }
}
document.addEventListener('visibilitychange', () => { if (document.hidden) stopSpeaker(); });
window.addEventListener('pagehide', stopSpeaker);

async function pushRegistration() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window))
    throw Error('Push is unavailable in this browser. On iPhone, add this page to the Home Screen and open it there.');
  await navigator.serviceWorker.register('/remote-sw.js', {scope: '/'});
  return navigator.serviceWorker.ready;
}
async function enablePush() {
  if (!('Notification' in window)) throw Error('This browser does not support notifications.');
  // Request permission in the button gesture, before network awaits.
  if (await Notification.requestPermission() !== 'granted') throw Error('Notifications are blocked in this browser. Check its site permissions.');
  const status = await post('push-status', {});
  if (!status.available) throw Error('Install requirements-push.txt on the PC first.');
  const registration = await pushRegistration();
  const raw = status.public_key.replaceAll('-', '+').replaceAll('_', '/');
  const key = Uint8Array.from(atob(raw + '='.repeat((4 - raw.length % 4) % 4)), c => c.charCodeAt(0));
  let sub = await registration.pushManager.getSubscription();
  if (sub && sub.options.applicationServerKey && !new Uint8Array(sub.options.applicationServerKey).every((v, i) => v === key[i])) {
    await sub.unsubscribe(); sub = null;
  }
  let created = false;
  if (!sub) { sub = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key}); created = true; }
  try { await post('push-subscribe', {subscription: sub.toJSON()}); }
  catch (error) { if (created) await sub.unsubscribe(); throw error; }
  say('Alerts enabled for future task results. Delivery depends on your browser and network.');
  await show('Notifications');
}
async function disablePush() {
  await post('push-unsubscribe', {});
  const registration = await navigator.serviceWorker?.getRegistration('/');
  const sub = await registration?.pushManager.getSubscription();
  if (sub) await sub.unsubscribe();
  say('Background alerts disabled. Saved results remain in your inbox.');
  await show('Notifications');
}
async function pushControls(card) {
  const status = await post('push-status', {});
  card.append(node('p', 'Background alerts: ' + status.status),
    node('p', 'Opt in to generic lock-screen alerts through your browser’s push provider. Project names, logs and chat text are not included. The PC must stay running. Open the private inbox through Tailscale for details.'),
    button(status.subscribed ? 'Re-enable alerts' : 'Enable phone alerts', enablePush));
  if (status.subscribed) card.append(button('Disable phone alerts', disablePush));
}
