window.NEMORAX_SITE_CONFIG = {
  github: {
    owner: "Coder071224",
    repo: "Nemorax",
    releaseTag: "v1.1.1",
    assets: {
      windows: "Nemorax.exe",
      android: "app-release.apk"
    }
  },
  release: {
    version: "1.0.0",
    channel: "Initial Release",
    updated: "April 12, 2026"
  },
  support: {
    email: "",
    customDomain: ""
  },
  app: {
    // Render-hosted Flet web app used by the website's "Open web app" button.
    webUrl: "https://nemorax-flet-web-it1f.onrender.com"
  },
  api: {
    localBaseUrl: "http://localhost:8000",
    // Primary production backend URL (Render). Railway may be kept as a manual fallback in deployed Flet env vars.
    productionBaseUrl: "https://nemorax-backend-c1ma.onrender.com",
    baseUrl: ["localhost", "127.0.0.1"].includes(window.location.hostname)
      ? "http://localhost:8000"
      : "https://nemorax-backend-c1ma.onrender.com"
  }
};
