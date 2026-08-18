# First-Run Configuration

Before you ever open a browser and type in an IOC (Indicator of Compromise -- a piece of evidence such as an IP address, domain, or file hash that a security analyst wants to investigate), you'll meet HORIZON GRID's Setup Wizard. This is a native Windows desktop application (built the traditional WinForms way, not a web page you'd load in a browser) that runs once, right after the installer finishes, and walks you through every decision the platform needs before it can start working: who the administrator is, which AI model will do the analysis, which third-party threat-intelligence sources you want to plug in, and which network ports it should use on this machine.

None of these choices are permanent traps -- everything set here can be revisited later by re-running the same wizard from the "Configuration" shortcut the installer creates. But for a first-time administrator, this is where the platform's whole configuration model gets introduced, so it's worth walking through page by page.

## Welcome

The wizard opens with a simple Welcome page that confirms you're about to configure HORIZON GRID and sets expectations for what's coming next: an administrator account, an AI model choice, provider setup, a network port review, and finally installation itself.

[FIGURE: 05-wizard-welcome.png | The Setup Wizard's Welcome page, the first screen a new administrator sees after the installer finishes.]

## Setting Up the Administrator Account

The next page asks for the details of the very first user account: an email address, an optional full name, and a password (typed twice, to confirm it).

[FIGURE: 06-wizard-admin-empty.png | The Administrator Account page with its fields still blank, showing exactly what information the wizard needs to create the first user.]

This page's own note that the first account "gets the Admin role -- see docs/SECURITY.md" is pointing at a file inside the product's source code, for developers who have it checked out -- not something you need to go find. Everything that file says about roles is covered in plain language in this manual's Security and Data Handling section, so nothing is missing if you don't have code access.

[FIGURE: 07-wizard-admin-filled.png | The same Administrator Account page after an email address, name, and password have been entered.]

This page looks like an ordinary "create your account" form, but it quietly does something more important: **whoever registers here becomes the platform's administrator, automatically, with no extra step.** The platform has a simple, fixed rule for this -- the very first account ever registered on a fresh installation is automatically granted administrator rights. The moment that happens, the public sign-up page closes itself: anyone who tries to register through the web app afterward (for example, a colleague who wants an account of their own) is turned away and told to ask an administrator instead, rather than quietly being handed a lesser account. There's no separate "make me an admin" checkbox or database edit required; it's purely a matter of being first. Because the Setup Wizard registers your account before anyone else can reach the platform, filling in this page is what makes you the administrator -- and every colleague's account after that has to be created for them from the Administration page, where you pick their role up front.

If you run the wizard again later to *reconfigure* an installation that's already up and running, this page behaves a little differently, since an administrator account already exists. You can simply leave the email and password fields blank to keep that account exactly as it is. Or, if you'd like to sign in for this session -- which is what enables the live Test Connection buttons on the pages that follow -- re-enter your existing email and password here; the wizard will log you in without creating a new account or changing the existing one.

[FIGURE: 28-wizard-admin-reconfigure-note.png | The Administrator Account page on a reconfigure run, with guidance explaining that leaving the fields blank keeps the existing account unchanged, while re-entering the existing email and password signs in for the session and enables the Test Connection buttons below.]

## Choosing an AI Model

Every investigation the platform runs ends with an AI-generated summary that pulls together what all the different intelligence sources found. This page is where you decide which AI does that work.

[FIGURE: 08-wizard-aiconfig.png | The AI Configuration page, where the administrator chooses which AI model will generate the AI-written summaries and final assessment for every investigation. (This screenshot predates the Groq backend described below; the page now offers a fifth choice alongside Ollama, Anthropic, Bedrock, and Gemini.)]

You have two broad options here:

- **A free local AI model**, which runs entirely on your own machine via Ollama. It costs nothing, requires no account or API key, and keeps everything on-premises -- a good default if you just want to get started.
- **A cloud AI provider** instead, if you'd rather use a more capable hosted AI model from a third-party service. The wizard currently supports four such providers: Anthropic, Amazon Bedrock, Google Gemini, and Groq (a fast-inference API service). Each requires an account and an API key with that provider.

Whichever backend you choose, this page now has a live **Test Connection** button that sends a minimal, real request to that provider and reports a genuine result -- not a placeholder or an automatic green checkmark. A working setup reports something like "Connected. Model replied: 'pong' (model: llama-3.3-70b-versatile, 245 ms)", including the real model that answered and the actual round-trip latency. A broken one reports a specific, real reason instead of a vague failure -- for example, an invalid key, an unrecognized model name, or a provider rate limit.

[FIGURE: 29-wizard-aiconfig-groq.png | The AI Configuration page with the Groq backend selected, showing the masked API key field and the Model dropdown set to llama-3.3-70b-versatile.]

[FIGURE: 30-wizard-aiconfig-groq-test-success.png | The AI Configuration page after clicking Test Connection for the Groq backend, showing the real success result: "OK: Connected. Model replied: 'pong' (model: llama-3.3-70b-versatile, 245 ms)".]

Either way, it's worth setting expectations early: the AI's job throughout this platform is to help you read and correlate a lot of raw intelligence data faster -- it is analytical assistance, not an unquestionable verdict. Later in the platform, every AI-written summary and verdict comes paired with an Evidence Ledger and "show your reasoning"-style verification tools that let you check exactly which underlying data the AI actually drew on, rather than just taking its word for it. You'll see this play out directly later in this guide, including a real case where two intelligence sources disagreed about the same IP address and the AI's own verdict was worth double-checking against the evidence.

## Threat Intelligence Providers

This page is where you connect the platform to outside sources of threat intelligence -- third-party services and databases (like VirusTotal or AbuseIPDB) that have already collected information about known-malicious IPs, domains, files, and more. The wizard lets you configure up to eight such providers here.

[FIGURE: 12-wizard-providers-configured.png | The Threat Intelligence Providers page, with API keys entered for VirusTotal, AbuseIPDB, and AlienVault OTX -- shown here as masked dots rather than the real key text.]

A few things worth knowing about this page:

- **Every provider is optional.** You don't need to fill in all eight, or even any of them, to finish setup. A couple of the providers listed here (for example, the U.S. government's NVD vulnerability database) work out of the box with no key at all -- an API key for those just raises how many requests per minute you're allowed, it doesn't switch the provider on or off.
- **Each key is entered once and masked.** Once typed, a key shows only as dots on screen, the same way a password field would, so it isn't left visible.
- **Each provider has a live "Test" button.** Clicking it immediately checks whether the key you just entered actually works against that provider's real service, so you find out about a typo or an expired key during setup rather than during your first real investigation.

In the interest of full transparency: the screenshot above is from this very evaluation of the platform, and the keys entered for VirusTotal, AbuseIPDB, and AlienVault OTX are real, working keys used to test the product -- not placeholder or example values.

## Network Ports

The next page lets you review which network ports on this Windows machine the platform will use once it's installed and running.

[FIGURE: 09-wizard-ports.png | The Network Ports page, where the administrator can review (and change, if needed) which ports the platform will use on this machine.]

Most administrators can simply accept the defaults shown here and move on. This page exists mainly for the case where something else already running on the same machine is using one of the same ports -- in which case you can change the platform's port here before installation begins, rather than running into a conflict afterward.

## Reviewing the Summary

Before anything is actually installed, the wizard shows a summary of every choice made so far -- the administrator account, the AI model selection, the ports, and how many threat-intelligence providers were configured.

[FIGURE: 10-wizard-summary.png | The Ready to Install summary page, giving the administrator one last look at every setting before installation begins.]

[FIGURE: 13-wizard-providers-summary.png | The same summary page reporting "Providers configured: 6 of 8" for this evaluation.]

That "6 of 8" line is a good illustration of how flexible provider setup really is: it counts both the providers where a real key was entered and the providers that work with no key required at all, added together. Your own installation might show a different number -- three, six, or zero -- and the platform will install and run just as well either way. Nothing on this page is a point of no return; if something looks wrong, you can still go back and change it before clicking through to install.

## Installation Complete

Once you confirm the summary, the wizard takes over and does the heavy lifting on its own: it pulls down and starts every service the platform needs, waits until the platform reports itself healthy, and then registers your administrator account using the exact details you typed in earlier -- so by the time this page appears, your account already exists and works.

[FIGURE: 11-wizard-installed.png | The Setup Wizard's final page, confirming that installation finished successfully and the platform is ready to use.]

This step can take a few minutes the first time, since it's downloading and starting up everything the platform depends on. Once it's done, you're ready to open the platform in a browser and sign in with the administrator account you just created.

[FIGURE: 15-login.png | The web app's Sign in page. Enter the administrator email and password you set on the wizard's Admin Account page and click Sign in -- this is the screen you'll land on every time you open the platform in a browser from now on.]
