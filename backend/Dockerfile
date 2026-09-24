FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl nmap ca-certificates gnupg apt-transport-https lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Metasploit Framework (official omnibus installer) -- backs the Pentest
# Suite's gated real-exploit-validation feature (app/pentest/exploit.py).
# msfrpcd is started bound to 127.0.0.1 only (see docker-compose.yml's
# backend `command:`), so it's reachable from nowhere but this container's
# own backend process -- never exposed on the Docker network or the host.
# This is a large (~1-2GB), heavy addition on purpose -- it's real offensive
# tooling, added deliberately, not a transitive dependency.
#
# Pinned to a specific commit (not the mutable `master` branch) with a
# checksum check before execution -- previously this fetched
# .../master/... and piped straight into `sh`, so a compromised or
# force-pushed master branch could execute arbitrary code as root during
# every image build with no way to detect it. To roll the pin forward,
# fetch the new commit's raw URL, verify the checksum out-of-band, and
# update both MSFINSTALL_COMMIT and MSFINSTALL_SHA256 together.
ENV MSFINSTALL_COMMIT=21d459344aa291e9d8c0abdd6cbd9806fdb84791
ENV MSFINSTALL_SHA256=d12fea4d1339ebecb09d8cc36920d9f5e5e7e9fffbe092b1e1cd09255cc16825
RUN curl -fsSL "https://raw.githubusercontent.com/rapid7/metasploit-omnibus/${MSFINSTALL_COMMIT}/config/templates/metasploit-framework-wrappers/msfupdate.erb" -o /tmp/msfinstall \
    && echo "${MSFINSTALL_SHA256}  /tmp/msfinstall" | sha256sum -c - \
    && chmod 755 /tmp/msfinstall \
    && /tmp/msfinstall \
    && rm -f /tmp/msfinstall
# Pre-builds the module cache into this image layer -- a cold cache build on
# first container start took long enough to look like a hung boot. Non-fatal
# if this particular invocation exits non-zero (e.g. no DB configured,
# which this deployment intentionally never sets up -- see exploit.py's own
# comment on why); the cache still gets built either way.
RUN timeout 300 msfconsole -qx 'exit' < /dev/null || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
