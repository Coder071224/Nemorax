window.NEMORAX_SITE_CONFIG = {
  github: {
    owner: "Coder071224",
    repo: "Nemorax",
    releaseTag: "",
    assets: {
      windows: "Nemorax.exe",
      android: "Nemorax.apk"
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
    // Railway-hosted Flet web app used by the website's "Open web app" button.
    webUrl: "https://nemoraxweb-production.up.railway.app"
  },
  api: {
    localBaseUrl: "http://localhost:8000",
    // Production backend URL (Railway)
    productionBaseUrl: "https://nemorax-production.up.railway.app",
    baseUrl: ["localhost", "127.0.0.1"].includes(window.location.hostname)
      ? "http://localhost:8000"
      : "https://nemorax-production.up.railway.app"
  }
};
