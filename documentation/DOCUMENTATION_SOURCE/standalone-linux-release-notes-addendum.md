# 🐧 Linux Release Notes

We're excited to bring **HORIZON GRID to Linux**. If you've been running HORIZON GRID on Windows and asked when Linux support was coming, the answer is now -- this release adds native, real support for **Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, and Debian 12 (bookworm)**.

## 🎁 What you get

This isn't a stripped-down or "coming later" port -- it's the exact same application you already know: the same investigation pipeline, threat scoring, AI-assisted analysis, provider integrations, dashboards, and case management, running from the same code as the Windows release. There is no feature gap to work around and nothing to relearn.

Installation is a familiar native experience for Linux users: a standard `.deb` package you install with `apt`, a guided terminal setup wizard (the direct counterpart to the Windows setup wizard) that walks you through your administrator account, AI configuration, and threat intelligence providers, and a simple `horizon-grid` command for everyday operation (`start`, `stop`, `status`, `backup`, and more). Under the hood, HORIZON GRID runs as a set of Docker containers, so your data and configuration are handled the same safe, self-contained way as on Windows.

## 🐳 Before you install: Docker matters

> [!IMPORTANT]
> There's one prerequisite worth calling out up front, because it's easy to
> get wrong: HORIZON GRID needs the **Docker Compose plugin**, and the
> version of Docker that comes from your distribution's own package
> repository (`docker.io`) typically does not include it. Installing
> `docker.io` alone and stopping there will leave you unable to start
> HORIZON GRID.

The fix is simple -- install Docker using **Docker's own official installation method** before you install HORIZON GRID:

```bash
curl -fsSL https://get.docker.com | sh
```

(Alternatively, you can add Docker's official apt repository by hand, following the instructions at docs.docker.com.) Either way gets you the real Docker Compose plugin that HORIZON GRID depends on.

## 🚀 Get started

For step-by-step instructions -- including the Docker prerequisite, running the setup wizard, and everyday commands -- see the **Linux Installation Guide**.
