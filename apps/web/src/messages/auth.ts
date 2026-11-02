/** Copy for sign-in, demo sign-in and sign-out (api-conventions §7, §7.1). */
export const authMessages = {
  login: {
    title: "Sign in",
    intro: "Use your work email and password.",
    email: "Email",
    password: "Password",
    showPassword: "Show password",
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
  showcase: {
    eyebrow: "Crown / Lamikraft",
    headline: ["Your day,", "prepared."],
    lede: "Briefings, quotes, materials and the people behind them, in one place. Sign in to open yours.",
    stageLabel: "Four material swatches from the catalogue, stacked like boards on a bench",
    swatchNote: "Illustrative material swatches, not product photos.",
    scrollHint: "What Lamikraft One does",
    story: [
      {
        number: "01",
        title: "A briefing for each person.",
        body: "Every morning the briefing lists what needs you: decisions, replies and changes to the records you own, with the evidence beside each one and a plain next step.",
      },
      {
        number: "02",
        title: "Ask in plain words.",
        body: "The assistant works through the same services as every screen. It drafts; you decide. Nothing leaves without your review, and every action keeps its receipt.",
      },
      {
        number: "03",
        title: "Real materials, real numbers.",
        body: "Prices come from active price lists, totals from the server, previews from each product's own specification. Nothing on screen is estimated.",
      },
    ],
    backToTop: "Back to sign-in",
  },
  requestId: "Reference",
} as const;
