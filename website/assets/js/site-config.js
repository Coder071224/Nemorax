window.NEMORAX_SITE_CONFIG = {
  github: {
    owner: "Coder071224",
    repo: "Nemorax",
    releaseTag: "v1.1.1",
    assets: {
      windows: "Nemis-Installer.exe",
      android: "Nemis.apk"
    }
  },
  release: {
    version: "1.0.0",
    channel: "Android APK Release",
    updated: "May 7, 2026",
    downloads: {
      windows: {
        url: "downloads/Nemis-Installer.exe",
        download: "Nemis-Installer.exe",
        label: "Download Nemis Installer",
        status: "Official Windows installer direct download from this website."
      },
      android: {
        url: "downloads/Nemis.apk",
        label: "Download Android APK",
        status: "Official Android APK direct download from this website."
      }
    }
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
