/* Firebase settings for accounts and saved locations.
 *
 * 1. Create a project at https://console.firebase.google.com
 * 2. Add a Web app (</> icon) and copy the values it shows into the fields below.
 * 3. Build > Authentication > Sign-in method: enable "Email/Password".
 * 4. Build > Firestore Database: create it, then paste firebase/firestore.rules into its Rules tab.
 * Full steps: docs/firebase-setup.md
 *
 * These web values are identifiers, not passwords: Firebase expects them to be in
 * the page. Access is protected by the sign-in step and the Firestore rules.
 * While the fields are empty the site still works; saved locations are then kept
 * in this browser only and the login page explains that accounts are not set up.
 */
window.OG_FIREBASE_CONFIG = {
  apiKey: "",
  authDomain: "",
  projectId: "",
  appId: ""
};
