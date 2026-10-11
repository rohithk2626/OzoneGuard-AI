/* Login and signup forms -> Firebase Authentication (email + password) via js/account.js.
 * Passwords go straight from the browser to Firebase; the OzoneGuard backend never sees them. */
(() => {
  const form = document.querySelector('form[data-mode]');
  if (!form) return;
  const mode = form.dataset.mode;                      // "login" or "register"
  const msg = form.querySelector('.msg');
  const button = form.querySelector('button[type=submit]');
  const say = (text, kind) => { msg.textContent = text; msg.style.color = { ok: '#1f7a3a', err: '#b42318', info: '#6b5200' }[kind || 'info']; };

  if (!OGAccount.configured) {
    say('Accounts are not set up yet: add your Firebase settings to frontend/js/firebase-config.js (steps in docs/firebase-setup.md). The rest of the site works without signing in.');
  }

  /* Already signed in? Say so instead of showing an empty form. */
  let submitting = false;
  OGAccount.onUser(user => {
    if (!user || submitting) return;
    const who = user.displayName || user.email;
    form.querySelectorAll('.f, label, .form-links, button[type=submit]').forEach(el => { el.style.display = 'none'; });
    say(`You are signed in as ${who}.`, 'ok');
    if (!form.querySelector('.signed-in')) {
      msg.insertAdjacentHTML('afterend', '<p class="signed-in" style="margin-top:16px"><a class="btn" href="dashboard.html">Go to your dashboard</a></p>');
    }
  });

  function validate(v) {
    const er = {};
    if (mode === 'register' && !(v.name || '').trim()) er.name = 'Enter your full name.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email || '')) er.email = 'Enter a valid email address.';
    if ((v.password || '').length < 8) er.password = 'Password must be at least 8 characters.';
    if (mode === 'register' && v.password !== v.confirm) er.confirm = 'Passwords do not match.';
    form.querySelectorAll('.e').forEach(x => { x.textContent = er[x.dataset.f] || ''; });
    return !Object.keys(er).length;
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(form));
    if (!validate(v)) return;
    submitting = true; button.disabled = true;
    say(mode === 'login' ? 'Signing in…' : 'Creating your account…');
    try {
      if (mode === 'login') await OGAccount.signIn(v.email.trim(), v.password, !!v.remember);
      else await OGAccount.signUp(v.name.trim(), v.email.trim(), v.password);
      say('Success. Taking you to your dashboard…', 'ok');
      location.href = 'dashboard.html';
    } catch (x) {
      submitting = false; button.disabled = false;
      say(OGAccount.message(x), 'err');
    }
  });

  const forgot = form.querySelector('#forgot');
  if (forgot) forgot.addEventListener('click', async e => {
    e.preventDefault();
    const email = (form.querySelector('[name=email]').value || '').trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return say('Type your email address above first, then click "Forgot password?".', 'err');
    try {
      await OGAccount.resetPassword(email);
      say('If an account exists for that email, a password reset link has been sent to it.', 'ok');
    } catch (x) { say(OGAccount.message(x), 'err'); }
  });
})();
