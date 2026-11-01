FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl ripgrep jq tree file make procps nodejs npm \
 && arch="$(dpkg --print-architecture)" \
 && [ "$arch" = "amd64" ] \
 && curl -fsSL -o /tmp/pwsh.tar.gz https://github.com/PowerShell/PowerShell/releases/download/v7.5.4/powershell-7.5.4-linux-x64.tar.gz \
 && mkdir -p /opt/microsoft/powershell/7 \
 && tar -xzf /tmp/pwsh.tar.gz -C /opt/microsoft/powershell/7 \
 && chmod +x /opt/microsoft/powershell/7/pwsh \
 && ln -s /opt/microsoft/powershell/7/pwsh /usr/local/bin/pwsh \
 && apt-get install -y --no-install-recommends "$(apt-cache search --names-only '^libicu[0-9]+$' | cut -d' ' -f1 | head -1)" \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/pwsh.tar.gz

RUN pip install --no-cache-dir pytest==8.4.2 ruff==0.14.2 setuptools wheel build \
 && useradd -m -u 1500 -s /bin/bash dev \
 && mkdir -p /work /opt/devtools && chown dev:dev /work

COPY op.py /opt/devtools/op.py
COPY gitconfig /home/dev/.gitconfig
COPY ssh_config /home/dev/.ssh/config
RUN chown -R dev:dev /home/dev && chmod 700 /home/dev/.ssh

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 POWERSHELL_TELEMETRY_OPTOUT=1 PYTHONDONTWRITEBYTECODE=1
USER dev
WORKDIR /work
CMD ["sleep", "infinity"]
