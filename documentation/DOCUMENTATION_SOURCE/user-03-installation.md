# 🪟 Installation Guide

## What the Installer Actually Does

HORIZON GRID is a **self-hosted** tool: instead of sending your indicators to someone else's cloud service, you run the entire product on a Windows machine you control. "IOC" stands for **Indicator of Compromise** — a piece of evidence such as an IP address, domain, URL, file hash, or CVE ID (a public vulnerability identifier) that a security analyst wants to investigate.

When you run the installer, you are not just copying a single program onto your machine. You are setting up a small, self-contained application stack — the platform's web interface, its own database, and several supporting background services — all bundled together and running only on this one Windows computer. The internal databases behind the platform are locked to this computer only and are never reachable from anywhere else on your network. The platform's own web interface, however, is genuinely usable from other devices on the same local network, not only from this computer — the installer sets this up automatically (a Windows Firewall rule scoped to your Private network, plus automatic detection of this machine's network address), and the app itself figures out the right address to talk to no matter which device opened it. See "Accessing From Another Computer" below for how to actually do this; if you'd rather keep the platform usable only from this machine, restrict access at your Windows firewall.

You do not need to understand how those internal pieces fit together to install and use the product. This guide only covers what you, the administrator, will see and click. A full technical breakdown of the underlying architecture is provided separately for readers who want it.

## ✅ Before You Begin: Prerequisites

Two things matter before you start the installer:

- **Administrator privileges.** You must run the installer as a Windows administrator. The installer checks for this and will not proceed without it.
- **Docker Desktop, installed and running.** This is the important one to understand: the platform's real, working services — its database, its background job runners, its web server — do not run as ordinary Windows programs. They run inside **Docker containers**, which is a standardized way of packaging and running software in isolated, self-contained units. Docker Desktop is the engine that makes those containers run on Windows. If Docker Desktop is not installed and running before you start, the installer's prerequisite check will flag it and prompt you to fix it before continuing.

Think of the installer as putting the platform's files in place and Docker Desktop as what actually breathes life into them afterward. Both are required.

## Step-by-Step: Running the Installer

The installer is a standard Windows setup wizard (built with Inno Setup, a common Windows installer framework). It walks you through a short series of screens before copying any files.

[FIGURE: 01-installer-destination.png | The installer's "Select Destination Location" page, where the administrator confirms or changes the folder on this machine where the platform's program files will be installed.]

[FIGURE: 02-installer-tasks.png | The installer's "Select Additional Tasks" page, where the administrator chooses optional extras — such as creating a desktop icon — before installation begins.]

On the next screen, the installer summarizes everything it is about to do before it touches your system.

[FIGURE: 03-installer-ready.png | The installer's "Ready to Install" summary page, giving the administrator a final review of the chosen destination and selected tasks before clicking Install.]

After you click through, the installer copies the platform's program files to your chosen location. This step only places files on disk — it does not yet start any services or ask you for any configuration. When it's done, you'll see the final screen:

[FIGURE: 04-installer-finished.png | The installer's "Completing Setup" page, confirming the file copy has finished successfully.]

## What Happens Next

Once you close the installer, the **Setup Wizard launches automatically**. This is a separate, second stage — a dedicated desktop application (not a web page) that collects your administrator account details, your AI configuration, and your threat-intelligence provider API keys, and then does the actual work of building and starting the Docker containers described above. That process is covered in the next section, "Setup Wizard."

## 🌐 Accessing From Another Computer

Once setup finishes, the platform is usable both from this computer and from any other device on the same local network — a second laptop, a colleague's desktop, even a phone or tablet's browser, as long as it's connected to the same Wi-Fi or Ethernet network. Nothing needs to be edited or reconfigured to make this work; it's set up automatically during installation.

**How to connect from another device.** The Setup Wizard's final page shows two links: one for using the platform on this computer, and a second one labeled for other devices on the network. Open that second link's address (it looks like `http://` followed by a set of numbers and a port, for example `192.168.1.125:3000`) in a browser on the other device. You'll land on the same sign-in page described in the next chapter, and everything from there on works identically to using the platform locally.

If you don't have that page open anymore, the same address is always available afterward from inside the app itself: sign in, open **Providers** in the top navigation, and select the **Network Access** tab. It shows the address for this computer and the address for other devices side by side, with a button to copy the second one so you can send it to whoever needs it.

**What makes this work.** The installer creates a Windows Firewall rule that allows the platform's two ports through, but only on networks Windows classifies as **Private** (the setting you're asked about the first time you connect to a new Wi-Fi network or Ethernet connection).

> [!IMPORTANT]
> The firewall rule never opens on Public networks, and never opens the platform to the wider internet. This is deliberate: the feature is meant for a trusted home or office network, the same network your other devices are already on, not for remote access from elsewhere.

> [!TIP]
> **If a second device can't connect:**
> - Make sure both devices are actually on the same network, and that the network is set to **Private** in Windows (check under Settings → Network & Internet on the computer running the platform) — the firewall rule intentionally will not open the ports on a network marked Public.
> - If the address shown doesn't work, your router may have assigned this computer a new network address since setup last ran (this can happen after a restart). Re-run **Configuration** from the Start Menu (Start Menu → IOC Intelligence Platform → Configuration) to re-detect it — no need to reinstall.
> - The Network Access tab will say "Not detected" if the wizard couldn't determine a network address automatically (uncommon, but possible on unusual network setups). The platform still works fine from this computer either way; re-running Configuration is worth trying to pick it up.
