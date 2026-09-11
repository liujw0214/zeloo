Name:           zeloo
Version:        0.1.0
Release:        1%{?dist}
Summary:        Self-hosted, self-evolving resident AI Agent runtime
License:        Apache-2.0
URL:            https://github.com/your-org/Zeloo
Source0:        https://github.com/your-org/Zeloo/archive/refs/tags/v%{version}.tar.gz
BuildArch:      x86_64
Requires:       python3 >= 3.11
Requires:       python3-virtualenv
Requires:       ca-certificates
BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  systemd

%description
Zeloo is a self-hosted, self-evolving AI agent runtime framework.

It ships with a three-layer System Prompt (stable / context / volatile),
multi-provider LLM routing across 40+ backends, more than 90 built-in
tools (file, web, shell, code execution, browser, image gen), 18+
messaging platform adapters (Telegram, Discord, Slack, WeChat, Lark,
...) and 39 web search providers (Tavily, Brave, Perplexity, Google,
Bing, SerpAPI, ...).

Workspace state is persisted in SQLite with FTS5 indexing; skills can
be hot reloaded, evolved, and audited via the curator lifecycle.

%prep
%autosetup -n Zeloo-%{version}

%build
# Build the native Rust extension (FTS5 CJK tokenizer) on demand.
if [ -d native/fts5_cjk ]; then
    (cd native/fts5_cjk && cargo build --release)
fi

# Materialise a reproducible virtualenv that we ship inside the package.
%{__python3} -m venv %{buildroot}/opt/zeloo/venv
%{buildroot}/opt/zeloo/venv/bin/pip install --no-cache-dir --quiet \
    --upgrade pip
%{buildroot}/opt/zeloo/venv/bin/pip install --no-cache-dir --quiet .
PYTHONPATH=%{buildroot}/opt/zeloo/venv/lib/python3.11/site-packages \
    %{buildroot}/opt/zeloo/venv/bin/python -c "import zeloo_cli" || true

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}/opt/zeloo
install -d %{buildroot}%{_unitdir}
install -d %{buildroot}%{_sysconfdir}/zeloo
install -d %{buildroot}/var/lib/zeloo

# Move the prepared venv from %build into the buildroot.
cp -a %{_builddir}/opt/zeloo/venv %{buildroot}/opt/zeloo/

# CLI wrapper.
install -m 0755 packaging/deb/zeloo/usr/bin/zeloo %{buildroot}%{_bindir}/zeloo

# Default profile template.
install -m 0644 config.yaml.example %{buildroot}%{_sysconfdir}/zeloo/config.yaml

# Systemd unit (kept here as the canonical source).
cat > %{buildroot}%{_unitdir}/zeloo.service <<'EOF'
[Unit]
Description=Zeloo Resident AI Agent Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=zeloo
Group=zeloo
WorkingDirectory=/var/lib/zeloo
Environment=ZELOO_HOME=/var/lib/zeloo
ExecStart=/opt/zeloo/venv/bin/python -m zeloo_cli run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

%files
%defattr(-,root,root,-)
%license LICENSE
%doc README.md docs/
%{_bindir}/zeloo
/opt/zeloo/venv
%{_unitdir}/zeloo.service
%{_sysconfdir}/zeloo/config.yaml
%dir /var/lib/zeloo

%pre
# Create the dedicated system user before files are laid down.
getent group zeloo >/dev/null || /usr/sbin/groupadd -r zeloo
getent passwd zeloo >/dev/null || \
    /usr/sbin/useradd -r -g zeloo -d /var/lib/zeloo -s /sbin/nologin \
        -c "Zeloo resident agent" zeloo
exit 0

%post
# Enable and start the service on initial install, restart on upgrade.
%systemd_post zeloo.service

# Bootstrap the workspace directory tree.
mkdir -p /var/lib/zeloo/{workspace,archive,profile,memory,skills,logs}
chown -R zeloo:zeloo /var/lib/zeloo
chmod 0750 /var/lib/zeloo

echo "Zeloo has been installed."
echo "Run 'sudo -u zeloo /usr/bin/zeloo doctor' to verify the install."
echo "Run 'sudo -u zeloo /usr/bin/zeloo install' for first-run setup."

%preun
# On full uninstall (action 0), stop and disable the service.
if [ "$1" -eq 0 ]; then
    %systemd_preun zeloo.service
fi
exit 0

%postun
# On full uninstall (action 0), leave the data directory alone so the
# operator can recover state if the removal was accidental.
if [ "$1" -eq 0 ]; then
    echo "Zeloo has been removed. Data in /var/lib/zeloo was preserved."
    echo "To wipe it manually: rm -rf /var/lib/zeloo"
fi
%systemd_postun_with_restart zeloo.service
exit 0

%changelog
* Mon Sep 11 2026 Zeloo Team <team@zeloo.io> - 0.1.0-1
- Initial package for the 0.1.0 release.
