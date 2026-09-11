{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  name = "Zeloo-dev";

  buildInputs = with pkgs; [
    python311
    python311Packages.venv
    git
    sqlite
    gcc
    pkg-config
    libsqlite3-dev
    openssl
    zlib
    nodejs_20
    uv
  ];

  zeloo_VERSION = "0.21.0";

  shellHook = ''
    echo "=== Zeloo Development Shell ===" >&2
    echo "Python: $(python --version)" >&2
    echo "SQLite:  $(sqlite3 --version)" >&2
    echo "Node:    $(node --version)" >&2
    echo "UV:      $(uv --version)" >&2
    echo "" >&2

    if [ ! -d .venv ]; then
      echo "Creating Python venv..." >&2
      ${pkgs.python311Packages.venv}/bin/venv .venv
      source .venv/bin/activate
      uv sync
    else
      source .venv/bin/activate
    fi

    if [ ! -f .env ]; then
      cp .env.example .env 2>/dev/null || true
      echo "Created .env — please fill in your API keys" >&2
    fi
  '';

  LD_LIBRARY_PATH = with pkgs; [
    stdenv.cc.cc.lib
    sqlite-out
    openssl.out
  ];
}
