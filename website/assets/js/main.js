(function () {
  const siteConfig = window.NEMORAX_SITE_CONFIG || {};
  const github = siteConfig.github || {};
  const githubAssets = github.assets || {};
  const release = {
    version: "1.0.0",
    channel: "Initial Release",
    updated: "April 12, 2026",
    downloads: {
      windows: {
        url: "",
        label: "Windows distribution pending publication",
        status: "Use this card for the official .exe link once the signed installer is published."
      },
      android: {
        url: "",
        label: "Android distribution pending publication",
        status: "Use this card for the official .apk link once the beta package is ready for direct download."
      }
    }
  };
  const configuredRelease = siteConfig.release || {};
  release.version = configuredRelease.version || release.version;
  release.channel = configuredRelease.channel || release.channel;
  release.updated = configuredRelease.updated || release.updated;

  function buildGitHubReleaseUrl(assetName) {
    if (!github.owner || !github.repo || !assetName) {
      return "";
    }

    const base = github.releaseTag
      ? `https://github.com/${github.owner}/${github.repo}/releases/download/${github.releaseTag}`
      : `https://github.com/${github.owner}/${github.repo}/releases/latest/download`;
    return `${base}/${assetName}`;
  }

  if (!release.downloads.windows.url) {
    release.downloads.windows.url = buildGitHubReleaseUrl(githubAssets.windows || "");
  }

  if (!release.downloads.android.url) {
    release.downloads.android.url = buildGitHubReleaseUrl(githubAssets.android || "");
  }

  if (release.downloads.windows.url) {
    release.downloads.windows.label = "Download Windows build";
    release.downloads.windows.status = "Official Windows release hosted through GitHub Releases.";
  }

  if (release.downloads.android.url) {
    release.downloads.android.label = "Download Android build";
    release.downloads.android.status = "Official Android APK hosted through GitHub Releases.";
  }

  document.querySelectorAll("[data-release-version]").forEach((node) => {
    node.textContent = release.version;
  });
  document.querySelectorAll("[data-release-channel]").forEach((node) => {
    node.textContent = release.channel;
  });
  document.querySelectorAll("[data-release-updated]").forEach((node) => {
    node.textContent = release.updated;
  });

  function renderDownloadSlot(host, platform) {
    if (!host || !release.downloads[platform]) {
      return;
    }

    const config = release.downloads[platform];
    host.innerHTML = "";

    if (config.url) {
      const link = document.createElement("a");
      link.className = "download-button";
      link.href = config.url;
      link.rel = "noopener";
      link.textContent = platform === "windows" ? "Download Windows build" : "Download .apk";
      host.appendChild(link);
    } else {
      const disabled = document.createElement("span");
      disabled.className = "download-button--disabled";
      disabled.textContent = config.label;
      host.appendChild(disabled);
    }

    const status = document.createElement("p");
    status.className = "download-card__status";
    status.textContent = config.status;
    host.appendChild(status);
  }

  renderDownloadSlot(document.querySelector("[data-download-windows]"), "windows");
  renderDownloadSlot(document.querySelector("[data-download-android]"), "android");

  const toggle = document.querySelector(".menu-toggle");
  const nav = document.querySelector(".site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      nav.classList.toggle("is-open", !expanded);
    });

    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        toggle.setAttribute("aria-expanded", "false");
        nav.classList.remove("is-open");
      });
    });
  }

  const revealNodes = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) || revealNodes.length === 0) {
    revealNodes.forEach((node) => node.classList.add("in"));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) {
        return;
      }

      const delay = Number(entry.target.getAttribute("data-delay") || 0);
      window.setTimeout(() => {
        entry.target.classList.add("in");
      }, delay);
      observer.unobserve(entry.target);
    });
  }, {
    threshold: 0.08
  });

  revealNodes.forEach((node) => observer.observe(node));
})();
