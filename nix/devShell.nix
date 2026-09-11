{
  pkgs ? import <nixpkgs> { },
  python ? pkgs.python312,
  name ? "Zeloo-dev",
}:

pkgs.mkShell {
  inherit name;

  buildInputs = with pkgs; [
    python
    python.pkgs.venvShellHook
    python.pkgs.pip
    python.pkgs.setuptools
    python.pkgs.wheel
    git
    ripgrep
    fd
    nixpkgs-fmt
    nil
    gnumake
  ];

  shellHook = ''
    if [ ! -d ".venv" ]; then
      python -m venv .venv
    fi
    source .venv/bin/activate
    pip install -e ".[dev]" || true
    export PYTHONPATH=$(pwd):$PYTHONPATH
    echo "Zeloo dev shell ready. Run: Zeloo doctor"
  '';

  env = {
    PYTHONDONTWRITEBYTECODE = "1";
  };
}