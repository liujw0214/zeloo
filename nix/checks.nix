{
  pkgs ? import <nixpkgs> { },
  self ? null,
}:

let
  python = pkgs.python312;
in
{
  pytest = pkgs.runCommand "pytest-run" { } ''
    set -euo pipefail
    cd ${self.packages.${pkgs.system}.Zeloo.src}
    ${python.withPackages (p: [ p.pytest ])}/bin/pytest tests -q --tb=short || exit 1
    touch $out
  '';

  ruff = pkgs.runCommand "ruff-check" { } ''
    cd ${self.packages.${pkgs.system}.Zeloo.src}
    ${python.withPackages (p: [ p.ruff ])}/bin/ruff check . || exit 1
    touch $out
  '';

  format = pkgs.runCommand "format-check" { } ''
    cd ${self.packages.${pkgs.system}.Zeloo.src}
    ${python.withPackages (p: [ p.ruff ])}/bin/ruff format --check . || exit 1
    touch $out
  '';
}