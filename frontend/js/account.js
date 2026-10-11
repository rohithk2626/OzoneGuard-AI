/* Accounts (Firebase Authentication, email + password) and saved locations.
 *
 * Signed in      -> saved locations live in Firestore at users/{uid}/locations
 *                   (only that user can read or write them: firebase/firestore.rules).
 * Not signed in  -> saved locations live in this browser only (localStorage).
 * Not configured -> same as "not signed in"; the login page says accounts are not set up.
 *
 * The Firebase SDK is downloaded only when js/firebase-config.js has been filled in.
 */
const OGAccount = (() => {
  const SDK = 'https://www.gstatic.com/firebasejs/10.14.1/';
  const cfg = window.OG_FIREBASE_CONFIG || {};
  const configured = !!(cfg.apiKey && cfg.projectId && cfg.appId);
  const LOCAL_KEY = 'og_saved_locations';
  const MAX_SAVED = 20;

  let user = null, known = false, initPromise = null, initError = null;
  const listeners = [];

  const loadScript = src => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.onload = resolve;
    s.onerror = () => reject(new Error('Could not load the Firebase SDK. Check your internet connection.'));
    document.head.appendChild(s);
  });

  let settle;
  const settled = new Promise(resolve => { settle = resolve; });      // resolves once we know who (if anyone) is signed in
  function publish(u) { user = u; known = true; settle(); listeners.forEach(cb => { try { cb(user); } catch (_) {} }); }
  const whenKnown = () => { init(); return settled; };

  function init() {
    if (!configured) { if (!known) publish(null); return Promise.resolve(false); }
    if (!initPromise) initPromise = (async () => {
      try {
        await loadScript(SDK + 'firebase-app-compat.js');
        await Promise.all([loadScript(SDK + 'firebase-auth-compat.js'), loadScript(SDK + 'firebase-firestore-compat.js')]);
        if (!firebase.apps.length) firebase.initializeApp(cfg);
        firebase.auth().onAuthStateChanged(publish);
        return true;
      } catch (e) { initError = e; publish(null); return false; }
    })();
    return initPromise;
  }

  async function need() {
    if (!configured) throw new Error('Accounts are not set up yet. Fill in frontend/js/firebase-config.js (see docs/firebase-setup.md).');
    if (!(await init())) throw initError || new Error('Firebase could not start.');
  }

  /* Call cb(user or null) now if the state is known, and again whenever it changes. */
  function onUser(cb) { listeners.push(cb); if (known) cb(user); init(); }

  const FRIENDLY = {
    'auth/email-already-in-use': 'An account with this email already exists. Sign in instead.',
    'auth/invalid-email': 'That email address is not valid.',
    'auth/weak-password': 'Choose a stronger password (at least 8 characters).',
    'auth/invalid-credential': 'Email or password is incorrect.',
    'auth/wrong-password': 'Email or password is incorrect.',
    'auth/user-not-found': 'Email or password is incorrect.',
    'auth/user-disabled': 'This account has been disabled.',
    'auth/too-many-requests': 'Too many attempts. Wait a few minutes and try again.',
    'auth/network-request-failed': 'Network problem. Check your internet connection.',
    'auth/operation-not-allowed': 'Email/Password sign-in is not enabled in the Firebase console (Authentication > Sign-in method).',
    'auth/configuration-not-found': 'Authentication is not enabled for this Firebase project yet (Build > Authentication > Get started).',
    'auth/api-key-not-valid.-please-pass-a-valid-api-key.': 'The apiKey in firebase-config.js is not valid.',
    'auth/invalid-api-key': 'The apiKey in firebase-config.js is not valid.',
    'permission-denied': 'Firestore refused this. Publish firebase/firestore.rules in the Firebase console and make sure you are signed in.',
    'unavailable': 'Could not reach Firestore. Check your internet connection.',
    'failed-precondition': 'Firestore is not created for this project yet (Build > Firestore Database > Create database).'
  };
  const message = e => FRIENDLY[e && e.code] || (e && e.message) || 'Something went wrong.';

  async function signUp(name, email, password) {
    await need();
    const cred = await firebase.auth().createUserWithEmailAndPassword(email, password);
    if (name) { await cred.user.updateProfile({ displayName: name }); publish(firebase.auth().currentUser); }
    return cred.user;
  }
  async function signIn(email, password, remember = true) {
    await need();
    const P = firebase.auth.Auth.Persistence;
    await firebase.auth().setPersistence(remember ? P.LOCAL : P.SESSION);
    return (await firebase.auth().signInWithEmailAndPassword(email, password)).user;
  }
  async function signOut() { await need(); await firebase.auth().signOut(); }
  async function resetPassword(email) { await need(); await firebase.auth().sendPasswordResetEmail(email); }

  /* ---------------------------------------------------------- saved locations */
  const clean = p => ({
    name: String(p.name || '').trim().slice(0, 80) || `${Number(p.lat).toFixed(3)}, ${Number(p.lon).toFixed(3)}`,
    lat: +Number(p.lat).toFixed(5), lon: +Number(p.lon).toFixed(5), createdAt: Date.now()
  });
  const same = (a, b) => Math.abs(a.lat - b.lat) < 0.0005 && Math.abs(a.lon - b.lon) < 0.0005;
  const readLocal = () => { try { return JSON.parse(localStorage.getItem(LOCAL_KEY) || '[]'); } catch (_) { return []; } };
  const writeLocal = rows => { try { localStorage.setItem(LOCAL_KEY, JSON.stringify(rows)); } catch (_) {} };
  const col = () => firebase.firestore().collection('users').doc(user.uid).collection('locations');
  const mode = () => (user ? 'cloud' : 'device');

  async function list() {
    await whenKnown();
    if (!user) return readLocal().sort((a, b) => b.createdAt - a.createdAt);
    const snap = await col().get();
    return snap.docs.map(d => ({ id: d.id, ...d.data() })).sort((a, b) => b.createdAt - a.createdAt);
  }
  async function add(place) {
    const row = clean(place);
    if (!Number.isFinite(row.lat) || !Number.isFinite(row.lon)) throw new Error('Pick a location first.');
    const rows = await list();
    const dup = rows.find(r => same(r, row));
    if (dup) return { ...dup, already: true };
    if (rows.length >= MAX_SAVED) throw new Error(`You can save up to ${MAX_SAVED} locations. Remove one first.`);
    if (!user) { const saved = { id: 'd' + row.createdAt, ...row }; writeLocal([saved, ...rows]); return saved; }
    const ref = await col().add(row);
    return { id: ref.id, ...row };
  }
  async function remove(id) {
    await whenKnown();
    if (!user) return writeLocal(readLocal().filter(r => r.id !== id));
    await col().doc(id).delete();
  }

  return { configured, onUser, whenKnown, signUp, signIn, signOut, resetPassword, message,
           locations: { list, add, remove, mode, MAX: MAX_SAVED }, get user() { return user; } };
})();
window.OGAccount = OGAccount;
