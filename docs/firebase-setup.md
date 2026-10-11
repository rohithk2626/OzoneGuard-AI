# Accounts and saved locations (Firebase)

Login, signup and saved locations use **Firebase Authentication** (email + password) and
**Cloud Firestore**. Both are on Firebase's free "Spark" plan. Nothing here touches the
FastAPI backend: the browser talks to Firebase directly, so the backend never sees a password.

Until you finish the steps below, the site still works. The login page says accounts are
not set up, and "Save this location" keeps places in the current browser only.

> Menu names in the Firebase console change from time to time. If a label differs slightly,
> look for the closest match.

## One-time setup (about 10 minutes)

1. **Create a project.** Go to <https://console.firebase.google.com>, sign in with a Google
   account, choose *Add project* (or *Create a project*), name it (for example
   `ozoneguard-ai`). Google Analytics is not needed; you can turn it off.

2. **Register a web app.** On the project overview page click the web icon `</>`, give the app
   a nickname, and click *Register app*. Firebase shows a `firebaseConfig` block.
   Copy these four values into `frontend/js/firebase-config.js`:

   ```js
   window.OG_FIREBASE_CONFIG = {
     apiKey: "…",
     authDomain: "….firebaseapp.com",
     projectId: "…",
     appId: "…"
   };
   ```

   These are identifiers, not secrets; Firebase expects them to be visible in the page.
   What protects the data is the sign-in step plus the rules in step 4.

3. **Turn on email/password sign-in.** *Build → Authentication → Get started → Sign-in method
   → Email/Password → Enable → Save.*

4. **Create the database and publish the rules.** *Build → Firestore Database → Create
   database.* Pick a location (for India, `asia-south1 (Mumbai)`), choose *production mode*,
   and create it. Then open the **Rules** tab, replace everything with the contents of
   `firebase/firestore.rules`, and click **Publish**.

5. **(Only if sign-in is refused from your address)** *Authentication → Settings → Authorized
   domains.* `localhost` is there by default. If you open the site as `http://127.0.0.1:8000`
   and Firebase complains about the domain, add `127.0.0.1`, or open the site as
   `http://localhost:8000` instead.

## Check that it works

1. Start the site with `uvicorn backend.main:app --reload`, then open `http://localhost:8000/signup.html`.
2. Create an account. You should land on the dashboard and see your name in the top bar.
   In the Firebase console, *Authentication → Users* now lists that email.
3. On the Location page pick a point and click **Save this location**. The message should say
   *Saved to your account*. In the console, *Firestore Database → Data* shows
   `users / <your user id> / locations / <one document>`.
4. Sign out and sign in again: the saved location is still on the dashboard.
5. On the login page, **Forgot password?** sends Firebase's standard reset email.

## What is stored

| Where | What |
|---|---|
| Firebase Authentication | email, password hash (managed by Firebase), display name |
| Firestore `users/{uid}/locations/{id}` | `name`, `lat`, `lon`, `createdAt` (milliseconds) |

Each user can read, add and delete only their own locations (`firebase/firestore.rules`).
A user can save up to 20 locations (checked in `frontend/js/account.js`).

Places saved in a browser *before* signing in stay in that browser; they are not copied into
the account automatically.

## Common messages

| Message on the site | Fix |
|---|---|
| "Accounts are not set up yet" | Fill in `frontend/js/firebase-config.js` (step 2). |
| "Email/Password sign-in is not enabled" | Step 3. |
| "Firestore refused this" | Publish `firebase/firestore.rules` (step 4) and make sure you are signed in. |
| "Firestore is not created for this project yet" | Create the database (step 4). |
| "The apiKey in firebase-config.js is not valid" | Re-copy the config block from the console (step 2). |

## How it was tested, and what was not

The pages were tested in a headless browser against a stand-in for Firebase (signup, login,
wrong password, sign out, save, list, remove, forgot password), and against the real Firebase
SDK offline to confirm every SDK call the code makes exists. **A real Firebase project was not
used**, so the first real signup and the Firestore rules above should be checked once with
the steps in "Check that it works".
