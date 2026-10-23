/** Copy for sign-in, demo sign-in and sign-out (api-conventions §7, §7.1). */
export const authMessages = {
  login: {
    title: "Sign in",
    intro: "Use your work email and password.",
    email: "Email",
    password: "Password",
    submit: "Sign in",
    submitting: "Signing in…",
    // One message for every wrong email/password combination: no account enumeration.
    invalid: "That email and password don't match an active account. Check them and try again.",
    rateLimited: (minutes: number | null) =>
      minutes ? `Too many sign-in attempts. Try again in ${minutes} ${minutes === 1 ? "minute" : "minutes"}.` : "Too many sign-in attempts. Wait a few minutes, then try again.",
    locked: "This account is temporarily locked after repeated failed attempts. Try again later or ask your administrator.",
    blocked: "Sign-in was blocked by a security check. Reload this page and try again.",
    network: "Lamikraft One can't be reached. Check your connection and try again.",
    generic: "Sign-in didn't work because of a problem on our side. Try again in a moment.",
    errorTitle: "Couldn't sign you in",
    emailRequired: "Enter your email.",
    passwordRequired: "Enter your password.",
  },
  demo: {
    title: "Demo sign-in",
    checking: "Signing you in to the demo workspace…",
    missingTitle: "This page needs a demo sign-in link",
    missingBody: "Open the full demo link you were given. If you have an account, sign in with your email instead.",
    invalidTitle: "This demo link can't be used",
    invalidBody: "Demo links work once and expire. Ask for a new link, or sign in with your email.",
    errorTitle: "Couldn't complete the demo sign-in",
    retry: "Try again",
    toLogin: "Go to sign-in",
  },
  signOut: {
    title: "Sign out",
    body: "Sign out of Lamikraft One on this device?",
    confirm: "Sign out",
    working: "Signing out…",
    cancel: "Back to Today",
    failed: "You're still signed in. Lamikraft One couldn't reach the server to sign you out. Try again.",
  },
  requestId: "Reference",
} as const;
